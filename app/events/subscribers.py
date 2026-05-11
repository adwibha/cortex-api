"""
Event bus subscribers.

Registered at app startup. Each subscriber handles one event type.
Audit log writes happen here — zero route handler changes needed.
"""
import logging
from typing import Optional

from app.database import AsyncSessionLocal
from app.events.bus import subscribe, EventType
from app.models.audit import AuditLogORM

logger = logging.getLogger(__name__)


@subscribe(EventType.TASK_CREATED)
async def on_task_created(payload: dict) -> None:
    await _write_audit(
        user_id=payload.get("user_id"),
        action="task.created",
        resource_type="task",
        resource_id=str(payload.get("task_id", "")),
        payload=payload,
        request_id=payload.get("request_id"),
    )


@subscribe(EventType.TASK_UPDATED)
async def on_task_updated(payload: dict) -> None:
    await _write_audit(
        user_id=payload.get("user_id"),
        action="task.updated",
        resource_type="task",
        resource_id=str(payload.get("task_id", "")),
        payload=payload,
        request_id=payload.get("request_id"),
    )


@subscribe(EventType.TASK_COMPLETED)
async def on_task_completed(payload: dict) -> None:
    await _write_audit(
        user_id=payload.get("user_id"),
        action="task.completed",
        resource_type="task",
        resource_id=str(payload.get("task_id", "")),
        payload=payload,
        request_id=payload.get("request_id"),
    )


@subscribe(EventType.TASK_DELETED)
async def on_task_deleted(payload: dict) -> None:
    await _write_audit(
        user_id=payload.get("user_id"),
        action="task.deleted",
        resource_type="task",
        resource_id=str(payload.get("task_id", "")),
        payload=payload,
        request_id=payload.get("request_id"),
    )


@subscribe(EventType.JOB_FINISHED)
async def on_job_finished(payload: dict) -> None:
    await _write_audit(
        user_id=payload.get("user_id"),
        action="job.finished",
        resource_type="job",
        resource_id=str(payload.get("job_id", "")),
        payload=payload,
    )


@subscribe(EventType.AI_SUMMARY_GENERATED)
async def on_ai_summary(payload: dict) -> None:
    await _write_audit(
        user_id=payload.get("user_id"),
        action="ai.summary_generated",
        resource_type="task",
        resource_id=str(payload.get("task_id", "")),
        payload=payload,
    )


async def _write_audit(
    user_id,
    action: str,
    resource_type: str,
    resource_id: str = "",
    payload: Optional[dict] = None,
    request_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            log = AuditLogORM(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                payload=payload,
                ip=ip,
                request_id=request_id,
            )
            db.add(log)
            await db.commit()
    except Exception as exc:
        logger.error("Audit write failed: %s", exc)
