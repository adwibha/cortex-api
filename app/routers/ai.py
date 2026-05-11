"""
AI-powered endpoints backed by Ollama (local, free).

Models used:
- llama3.2:1b       — text generation (NL search, summarize, prioritize)
- nomic-embed-text  — embeddings (semantic search)
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.events.bus import publish, EventType
from app.models.job import JobType
from app.models.task import TaskORM
from app.models.user import UserORM
from app.routers.jobs import _enqueue_job
from app.schemas import (
    NLSearchRequest, NLSearchResponse,
    SummarizeResponse, PrioritizeResponse,
    SemanticSearchRequest, SemanticSearchResponse,
)
from app.services import ollama
from app.config import settings

router = APIRouter(tags=["ai"])
logger = logging.getLogger(__name__)


def _task_not_found(task_id: UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": "TASK_NOT_FOUND", "message": f"Task {task_id} not found"}, "request_id": ""},
    )


async def _fetch_owned_task(task_id: UUID, owner_id: UUID, db: AsyncSession) -> TaskORM:
    result = await db.execute(
        select(TaskORM).where(TaskORM.id == task_id, TaskORM.owner_id == owner_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise _task_not_found(task_id)
    return task


# ── Natural language search ──────────────────────────────────────────────────

@router.post("/tasks/search/natural-language", response_model=NLSearchResponse)
async def nl_search(
    payload: NLSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Parse a natural language query into structured filters and return matching tasks.

    Pipeline: user query → LLM → JSON filters → SQL → validated response
    """
    prompt = f"""You are a task search assistant. Convert the user's natural language query into JSON filters.

User query: "{payload.query}"

Return ONLY valid JSON with these optional fields:
- title_contains (string)
- completed (boolean)
- priority_gte (integer 0-5)
- priority_lte (integer 0-5)

Example: {{"completed": false, "priority_gte": 3}}

JSON:"""

    raw = await ollama.generate(prompt)
    filters = ollama.extract_json_object(raw) or {}

    if not isinstance(filters, dict):
        filters = {}
        logger.warning("LLM returned non-dict filters for query: %s", payload.query)

    query = select(TaskORM).where(TaskORM.owner_id == current_user.id)
    if filters.get("title_contains"):
        query = query.where(TaskORM.title.ilike(f"%{filters['title_contains']}%"))
    if filters.get("completed") is not None:
        query = query.where(TaskORM.completed == filters["completed"])
    if filters.get("priority_gte") is not None:
        query = query.where(TaskORM.priority >= filters["priority_gte"])
    if filters.get("priority_lte") is not None:
        query = query.where(TaskORM.priority <= filters["priority_lte"])

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()
    result = await db.execute(query.order_by(TaskORM.priority.desc()).limit(20))
    items = result.scalars().all()

    return NLSearchResponse(query=payload.query, filters=filters, items=list(items), total=total)


# ── Summarize ────────────────────────────────────────────────────────────────

@router.post("/tasks/{task_id}/summarize", response_model=SummarizeResponse)
async def summarize_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Summarize a task's title and description in 1-2 sentences using the local LLM."""
    task = await _fetch_owned_task(task_id, current_user.id, db)

    prompt = f"""Summarize this task concisely in 1-2 sentences:

Title: {task.title}
Description: {task.description or 'No description'}
Priority: {task.priority}/5
Status: {"Completed" if task.completed else "Pending"}

Summary:"""

    summary = (await ollama.generate(prompt)).strip()

    await publish(EventType.AI_SUMMARY_GENERATED, {
        "task_id": str(task_id),
        "user_id": str(current_user.id),
        "summary_length": len(summary),
    })

    return SummarizeResponse(task_id=task_id, summary=summary, model=settings.ollama_model)


# ── Prioritize ───────────────────────────────────────────────────────────────

@router.post("/tasks/{task_id}/prioritize", response_model=PrioritizeResponse)
async def prioritize_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Suggest a priority score (0–5) for a task based on its content."""
    task = await _fetch_owned_task(task_id, current_user.id, db)

    prompt = f"""Analyze this task and suggest a priority from 0 (lowest) to 5 (highest).

Title: {task.title}
Description: {task.description or 'No description'}
Current priority: {task.priority}

Return ONLY valid JSON:
{{"suggested_priority": <number 0-5>, "reasoning": "<brief reason>"}}

JSON:"""

    raw = await ollama.generate(prompt)
    parsed = ollama.extract_json_object(raw)

    suggested_priority = task.priority
    reasoning = "Unable to determine priority."

    if parsed:
        try:
            suggested_priority = max(0, min(5, int(parsed.get("suggested_priority", task.priority))))
            reasoning = parsed.get("reasoning", reasoning)
        except (TypeError, ValueError):
            logger.warning("Could not parse priority from LLM response: %s", raw)

    return PrioritizeResponse(
        task_id=task_id,
        suggested_priority=suggested_priority,
        reasoning=reasoning,
        model=settings.ollama_model,
    )


# ── Streaming ────────────────────────────────────────────────────────────────

@router.get("/tasks/{task_id}/ai-stream")
async def stream_task_analysis(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Stream AI analysis of a task token by token via Server-Sent Events."""
    task = await _fetch_owned_task(task_id, current_user.id, db)

    prompt = f"""Provide a brief analysis of this task including its complexity, potential blockers, and completion strategy:

Title: {task.title}
Description: {task.description or 'No description provided'}
Priority: {task.priority}/5

Analysis:"""

    return StreamingResponse(
        ollama.stream_tokens(prompt),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Semantic search ──────────────────────────────────────────────────────────

@router.post("/tasks/semantic-search", response_model=SemanticSearchResponse)
async def semantic_search(
    payload: SemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Semantic similarity search using pgvector embeddings.
    Falls back to keyword search when embeddings are unavailable.
    """
    try:
        query_embedding = await ollama.embed(payload.query)
        vector_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
        sql = text("""
            SELECT * FROM tasks
            WHERE owner_id = :owner_id
            AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)
        result = await db.execute(sql, {
            "owner_id": current_user.id,
            "embedding": vector_str,
            "limit": payload.limit,
        })
        items = [TaskORM(**dict(r._mapping)) for r in result.fetchall()]
    except Exception as exc:
        logger.warning("Semantic search fell back to keyword search: %s", exc)
        result = await db.execute(
            select(TaskORM)
            .where(TaskORM.owner_id == current_user.id)
            .where(TaskORM.title.ilike(f"%{payload.query}%"))
            .limit(payload.limit)
        )
        items = list(result.scalars().all())

    return SemanticSearchResponse(query=payload.query, items=items, total=len(items))


@router.post("/embeddings/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_embeddings(
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Enqueue a background job to recompute embeddings for all of the current user's tasks."""
    job = await _enqueue_job(db, task_id=None, job_type=JobType.reindex, user_id=current_user.id)
    return {"job_id": job.id, "status": "queued", "message": "Embedding reindex job enqueued"}
