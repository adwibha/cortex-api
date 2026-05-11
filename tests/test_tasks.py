"""
Task CRUD tests.

All task endpoints now require authentication. Tests register a user and
obtain a JWT token before exercising the task API.
"""
import pytest
from httpx import AsyncClient


@pytest.fixture
async def auth_headers(async_client: AsyncClient) -> dict:
    """Register a test user and return Authorization headers."""
    await async_client.post(
        "/api/v1/auth/register",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestTaskCRUD:
    async def test_create_task(self, async_client: AsyncClient, auth_headers):
        response = await async_client.post(
            "/api/v1/tasks",
            json={"title": "Test task", "description": "Test description", "priority": 2},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test task"
        assert data["description"] == "Test description"
        assert data["priority"] == 2
        assert data["completed"] is False
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_get_task(self, async_client: AsyncClient, auth_headers):
        create = await async_client.post(
            "/api/v1/tasks", json={"title": "Get test", "priority": 1}, headers=auth_headers
        )
        task_id = create.json()["id"]

        response = await async_client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["id"] == task_id

    async def test_get_task_not_found(self, async_client: AsyncClient, auth_headers):
        nonexistent = "00000000-0000-0000-0000-000000000000"
        response = await async_client.get(f"/api/v1/tasks/{nonexistent}", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "TASK_NOT_FOUND"

    async def test_list_tasks(self, async_client: AsyncClient, auth_headers):
        await async_client.post("/api/v1/tasks", json={"title": "Task 1"}, headers=auth_headers)
        await async_client.post("/api/v1/tasks", json={"title": "Task 2"}, headers=auth_headers)

        response = await async_client.get("/api/v1/tasks", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 2

    async def test_list_tasks_pagination(self, async_client: AsyncClient, auth_headers):
        for i in range(15):
            await async_client.post("/api/v1/tasks", json={"title": f"Task {i}"}, headers=auth_headers)

        response = await async_client.get("/api/v1/tasks?limit=5&offset=0", headers=auth_headers)
        data = response.json()
        assert len(data["items"]) == 5
        assert data["limit"] == 5

    async def test_list_tasks_filter_completed(self, async_client: AsyncClient, auth_headers):
        await async_client.post("/api/v1/tasks", json={"title": "Done", "completed": True}, headers=auth_headers)
        await async_client.post("/api/v1/tasks", json={"title": "Pending", "completed": False}, headers=auth_headers)

        response = await async_client.get("/api/v1/tasks?completed=true", headers=auth_headers)
        data = response.json()
        assert all(item["completed"] is True for item in data["items"])

    async def test_update_task(self, async_client: AsyncClient, auth_headers):
        create = await async_client.post(
            "/api/v1/tasks", json={"title": "Original", "priority": 1}, headers=auth_headers
        )
        task_id = create.json()["id"]

        response = await async_client.patch(
            f"/api/v1/tasks/{task_id}",
            json={"title": "Updated", "priority": 5, "completed": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated"
        assert data["priority"] == 5
        assert data["completed"] is True

    async def test_update_task_partial(self, async_client: AsyncClient, auth_headers):
        create = await async_client.post(
            "/api/v1/tasks",
            json={"title": "Original", "description": "Desc", "priority": 1},
            headers=auth_headers,
        )
        task_id = create.json()["id"]

        response = await async_client.patch(
            f"/api/v1/tasks/{task_id}", json={"priority": 3}, headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Original"
        assert data["priority"] == 3

    async def test_delete_task(self, async_client: AsyncClient, auth_headers):
        create = await async_client.post(
            "/api/v1/tasks", json={"title": "To delete"}, headers=auth_headers
        )
        task_id = create.json()["id"]

        response = await async_client.delete(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        assert response.status_code == 204

        response = await async_client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        assert response.status_code == 404

    async def test_unauthenticated_request(self, async_client: AsyncClient):
        response = await async_client.get("/api/v1/tasks")
        assert response.status_code == 401

    async def test_correlation_id_header(self, async_client: AsyncClient, auth_headers):
        response = await async_client.get("/api/v1/tasks", headers=auth_headers)
        assert "x-request-id" in response.headers

    async def test_status_codes(self, async_client: AsyncClient, auth_headers):
        create = await async_client.post("/api/v1/tasks", json={"title": "Test"}, headers=auth_headers)
        assert create.status_code == 201

        task_id = create.json()["id"]
        delete = await async_client.delete(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        assert delete.status_code == 204

    async def test_task_isolation_between_users(self, async_client: AsyncClient, auth_headers):
        """Tasks must only be visible to their owner."""
        # Create task as user 1
        create = await async_client.post(
            "/api/v1/tasks", json={"title": "User1 task"}, headers=auth_headers
        )
        task_id = create.json()["id"]

        # Register user 2
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "user2@example.com", "password": "testpass123"},
        )
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "user2@example.com", "password": "testpass123"},
        )
        user2_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        response = await async_client.get(f"/api/v1/tasks/{task_id}", headers=user2_headers)
        assert response.status_code == 404
