# Architecture

## Overview

Task API is a stateless REST API built with FastAPI and SQLAlchemy. It implements production patterns for error handling, validation, pagination, and request correlation.

## Design Principles

### 1. Stateless
Every request contains all information needed to process it. No session storage. Each request is independent and can be handled by any server instance.

### 2. Resource-Oriented
Tasks are resources accessed via URLs:
- `GET /api/v1/tasks` - Collection of tasks
- `GET /api/v1/tasks/{id}` - Single task
- `POST /api/v1/tasks` - Create new task
- `PATCH /api/v1/tasks/{id}` - Update existing task
- `DELETE /api/v1/tasks/{id}` - Remove task

### 3. HTTP Semantics
Correct status codes convey intent:
- `200 OK` - Request succeeded, body contains result
- `201 Created` - Resource created successfully
- `204 No Content` - Request succeeded, no body (DELETE operations)
- `400 Bad Request` - Client error (invalid input, missing fields)
- `404 Not Found` - Resource doesn't exist
- `5xx Server Error` - Server error (should rarely happen)

## Request Flow

```
[Client Request]
      ↓
[Correlation ID Middleware] ← Adds X-Request-ID header
      ↓
[FastAPI Route Matching] ← Determines which endpoint handles request
      ↓
[Pydantic Validation] ← Validates request body against schema
      ↓ (Valid)
[Route Handler] ← Business logic, CRUD operations
      ↓
[Database Query] ← SQLAlchemy ORM queries or mutations
      ↓
[Response Serialization] ← Convert ORM objects to JSON
      ↓
[Add Headers] ← Include X-Request-ID header in response
      ↓
[Client Response]

      ↓ (Invalid)
[ValidationError Handler] ← Catches Pydantic errors
      ↓
[Error Response] ← 400 Bad Request with field-level errors
      ↓
[Client Response]
```

## OpenAPI & Documentation

FastAPI auto-generates OpenAPI schema by introspecting:

1. **Route paths and methods** - Defines available endpoints
2. **Type hints** - Defines request/response models
3. **Pydantic models** - Defines validation rules and examples
4. **Docstrings** - Describes what each endpoint does

Result: Interactive Swagger UI at `/docs` with live request testing.

**Key Files:**
- `app/schemas.py` - Pydantic models define schema
- `app/routers/tasks.py` - Route handlers define operations

## Error Handling

### Standard Error Format

All errors follow this structure:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": {}
  },
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Error Codes

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `VALIDATION_ERROR` | 400 | Invalid request data |
| `TASK_NOT_FOUND` | 404 | Task with given ID doesn't exist |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

### Error Examples

**Validation Error (Missing required field):**
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input provided",
    "details": {
      "errors": [
        {
          "field": "title",
          "message": "Field required",
          "type": "missing"
        }
      ]
    }
  },
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Not Found (No task with ID):**
```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task with id 999 not found",
    "details": null
  },
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## Validation

Pydantic validates all input automatically:

1. **Type validation** - Ensures field types match schema
2. **Range validation** - Ensures values within constraints (e.g., priority 0-5)
3. **Length validation** - Ensures strings within min/max length
4. **Custom validators** - Can add business logic validators

**Key File:** `app/schemas.py` - Defines all validation rules

Example:
```python
class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    priority: int = Field(default=1, ge=0, le=5)
```

This enforces:
- `title` required, 1-255 characters
- `priority` optional, defaults to 1, must be 0-5

Invalid requests return 400 with field-level errors explaining what's wrong.

## Pagination

List endpoints support limit/offset pagination:

**Query Parameters:**
- `limit` - Number of items to return (1-100, default 10)
- `offset` - Number of items to skip (default 0)
- `completed` - Optional filter (true/false)

**Response:**
```json
{
  "items": [...],      // Array of tasks
  "total": 42,         // Total count (not limited)
  "limit": 10,         // Requested limit
  "offset": 0          // Requested offset
}
```

**Pattern:**
```
Page 1: limit=10, offset=0   → items 0-9
Page 2: limit=10, offset=10  → items 10-19
Page 3: limit=10, offset=20  → items 20-29
```

Frontend can calculate total pages: `ceil(total / limit)`

## Request Correlation

Every request gets a unique UUID (`X-Request-ID`):

1. **Middleware** (`app/main.py`) generates UUID for each request
2. **Stored in request state** - Available to route handlers
3. **Included in error responses** - Client can reference error by ID
4. **Logged with request** - Server logs include request ID for tracing
5. **Returned in response headers** - Client sees same ID in response

**Benefits:**
- Track a single request through logs
- Link client issues to server logs
- Debug distributed tracing issues

**Example:**
```
Client Request with: X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
Server Response includes: X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
Server Logs include: [550e8400-e29b-41d4-a716-446655440000] POST /api/v1/tasks → 201
```

## Database Design

### SQLAlchemy ORM

Uses SQLAlchemy for database abstraction:

**Benefits:**
- Database-agnostic SQL generation
- Type-safe queries
- Connection pooling
- Transaction management

**Task Table:**
```
id          INTEGER PRIMARY KEY  (auto-increment)
title       VARCHAR(255) NOT NULL
description VARCHAR(1000)
completed   BOOLEAN DEFAULT FALSE
priority    INTEGER DEFAULT 1
created_at  DATETIME DEFAULT now()
updated_at  DATETIME DEFAULT now()
```

**Key File:** `app/database.py` - ORM model and CRUD operations

### CRUD Operations

| Operation | Function | Returns |
|-----------|----------|---------|
| Create | `create_task(db, ...)` | TaskORM instance |
| Read One | `get_task(db, id)` | TaskORM or None |
| Read Many | `list_tasks(db, ...)` | (items, total) tuple |
| Update | `update_task(db, id, ...)` | TaskORM or None |
| Delete | `delete_task(db, id)` | bool |

## Testing Strategy

### Unit Tests (`test_tasks.py`)

Test CRUD operations:
- Create, read, update, delete tasks
- Pagination (limit, offset)
- Filtering (completed status)
- Status codes (201, 204, 404)
- Correlation ID headers

### Validation Tests (`test_validation.py`)

Test Pydantic validation:
- Required fields
- String length constraints
- Integer range constraints
- Type validation
- Error response format

### Test Database

Tests use **in-memory SQLite** (`sqlite:///:memory:`) to:
- Run without file system I/O
- Isolate each test run
- Enable parallel test execution
- Keep tests fast

