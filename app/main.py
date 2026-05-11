import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import ValidationError
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal, init_db
from app.events import subscribers  # noqa: F401 — registers all handlers via decorators
from app.events.bus import close as close_bus, get_redis, start_subscribers
from app.middleware.idempotency import IdempotencyMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers import agents, ai, audit, auth, jobs, tasks
from app.schemas import ErrorDetail, ErrorResponse

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _setup_telemetry() -> None:
    resource = Resource.create({"service.name": settings.app_name, "service.version": settings.app_version})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_telemetry()
    await init_db()
    await start_subscribers()
    logger.info("%s v%s started", settings.app_name, settings.app_version)
    yield
    await close_bus()
    logger.info("%s shutting down", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    description=(
        "**cortex-api** — AI workflow platform with task management, agent orchestration, "
        "semantic search, background jobs, and OpenTelemetry observability.\n\n"
        "Authenticate via **Bearer JWT** (obtain from `/auth/login`) "
        "or **X-API-Key** header (from `/auth/me`)."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    schema["components"]["securitySchemes"]["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

# ── Middleware (order matters — outermost runs first) ────────────────────────
app.add_middleware(
    CORSMiddleware,
    # Explicit allowlist instead of wildcard; configured via CORS_ALLOWED_ORIGINS env var
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "Idempotency-Key", "X-Request-ID"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(IdempotencyMiddleware)

# ── Prometheus instrumentation (no .expose() — we add a protected route below) ──
_instrumentator = Instrumentator()
_instrumentator.instrument(app)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")


# ── Correlation ID + Security headers middleware ─────────────────────────────
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    start = time.perf_counter()

    response = await call_next(request)

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Request-ID"] = request_id

    # Security headers on every response
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Prevent intermediary caches from storing sensitive API responses
    response.headers["Cache-Control"] = "no-store"

    logger.info(
        "%s %s -> %s (%.2fms) [%s]",
        request.method, request.url.path, response.status_code, duration_ms, request_id,
    )
    return response


# ── Exception handlers ────────────────────────────────────────────────────────
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    request_id = getattr(request.state, "request_id", str(uuid4()))
    errors = [
        {"field": ".".join(str(x) for x in e["loc"][1:]), "message": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=ErrorResponse(
            error=ErrorDetail(code="VALIDATION_ERROR", message="Invalid input provided", details={"errors": errors}),
            request_id=request_id,
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", str(uuid4()))
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        detail = exc.detail
        if not detail.get("request_id"):
            detail["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code="HTTP_ERROR",
                message=exc.detail if isinstance(exc.detail, str) else "An error occurred",
            ),
            request_id=request_id,
        ).model_dump(),
    )


# ── Health endpoints ──────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "version": settings.app_version}


@app.get("/health/deep", tags=["health"])
async def health_deep():
    results = {
        "postgres": await _check_postgres(),
        "redis": await _check_redis(),
        "ollama": await _check_ollama(),
    }
    overall = "ok" if all(v.startswith("ok") for v in results.values()) else "degraded"
    return {"status": overall, **results}


async def _check_postgres() -> str:
    try:
        t0 = time.perf_counter()
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return f"ok {round((time.perf_counter() - t0) * 1000)}ms"
    except Exception:
        # Sanitize: never expose raw exception messages (may contain connection strings)
        logger.exception("Postgres health check failed")
        return "error"


async def _check_redis() -> str:
    try:
        t0 = time.perf_counter()
        await get_redis().ping()
        return f"ok {round((time.perf_counter() - t0) * 1000)}ms"
    except Exception:
        logger.exception("Redis health check failed")
        return "error"


async def _check_ollama() -> str:
    try:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
            resp.raise_for_status()
        return f"ok {round((time.perf_counter() - t0) * 1000)}ms"
    except Exception:
        logger.exception("Ollama health check failed")
        return "error"


# ── Prometheus metrics (protected by optional bearer token) ──────────────────
@app.get("/metrics", tags=["observability"], include_in_schema=False)
async def metrics(request: Request):
    """Expose Prometheus metrics. Requires Authorization: Bearer <METRICS_TOKEN> if configured."""
    if settings.metrics_token:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header[7:] != settings.metrics_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "UNAUTHORIZED", "message": "Valid metrics token required"}, "request_id": ""},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", tags=["root"])
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


# ── FastAPI OTEL instrumentation (after app is fully configured) ─────────────
FastAPIInstrumentor.instrument_app(app)
