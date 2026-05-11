# cortex-api — API Reference

**Base URL:** `http://localhost:8000`  
**OpenAPI UI:** `http://localhost:8000/docs`  
**Version:** 2.0.0

---

## Authentication

All endpoints except `/health`, `/health/deep`, `/metrics`, `/`, and the `/auth/*` registration/login routes require authentication.

### Bearer JWT (recommended)

```
Authorization: Bearer <access_token>
```

### API Key

```
X-API-Key: <api_key>
```

Obtain your API key from `GET /api/v1/auth/me` after registering.

---

## Common Headers

| Header | Description |
|--------|-------------|
| `X-Request-ID` | Optional. Pass your own UUID for tracing. Returned on every response. |
| `Idempotency-Key` | Optional on POST endpoints. Prevents duplicate resource creation on retries. Cached 24h. |
| `Content-Type` | `application/json` for all request bodies. |

---

## Standard Error Shape

Every error response follows this structure:

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task 42 not found",
    "details": null
  },
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `error.code` | string | Machine-readable error code |
| `error.message` | string | Human-readable description |
| `error.details` | object \| null | Field-level validation errors (VALIDATION_ERROR only) |
| `request_id` | string | UUID for log correlation |

### Error Codes

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `VALIDATION_ERROR` | 400 | Pydantic schema violation — `details.errors` contains field list |
| `UNAUTHORIZED` | 401 | Missing or invalid Bearer token / API key |
| `FORBIDDEN` | 403 | Valid token but insufficient role |
| `TASK_NOT_FOUND` | 404 | Task does not exist or belongs to another user |
| `JOB_NOT_FOUND` | 404 | Job ID does not exist |
| `EMAIL_TAKEN` | 409 | Email already registered |
| `RATE_LIMIT_EXCEEDED` | 429 | Exceeded 60 req/min — check `Retry-After` header |
| `AI_UNAVAILABLE` | 503 | Ollama service unreachable |
| `HTTP_ERROR` | varies | Catch-all for unexpected HTTP errors |

---

## Auth

### Register

```
POST /api/v1/auth/register
```

**Request body:**

