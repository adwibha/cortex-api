"""
Async Ollama HTTP client.

Single place for all LLM calls so ai.py and agents.py
share the same timeout, tracing, and error handling.
"""
import json
import logging
from typing import AsyncGenerator, Optional

import httpx
from fastapi import HTTPException, status
from opentelemetry import trace

from app.config import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_TIMEOUT = httpx.Timeout(120.0)
_HEALTH_TIMEOUT = httpx.Timeout(5.0)


async def generate(prompt: str, model: Optional[str] = None) -> str:
    """Call Ollama /api/generate, return the full response string."""
    used_model = model or settings.ollama_model
    with tracer.start_as_current_span("ollama.generate") as span:
        span.set_attribute("ollama.model", used_model)
        span.set_attribute("ollama.prompt_length", len(prompt))
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{settings.ollama_url}/api/generate",
                    json={"model": used_model, "prompt": prompt, "stream": False},
                )
                resp.raise_for_status()
                return resp.json().get("response", "")
        except httpx.HTTPError as exc:
            logger.error("Ollama generate failed: %s", exc)
            raise _unavailable()


async def embed(text: str) -> list[float]:
    """Generate an embedding vector via Ollama /api/embeddings."""
    with tracer.start_as_current_span("ollama.embed") as span:
        span.set_attribute("ollama.model", settings.ollama_embed_model)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{settings.ollama_url}/api/embeddings",
                    json={"model": settings.ollama_embed_model, "prompt": text},
                )
                resp.raise_for_status()
                return resp.json().get("embedding", [])
        except httpx.HTTPError as exc:
            logger.error("Ollama embed failed: %s", exc)
            raise _unavailable()


async def stream_tokens(prompt: str) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted token chunks from Ollama's streaming API."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_url}/api/generate",
            json={"model": settings.ollama_model, "prompt": prompt, "stream": True},
        ) as response:
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if chunk.get("done"):
                        yield "data: [DONE]\n\n"
                        return
                except json.JSONDecodeError:
                    continue


async def is_available() -> bool:
    """Return True if Ollama is reachable (used by /health/deep)."""
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": {"code": "AI_UNAVAILABLE", "message": "AI service is unavailable"}, "request_id": ""},
    )


def extract_json_object(text: str) -> Optional[dict]:
    """Extract the first JSON object from a string. Returns None on failure."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def extract_json_array(text: str) -> Optional[list]:
    """Extract the first JSON array from a string. Returns None on failure."""
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
    return None
