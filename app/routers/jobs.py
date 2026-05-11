import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import arq
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.job import JobORM, JobStatus, JobType
from app.models.task import TaskORM
from app.models.user import UserORM
from app.schemas import JobResponse

router = APIRouter(tags=["jobs"])
logger = logging.getLogger(__name__)


async def _enqueue_job(
    db: AsyncSession,
    task_id: Optional[UUID],
    job_type: JobType,
    user_id: UUID,
) -> JobORM:
    job = JobORM(
        id=str(uuid.uuid4()),
        task_id=task_id,
        type=job_type,
        status=JobStatus.pending,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    try:
        redis_settings = arq.connections.RedisSettings.from_dsn(settings.redis_url)
        pool = await arq.create_pool(redis_settings)
        await pool.enqueue_job("process_job", job.id, str(user_id))
        await pool.aclose()
    except Exception as exc:
        logger.error("Failed to enqueue job %s: %s — marking as failed", job.id, exc)
        job.status = JobStatus.failed
        job.error = f"Enqueue failed: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()

    return job


@router.post("/tasks/{task_id}/categorize", status_code=status.HTTP_202_ACCEPTED)
async def categorize_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Enqueue an AI categorization job for a task. Returns 202 with job_id for polling."""
    result = await db.execute(
        select(TaskORM).where(TaskORM.id == task_id, TaskORM.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "TASK_NOT_FOUND", "message": f"Task {task_id} not found"}, "request_id": ""},
        )

    job = await _enqueue_job(db, task_id=task_id, job_type=JobType.categorize, user_id=current_user.id)
    return {"job_id": job.id, "status": job.status, "task_id": str(task_id)}


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    """Poll job status. Returns status, result when done, or error if failed."""
    result = await db.execute(select(JobORM).where(JobORM.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "JOB_NOT_FOUND", "message": f"Job {job_id} not found"}, "request_id": ""},
        )

    # Ownership check: verify job belongs to a task owned by the current user
    if job.task_id is not None:
        task_result = await db.execute(
            select(TaskORM).where(TaskORM.id == job.task_id, TaskORM.owner_id == current_user.id)
        )
        if not task_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": {"code": "JOB_NOT_FOUND", "message": f"Job {job_id} not found"}, "request_id": ""},
            )

    return job
