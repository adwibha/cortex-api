import enum
import uuid

from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Enum, Uuid, func
from sqlalchemy.orm import relationship

from app.database import Base


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class JobType(str, enum.Enum):
    categorize = "categorize"
    embed = "embed"
    reindex = "reindex"


class JobORM(Base):
    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True, index=True)
    task_id = Column(Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    type = Column(Enum(JobType), nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.pending, nullable=False, index=True)
    result = Column(JSON, nullable=True)
    error = Column(String(1000), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    finished_at = Column(DateTime, nullable=True)

    task = relationship("TaskORM", back_populates="jobs", lazy="noload")
