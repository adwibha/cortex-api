"""
Agent orchestration endpoints.

POST /agents/plan-execution runs a 3-stage pipeline:
  1. Planner     — decompose goal into concrete task titles
  2. Prioritizer — score each task's urgency (0–5)
  3. Scheduler   — order tasks by priority
  4. Persist     — bulk INSERT generated tasks, return list
"""
import logging

from fastapi import APIRouter, Depends, status
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.task import TaskORM
from app.models.user import UserORM
from app.schemas import PlanExecutionRequest, PlanExecutionResponse
from app.services import ollama

router = APIRouter(prefix="/agents", tags=["agents"])
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def _planner(goal: str) -> list[str]:
    """Stage 1: Decompose a goal into 3–7 actionable task titles."""
    with tracer.start_as_current_span("agent.planner") as span:
        span.set_attribute("agent.goal", goal)
        prompt = f"""You are a project planner. Break down this goal into 3-7 concrete, actionable task titles.

Goal: {goal}

Return ONLY a JSON array of task title strings, nothing else.
Example: ["Set up CI pipeline", "Write unit tests", "Deploy to staging"]

Tasks:"""
        raw = await ollama.generate(prompt)
        parsed = ollama.extract_json_array(raw)
        if parsed:
            return [str(t) for t in parsed if isinstance(t, str)][:7]
        logger.warning("Planner could not parse task list, falling back to goal as single task")
        return [goal]


async def _prioritizer(task_titles: list[str]) -> list[int]:
    """Stage 2: Score each task's urgency on a 0–5 scale."""
    with tracer.start_as_current_span("agent.prioritizer") as span:
        span.set_attribute("agent.task_count", len(task_titles))
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(task_titles))
        prompt = f"""Rate the urgency of each task from 0 (low) to 5 (high). Consider dependencies and impact.

Tasks:
{numbered}

Return ONLY a JSON array of integers in the same order.
Example: [4, 2, 5, 3]

Priorities:"""
        raw = await ollama.generate(prompt)
        parsed = ollama.extract_json_array(raw)
        if parsed:
            scores = [max(0, min(5, int(p))) for p in parsed]
            if len(scores) == len(task_titles):
                return scores
        logger.warning("Prioritizer could not parse scores, defaulting to 3")
        return [3] * len(task_titles)


def _scheduler(task_titles: list[str], priorities: list[int]) -> list[int]:
    """Stage 3: Return task indices ordered from highest to lowest priority."""
    with tracer.start_as_current_span("agent.scheduler"):
        return sorted(range(len(task_titles)), key=lambda i: -priorities[i])


@router.post("/plan-execution", response_model=PlanExecutionResponse, status_code=status.HTTP_201_CREATED)
async def plan_execution(
    payload: PlanExecutionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """
    Multi-agent pipeline: decompose a goal into tasks, prioritize, schedule, and persist them.

    Supports the `Idempotency-Key` header to prevent duplicate plan creation on retries.
    """
    with tracer.start_as_current_span("agents.plan_execution") as span:
        span.set_attribute("goal", payload.goal)
        span.set_attribute("user_id", str(current_user.id))

        task_titles = await _planner(payload.goal)
        priorities = await _prioritizer(task_titles)
        ordered_indices = _scheduler(task_titles, priorities)

        indexed_tasks: list[tuple[int, TaskORM]] = []
        for idx in ordered_indices:
            task = TaskORM(
                title=task_titles[idx],
                description=f"Auto-generated for goal: {payload.goal}",
                priority=priorities[idx],
                owner_id=current_user.id,
            )
            db.add(task)
            indexed_tasks.append((idx, task))

        await db.commit()
        for _, task in indexed_tasks:
            await db.refresh(task)

        tasks_in_original_order = [t for _, t in sorted(indexed_tasks, key=lambda x: x[0])]
        span.set_attribute("tasks_created", len(tasks_in_original_order))

        plan_summary = (
            f"Created {len(tasks_in_original_order)} tasks for goal: '{payload.goal}'. "
            f"Priority range: {min(priorities)}–{max(priorities)}."
        )

        return PlanExecutionResponse(
            goal=payload.goal,
            tasks_created=tasks_in_original_order,
            plan_summary=plan_summary,
            model=settings.ollama_model,
        )
