import uuid

from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import relationship

from app.database import Base


class TaskORM(Base):
    __tablename__ = "tasks"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(String(1000), nullable=True)
    completed = Column(Boolean, default=False, index=True, nullable=False)
    priority = Column(Integer, default=1, nullable=False)
    owner_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    owner = relationship("UserORM", back_populates="tasks", lazy="noload")
    jobs = relationship("JobORM", back_populates="task", lazy="noload")
