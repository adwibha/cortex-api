import enum
import secrets
import uuid

from sqlalchemy import Column, String, DateTime, Enum, Uuid, func
from sqlalchemy.orm import relationship

from app.database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class UserORM(Base):
    __tablename__ = "users"

    # UUID PK prevents ID enumeration and hides resource count
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.user, nullable=False)
    api_key = Column(String(64), unique=True, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    tasks = relationship("TaskORM", back_populates="owner", lazy="noload")
    audit_logs = relationship("AuditLogORM", back_populates="user", lazy="noload")

    @staticmethod
    def generate_api_key() -> str:
        return secrets.token_urlsafe(48)
