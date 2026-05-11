from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.events.bus import publish, EventType
from app.models.task import TaskORM
from app.models.user import UserORM
from app.schemas import Task, TaskCreate, TaskUpdate, TaskListResponse

router = APIRouter(tags=["tasks"])


def _not_found(task_id: UUID, request_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": {"code": "TASK_NOT_FOUND", "message": f"Task {task_id} not found", "details": None},
            "request_id": request_id,
        },
    )


def _req_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    completed: Optional[bool] = None,
):
    query = select(TaskORM).where(TaskORM.owner_id == current_user.id)
    if completed is not None:
        query = query.where(TaskORM.completed == completed)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    result = await db.execute(
        query.order_by(TaskORM.created_at.desc()).limit(limit).offset(offset)
    )
    items = result.scalars().all()
    return TaskListResponse(items=list(items), total=total, limit=limit, offset=offset)


@router.get("/tasks/{task_id}", response_model=Task)
async def get_task(
    task_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    result = await db.execute(
        select(TaskORM).where(TaskORM.id == task_id, TaskORM.owner_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise _not_found(task_id, _req_id(request))
    return task


@router.post("/tasks", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    task = TaskORM(
        title=payload.title,
        description=payload.description,
        completed=payload.completed,
        priority=payload.priority,
        owner_id=current_user.id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    await publish(EventType.TASK_CREATED, {
        "task_id": str(task.id),
        "user_id": str(current_user.id),
        "title": task.title,
        "request_id": _req_id(request),
    })

    return task


@router.patch("/tasks/{task_id}", response_model=Task)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    result = await db.execute(
        select(TaskORM).where(TaskORM.id == task_id, TaskORM.owner_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise _not_found(task_id, _req_id(request))

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.completed is not None:
        task.completed = payload.completed
    if payload.priority is not None:
        task.priority = payload.priority

    task.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(task)

    event = EventType.TASK_COMPLETED if task.completed else EventType.TASK_UPDATED
    await publish(event, {
        "task_id": str(task.id),
        "user_id": str(current_user.id),
        "request_id": _req_id(request),
    })

    return task


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    result = await db.execute(
        select(TaskORM).where(TaskORM.id == task_id, TaskORM.owner_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise _not_found(task_id, _req_id(request))

    await db.delete(task)
    await db.commit()

    await publish(EventType.TASK_DELETED, {
        "task_id": str(task_id),
        "user_id": str(current_user.id),
        "request_id": _req_id(request),
    })
