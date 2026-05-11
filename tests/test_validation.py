"""
Validation tests — Pydantic schema enforcement on task endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.fixture
async def auth_headers(async_client: AsyncClient) -> dict:
    await async_client.post(
        "/api/v1/auth/register",
        json={"email": "val@example.com", "password": "testpass123"},
    )
    resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "val@example.com", "password": "testpass123"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


class TestValidation:
    async def test_missing_title(self, async_client: AsyncClient, auth_headers):
        response = await async_client.post(
            "/api/v1/tasks", json={"description": "No title"}, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_empty_title(self, async_client: AsyncClient, auth_headers):
        response = await async_client.post(
            "/api/v1/tasks", json={"title": ""}, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_title_too_long(self, async_client: AsyncClient, auth_headers):
        response = await async_client.post(
            "/api/v1/tasks", json={"title": "x" * 256}, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_priority_below_range(self, async_client: AsyncClient, auth_headers):
        response = await async_client.post(
            "/api/v1/tasks", json={"title": "Test", "priority": -1}, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_priority_above_range(self, async_client: AsyncClient, auth_headers):
        response = await async_client.post(
            "/api/v1/tasks", json={"title": "Test", "priority": 6}, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_priority_valid_range(self, async_client: AsyncClient, auth_headers):
        for priority in range(0, 6):
            response = await async_client.post(
                "/api/v1/tasks", json={"title": "Test", "priority": priority}, headers=auth_headers
            )
            assert response.status_code == 201
            assert response.json()["priority"] == priority

    async def test_completed_type_validation(self, async_client: AsyncClient, auth_headers):
        response = await async_client.post(
            "/api/v1/tasks", json={"title": "Test", "completed": "yes"}, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_description_too_long(self, async_client: AsyncClient, auth_headers):
        response = await async_client.post(
            "/api/v1/tasks", json={"title": "Test", "description": "x" * 1001}, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_valid_minimal_task(self, async_client: AsyncClient, auth_headers):
        response = await async_client.post(
            "/api/v1/tasks", json={"title": "Minimal"}, headers=auth_headers
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Minimal"
        assert data["description"] is None
        assert data["completed"] is False
        assert data["priority"] == 1

    async def test_pagination_limit_validation(self, async_client: AsyncClient, auth_headers):
        response = await async_client.get("/api/v1/tasks?limit=0", headers=auth_headers)
        assert response.status_code == 422

        response = await async_client.get("/api/v1/tasks?limit=101", headers=auth_headers)
        assert response.status_code == 422

    async def test_pagination_offset_validation(self, async_client: AsyncClient, auth_headers):
        response = await async_client.get("/api/v1/tasks?offset=-1", headers=auth_headers)
        assert response.status_code == 422
