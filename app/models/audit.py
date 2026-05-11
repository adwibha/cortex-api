import uuid

from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Uuid, func
from sqlalchemy.orm import relationship

from app.database import Base


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False, index=True)
    resource_id = Column(String(64), nullable=True)
    payload = Column(JSON, nullable=True)
    ip = Column(String(64), nullable=True)
    request_id = Column(String(64), nullable=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    user = relationship("UserORM", back_populates="audit_logs", lazy="noload")
