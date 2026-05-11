"""Auth endpoint tests."""
import pytest
from httpx import AsyncClient


class TestAuth:
    async def test_register(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": "strongpass123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "new@example.com"
        assert data["role"] == "user"
        assert "api_key" in data

    async def test_register_duplicate_email(self, async_client: AsyncClient):
        payload = {"email": "dup@example.com", "password": "strongpass123"}
        await async_client.post("/api/v1/auth/register", json=payload)
        response = await async_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EMAIL_TAKEN"

    async def test_logout_revokes_refresh_token(self, async_client: AsyncClient):
        """After logout, the refresh token must no longer produce a new access token."""
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "logout@example.com", "password": "strongpass123"},
        )
        login_resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "logout@example.com", "password": "strongpass123"},
        )
        tokens = login_resp.json()

        # Logout should succeed
        logout_resp = await async_client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert logout_resp.status_code == 204

    async def test_login(self, async_client: AsyncClient):
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "login@example.com", "password": "strongpass123"},
        )
        response = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "strongpass123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, async_client: AsyncClient):
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "wp@example.com", "password": "correctpass"},
        )
        response = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "wp@example.com", "password": "wrongpass"},
        )
        assert response.status_code == 401

    async def test_refresh_token(self, async_client: AsyncClient):
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "refresh@example.com", "password": "strongpass123"},
        )
        login_resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "refresh@example.com", "password": "strongpass123"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    async def test_me_endpoint(self, async_client: AsyncClient):
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "me@example.com", "password": "strongpass123"},
        )
        login_resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "me@example.com", "password": "strongpass123"},
        )
        token = login_resp.json()["access_token"]

        response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["email"] == "me@example.com"

    async def test_api_key_auth(self, async_client: AsyncClient):
        """API key from registration should authenticate requests."""
        reg = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "apikey@example.com", "password": "strongpass123"},
        )
        api_key = reg.json()["api_key"]

        response = await async_client.get(
            "/api/v1/tasks",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200

    async def test_health_endpoint(self, async_client: AsyncClient):
        response = await async_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