```json
{
  "email": "you@example.com",
  "password": "strongpass123"
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `email` | string | Valid email, unique |
| `password` | string | 8–128 characters |

**201 Created:**

```json
{
  "id": 1,
  "email": "you@example.com",
  "role": "user",
  "api_key": "aBcDeFgH...",
  "created_at": "2026-05-11T12:00:00"
}
```

**Errors:** `400 VALIDATION_ERROR`, `409 EMAIL_TAKEN`

---

### Login

```
POST /api/v1/auth/login
```

**Request body:**

```json
{
  "email": "you@example.com",
  "password": "strongpass123"
}
```

**200 OK:**

```json
{
  "access_token": "eyJhbGci...",
  "refresh_token": "eyJhbGci...",
  "token_type": "bearer"
}
```

Access token expires in **30 minutes**. Refresh token expires in **7 days**.

**Errors:** `401 INVALID_CREDENTIALS`

---

### Refresh Token

```
POST /api/v1/auth/refresh
```

**Request body:**

```json
{
  "refresh_token": "eyJhbGci..."
}
```

**200 OK:**

```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer"
}
```

**Errors:** `401 INVALID_TOKEN`, `401 USER_NOT_FOUND`

---

### Current User

```
GET /api/v1/auth/me
```

**200 OK:**

```json
{
  "id": 1,
  "email": "you@example.com",
  "role": "user",
  "api_key": "aBcDeFgH...",
  "created_at": "2026-05-11T12:00:00"
}
```

**Errors:** `401 UNAUTHORIZED`

---

## Tasks

All task endpoints require authentication. Tasks are scoped to the authenticated user — you cannot read or modify another user's tasks.

### Task Object

```json
{
  "id": 1,
  "title": "Fix the login bug",
  "description": "Users get 500 on /auth/login after 3 attempts",
  "completed": false,
  "priority": 4,
  "owner_id": 1,
  "created_at": "2026-05-11T12:00:00",
  "updated_at": "2026-05-11T12:00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Auto-assigned |
| `title` | string | 1–255 characters |
| `description` | string \| null | Max 1000 characters |
| `completed` | bool | Default `false` |
| `priority` | int | 0 (lowest) – 5 (highest), default 1 |
| `owner_id` | int | ID of the owning user |
| `created_at` | datetime | ISO 8601 UTC |
| `updated_at` | datetime | ISO 8601 UTC |

---

### List Tasks

```
GET /api/v1/tasks
```

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 10 | 1–100 |
| `offset` | int | 0 | Pagination offset |
| `completed` | bool | — | Filter by completion status |

**200 OK:**

```json
{
  "items": [ { ...Task } ],
  "total": 42,
  "limit": 10,
  "offset": 0
}
```

**cURL:**
```bash
curl "http://localhost:8000/api/v1/tasks?limit=5&completed=false" \
  -H "Authorization: Bearer <token>"
```

**Python:**
```python
import requests

resp = requests.get(
    "http://localhost:8000/api/v1/tasks",
    headers={"Authorization": f"Bearer {token}"},
    params={"limit": 5, "completed": False},
)
data = resp.json()
print(data["total"], "total tasks")
```

**Errors:** `401`, `422 VALIDATION_ERROR` (invalid query params)

---

### Get Task

```
GET /api/v1/tasks/{task_id}
```

**200 OK:** Task object  
**Errors:** `401`, `404 TASK_NOT_FOUND`

---

### Create Task

```
POST /api/v1/tasks
```

Supports `Idempotency-Key` header.

**Request body:**

```json
{
  "title": "Write integration tests",
  "description": "Cover auth and task CRUD endpoints",
  "priority": 3,
  "completed": false
}
```

| Field | Required | Constraints |
|-------|----------|-------------|
| `title` | yes | 1–255 chars |
| `description` | no | max 1000 chars |
| `priority` | no | 0–5, default 1 |
| `completed` | no | bool, default false |

**201 Created:** Task object  
**Headers:** `X-Request-ID`

**cURL:**
```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer <token>" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"title": "Write integration tests", "priority": 3}'
```

**Errors:** `400 VALIDATION_ERROR`, `401`

---

### Update Task

```
PATCH /api/v1/tasks/{task_id}
```

All fields are optional. Only provided fields are updated.

**Request body:**

```json
{
  "completed": true,
  "priority": 5
}
```

**200 OK:** Updated task object  
**Errors:** `400 VALIDATION_ERROR`, `401`, `404 TASK_NOT_FOUND`

---

### Delete Task

```
DELETE /api/v1/tasks/{task_id}
```

**204 No Content**  
**Errors:** `401`, `404 TASK_NOT_FOUND`

---

## AI Endpoints

Backed by [Ollama](https://ollama.com) running locally. All calls use `llama3.2:1b` for text generation and `nomic-embed-text` for embeddings. If Ollama is unavailable, AI endpoints return `503 AI_UNAVAILABLE`.

### Natural Language Search

```
POST /api/v1/tasks/search/natural-language
```

Converts a plain-English query into SQL filters and returns matching tasks.

**Request body:**

```json
{
  "query": "high priority unfinished backend tasks"
}
```

**200 OK:**

```json
{
  "query": "high priority unfinished backend tasks",
  "filters": { "completed": false, "priority_gte": 4 },
  "items": [ { ...Task } ],
  "total": 3
}
```

**cURL:**
```bash
curl -X POST http://localhost:8000/api/v1/tasks/search/natural-language \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "high priority unfinished tasks"}'
```

---

### Summarize Task

```
POST /api/v1/tasks/{task_id}/summarize
```

Generates a 1–2 sentence summary of the task.

**200 OK:**

```json
{
  "task_id": 1,
  "summary": "Fix login endpoint that returns 500 after three failed attempts.",
  "model": "llama3.2:1b"
}
```

**Errors:** `401`, `404 TASK_NOT_FOUND`, `503 AI_UNAVAILABLE`

---

### Prioritize Task

```
POST /api/v1/tasks/{task_id}/prioritize
```

Suggests a priority score (0–5) with reasoning.

**200 OK:**

```json
{
  "task_id": 1,
  "suggested_priority": 5,
  "reasoning": "Login failures block all users from the platform.",
  "model": "llama3.2:1b"
}
```

**Errors:** `401`, `404 TASK_NOT_FOUND`, `503 AI_UNAVAILABLE`

---

### Stream Task Analysis

```
GET /api/v1/tasks/{task_id}/ai-stream
```

Streams a detailed task analysis token by token via Server-Sent Events.

**Response:** `text/event-stream`

```
data: {"token": "This"}
data: {"token": " task"}
data: {"token": " requires"}
...
data: [DONE]
```

**cURL:**
```bash
curl -N "http://localhost:8000/api/v1/tasks/1/ai-stream" \
  -H "Authorization: Bearer <token>"
```

**JavaScript:**
```javascript
const evtSource = new EventSource(
  "/api/v1/tasks/1/ai-stream",
  { headers: { Authorization: `Bearer ${token}` } }
);
evtSource.onmessage = (e) => {
  if (e.data === "[DONE]") return evtSource.close();
  const { token } = JSON.parse(e.data);
  process.stdout.write(token);
};
```

---

### Semantic Search

```
POST /api/v1/tasks/semantic-search
```

Finds tasks by meaning using pgvector cosine similarity. Falls back to keyword search if embeddings are unavailable.

**Request body:**

```json
{
  "query": "infrastructure reliability improvements",
  "limit": 5
}
```

| Field | Type | Constraints | Default |
|-------|------|-------------|---------|
| `query` | string | 1–500 chars | required |
| `limit` | int | 1–50 | 10 |

**200 OK:**

```json
{
  "query": "infrastructure reliability improvements",
  "items": [ { ...Task } ],
  "total": 3
}
```

---

### Reindex Embeddings

```
POST /api/v1/embeddings/reindex
```

Enqueues a background job to regenerate embeddings for all of the current user's tasks.

**202 Accepted:**

```json
{
  "job_id": "abc123",
  "status": "queued",
  "message": "Embedding reindex job enqueued"
}
```

---

## Agent Orchestration

### Plan Execution

```
POST /api/v1/agents/plan-execution
```

Runs a 3-stage multi-agent pipeline: **Planner → Prioritizer → Scheduler → Persist**.

Supports `Idempotency-Key` to prevent duplicate plan creation on retries.

**Request body:**

```json
{
  "goal": "Prepare backend API for production release by Friday"
}
```

| Field | Constraints |
|-------|-------------|
| `goal` | 5–1000 characters |

**201 Created:**

```json
{
  "goal": "Prepare backend API for production release by Friday",
  "tasks_created": [
    { "id": 10, "title": "Add rate limiting", "priority": 5, ... },
    { "id": 11, "title": "Write load tests", "priority": 4, ... },
    { "id": 12, "title": "Set up monitoring alerts", "priority": 4, ... }
  ],
  "plan_summary": "Created 3 tasks for goal: '...'. Priority range: 4–5.",
  "model": "llama3.2:1b"
}
```

**cURL:**
```bash
curl -X POST http://localhost:8000/api/v1/agents/plan-execution \
  -H "Authorization: Bearer <token>" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Prepare backend API for production release by Friday"}'
```

**Python:**
```python
import requests, uuid

resp = requests.post(
    "http://localhost:8000/api/v1/agents/plan-execution",
    headers={
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": str(uuid.uuid4()),
        "Content-Type": "application/json",
    },
    json={"goal": "Prepare backend API for production release by Friday"},
)
plan = resp.json()
print(f"Created {len(plan['tasks_created'])} tasks")
```

**Errors:** `400 VALIDATION_ERROR`, `401`, `503 AI_UNAVAILABLE`

---

## Background Jobs

### Categorize Task

```
POST /api/v1/tasks/{task_id}/categorize
```

Enqueues an async job to categorize the task using the LLM.

**202 Accepted:**

```json
{
  "job_id": "a1b2c3d4-...",
  "status": "queued",
  "task_id": 1
}
```

---

### Get Job Status

```
GET /api/v1/jobs/{job_id}
```

**200 OK:**

```json
{
  "id": "a1b2c3d4-...",
  "task_id": 1,
  "type": "categorize",
  "status": "done",
  "result": {
    "category": "work",
    "confidence": 0.91
  },
  "error": null,
  "created_at": "2026-05-11T12:00:00",
  "finished_at": "2026-05-11T12:00:08"
}
```

| `status` | Meaning |
|----------|---------|
| `pending` | Queued, not yet picked up by worker |
| `running` | Currently being processed |
| `done` | Completed successfully — check `result` |
| `failed` | Error occurred — check `error` |

**Errors:** `401`, `404 JOB_NOT_FOUND`

---

## Audit Logs

### List Audit Logs

```
GET /api/v1/audit-logs
```

**Requires `admin` role.**

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | 1–200, default 50 |
| `offset` | int | Pagination offset |
| `user_id` | int | Filter by user |
| `action` | string | Filter by action (e.g. `task.created`) |
| `resource_type` | string | Filter by resource (e.g. `task`) |

**200 OK:**

```json
{
  "items": [
    {
      "id": 1,
      "user_id": 1,
      "action": "task.created",
      "resource_type": "task",
      "resource_id": "5",
      "payload": { "task_id": 5, "title": "Fix bug" },
      "ip": null,
      "request_id": "550e8400-...",
      "timestamp": "2026-05-11T12:00:00"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### Audit Event Types

| Action | Triggered by |
|--------|-------------|
| `task.created` | `POST /tasks` |
| `task.completed` | `PATCH /tasks/{id}` when `completed` set to true |
| `task.deleted` | `DELETE /tasks/{id}` |
| `job.finished` | ARQ worker on job completion |
| `ai.summary_generated` | `POST /tasks/{id}/summarize` |

**Errors:** `401`, `403 FORBIDDEN`

---

## Health & Observability

### Basic Health

```
GET /health
```

**200 OK:**
```json
{ "status": "ok", "version": "2.0.0" }
```

---

### Deep Health

```
GET /health/deep
```

Checks connectivity to Postgres, Redis, and Ollama with latency.

**200 OK (healthy):**
```json
{
  "status": "ok",
  "postgres": "ok 4ms",
  "redis": "ok 1ms",
  "ollama": "ok 22ms"
}
```

**200 OK (degraded):**
```json
{
  "status": "degraded",
  "postgres": "ok 4ms",
  "redis": "ok 1ms",
  "ollama": "error: Connection refused"
}
```

---

### Prometheus Metrics

```
GET /metrics
```

Returns Prometheus text format. Metrics include request counts, latency histograms, and in-progress request gauges per endpoint.

---

## Rate Limiting

All endpoints are subject to a sliding window limit of **60 requests per minute per IP**.

When exceeded:

**429 Too Many Requests:**
```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded. Max 60 requests/minute.",
    "details": { "limit": 60, "retry_after": 34 }
  },
  "request_id": "..."
}
```

Response header: `Retry-After: 34`

---

## Idempotency

POST endpoints that create resources accept an `Idempotency-Key` header:

```
Idempotency-Key: <uuid>
```

- **First call:** request is processed normally; response is cached in Redis for 24 hours.
- **Repeated call with same key:** cached response is returned immediately with header `X-Idempotency-Replayed: true`. No DB write occurs.

Applies to: `POST /tasks`, `POST /agents/plan-execution`.

---

## Pagination

List endpoints use offset-based pagination:

```
GET /api/v1/tasks?limit=10&offset=20
```

Response always includes `total` for building page navigation:

```json
{
  "items": [...],
  "total": 87,
  "limit": 10,
  "offset": 20
}
```

---

## Data Models

### User

| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Primary key |
| `email` | string | Unique |
| `role` | `user` \| `admin` | Default `user` |
| `api_key` | string | 64-char URL-safe token |
| `created_at` | datetime | UTC |

### Task

| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Primary key |
| `title` | string | 1–255 chars |
| `description` | string \| null | Max 1000 chars |
| `completed` | bool | Default false |
| `priority` | int | 0–5 |
| `owner_id` | int | FK → users.id |
| `created_at` | datetime | UTC |
| `updated_at` | datetime | UTC |

### Job

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | UUID |
| `task_id` | int \| null | FK → tasks.id |
| `type` | `categorize` \| `embed` \| `reindex` | |
| `status` | `pending` \| `running` \| `done` \| `failed` | |
| `result` | JSON \| null | Present when done |
| `error` | string \| null | Present when failed |
| `created_at` | datetime | UTC |
| `finished_at` | datetime \| null | UTC |

### AuditLog

| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Primary key |
| `user_id` | int \| null | FK → users.id |
| `action` | string | e.g. `task.created` |
| `resource_type` | string | e.g. `task` |
| `resource_id` | string \| null | |
| `payload` | JSON \| null | Event context |
| `ip` | string \| null | Client IP |
| `request_id` | string \| null | Correlation ID |
| `timestamp` | datetime | UTC |