**Key Pattern:**
```python
@pytest.fixture(scope="function")
def db():
    # Fresh database for each test
    Base.metadata.create_all(bind=engine)
    yield db
    # Clean up after test
    Base.metadata.drop_all(bind=engine)
```

## Production Extensions

This API is designed to scale to production with:

### 1. Authentication
Replace in-memory correlation IDs with JWT tokens:
```python
from fastapi.security import HTTPBearer

security = HTTPBearer()

@router.post("/tasks")
async def create_task(task: TaskCreate, current_user = Depends(get_current_user)):
    # Only current_user can create tasks
```

### 2. Real Database
Switch from SQLite to PostgreSQL:
```python
DATABASE_URL = "postgresql://user:password@localhost/taskdb"
# Everything else stays the same
```

### 3. Rate Limiting
Add per-user rate limits:
```python
from slowapi import Limiter

limiter = Limiter(key_func=get_user_id)

@router.post("/tasks")
@limiter.limit("100/hour")
async def create_task(...):
    pass
```

### 4. Logging & Monitoring
Add structured logging and metrics:
```python
from pythonjsonlogger import jsonlogger

logger.info("task_created", extra={"task_id": task.id, "user_id": user_id})
```

### 5. Database Migrations
Use Alembic for schema versioning:
```bash
alembic init alembic
alembic revision --autogenerate -m "Initial schema"
alembic upgrade head
```

### 6. Async I/O
FastAPI already supports async - just mark handlers:
```python
@router.get("/tasks")
async def list_tasks(...):  # async allowed
    items, total = await db.execute(...)
```

## API Versioning

Current version is `v1` in URL path:
- `GET /api/v1/tasks`
- `POST /api/v1/tasks`

When breaking changes needed, create v2:
- `GET /api/v2/tasks` (new schema)
- `GET /api/v1/tasks` (maintained for backward compatibility)

## Security Considerations

### Input Validation
Pydantic validates all input - prevents:
- Invalid data types
- Out-of-range values
- Malformed requests

### CORS
Configured to allow all origins (development):
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
)
```

In production, restrict to your domains:
```python
allow_origins=["https://yourdomain.com", "https://app.yourdomain.com"]
```

### SQL Injection Prevention
SQLAlchemy ORM parameterizes all queries:
```python
db.query(TaskORM).filter(TaskORM.id == task_id)  # Safe - parameterized
# Not: f"SELECT * FROM tasks WHERE id = {task_id}"  # Vulnerable
```

## Deployment

### Development
```bash
python -m uvicorn app.main:app --reload
```

### Production
```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app
```

Or with Docker:
```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]
```

## Summary

Task API demonstrates production REST API patterns:
- Stateless architecture
- Proper HTTP semantics
- Comprehensive validation
- Consistent error handling
- Request correlation for debugging
- Pagination for large datasets
- Comprehensive test coverage
- OpenAPI documentation

These patterns form the foundation for scaling to a real production system.
