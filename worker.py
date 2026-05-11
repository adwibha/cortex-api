"""
ARQ background worker.

Start with: python worker.py
Or via docker-compose as a separate service.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

import arq
import httpx
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.events.bus import publish, EventType
from app.models.job import JobORM, JobStatus, JobType
from app.models.task import TaskORM
from app.services.ollama import extract_json_object

logger = logging.getLogger(__name__)


async def process_job(ctx: dict, job_id: str, user_id: str) -> dict:
    """Process a queued job — currently handles: categorize, embed, reindex."""
    owner_id = UUID(user_id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(JobORM).where(JobORM.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            logger.warning("Job %s not found", job_id)
            return {}

        job.status = JobStatus.running
        await db.commit()

        try:
            if job.type == JobType.categorize and job.task_id:
                task_result = await db.execute(select(TaskORM).where(TaskORM.id == job.task_id))
                task = task_result.scalar_one_or_none()

                if task:
                    prompt = f"""Categorize this task into one of: [work, personal, health, finance, learning, other].

Title: {task.title}
Description: {task.description or ''}

Return ONLY a JSON object: {{"category": "<category>", "confidence": <0.0-1.0>}}

JSON:"""
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.post(
                            f"{settings.ollama_url}/api/generate",
                            json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
                        )
                        resp.raise_for_status()
                        raw = resp.json().get("response", "")

                    job.result = extract_json_object(raw) or {"category": "other", "confidence": 0.5}
                else:
                    job.result = {"error": "Task not found"}

            elif job.type == JobType.reindex:
                tasks_result = await db.execute(
                    select(TaskORM).where(TaskORM.owner_id == owner_id)
                )
                tasks = tasks_result.scalars().all()
                embedded = 0
                for task in tasks:
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            resp = await client.post(
                                f"{settings.ollama_url}/api/embeddings",
                                json={"model": settings.ollama_embed_model, "prompt": f"{task.title} {task.description or ''}"},
                            )
                            if resp.status_code == 200:
                                embedded += 1
                    except Exception:
                        pass
                job.result = {"tasks_processed": len(tasks), "embeddings_created": embedded}

            job.status = JobStatus.done
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()

            await publish(EventType.JOB_FINISHED, {"job_id": job_id, "type": job.type, "user_id": user_id})
            return job.result or {}

        except Exception as exc:
            logger.error("Job %s failed: %s", job_id, exc)
            job.status = JobStatus.failed
            job.error = str(exc)[:1000]
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
            raise


class WorkerSettings:
    functions = [process_job]
    redis_settings = arq.connections.RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 300


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    arq.run_worker(WorkerSettings)
