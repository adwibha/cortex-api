from pydantic import BaseModel, ConfigDict, Field, EmailStr
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID


# ── Task schemas ─────────────────────────────────────────────────────────────

class TaskBase(BaseModel):
    model_config = ConfigDict(strict=True)
    title: str = Field(..., min_length=1, max_length=255, examples=["Buy groceries"])
    description: Optional[str] = Field(None, max_length=1000, examples=["Milk, eggs, bread"])
    completed: bool = Field(False, examples=[False])
    priority: int = Field(default=1, ge=0, le=5, examples=[3])


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    completed: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0, le=5)


class Task(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    created_at: datetime = Field(..., examples=["2024-01-15T10:30:00"])
    updated_at: datetime = Field(..., examples=["2024-01-15T10:30:00"])


class TaskListResponse(BaseModel):
    items: List[Task]
    total: int = Field(..., examples=[42])
    limit: int = Field(..., examples=[10])
    offset: int = Field(..., examples=[0])


# ── Auth schemas ──────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str
    api_key: Optional[str] = None
    created_at: datetime


# ── Job schemas ────────────────────────────────────────────────────────────────

class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: Optional[UUID]
    type: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


# ── AI schemas ────────────────────────────────────────────────────────────────

class NLSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, examples=["high priority tasks from this week"])


class NLSearchResponse(BaseModel):
    query: str
    filters: dict
    items: List[Task]
    total: int


class SummarizeResponse(BaseModel):
    task_id: UUID
    summary: str
    model: str


class PrioritizeResponse(BaseModel):
    task_id: UUID
    suggested_priority: int
    reasoning: str
    model: str


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(10, ge=1, le=50)


class SemanticSearchResponse(BaseModel):
    query: str
    items: List[Task]
    total: int


# ── Agent schemas ─────────────────────────────────────────────────────────────

class PlanExecutionRequest(BaseModel):
    goal: str = Field(..., min_length=5, max_length=1000, examples=["Prepare backend release for Friday"])


class PlanExecutionResponse(BaseModel):
    goal: str
    tasks_created: List[Task]
    plan_summary: str
    model: str


# ── Audit schemas ─────────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[UUID]
    action: str
    resource_type: str
    resource_id: Optional[str]
    payload: Optional[Any]
    ip: Optional[str]
    request_id: Optional[str]
    timestamp: datetime


class AuditLogListResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    limit: int
    offset: int


# ── Error schemas ─────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str = Field(..., examples=["VALIDATION_ERROR"])
    message: str = Field(..., examples=["Invalid input provided"])
    details: Optional[dict] = Field(None)


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
