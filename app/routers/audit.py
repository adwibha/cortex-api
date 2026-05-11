from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.audit import AuditLogORM
from app.models.user import UserORM, UserRole
from app.schemas import AuditLogListResponse

router = APIRouter(tags=["audit"])


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    db: AsyncSession = Depends(get_db),
    _admin: UserORM = Depends(require_role(UserRole.admin)),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: Optional[UUID] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
):
    query = select(AuditLogORM)
    if user_id is not None:
        query = query.where(AuditLogORM.user_id == user_id)
    if action:
        query = query.where(AuditLogORM.action == action)
    if resource_type:
        query = query.where(AuditLogORM.resource_type == resource_type)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    result = await db.execute(
        query.order_by(AuditLogORM.timestamp.desc()).limit(limit).offset(offset)
    )
    items = result.scalars().all()

    return AuditLogListResponse(items=list(items), total=total, limit=limit, offset=offset)
