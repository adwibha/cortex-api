from typing import List

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite+aiosqlite:///./tasks.db"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Ollama — plain str so f-string interpolation never produces double slashes
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:1b"
    ollama_embed_model: str = "nomic-embed-text"

    @field_validator("ollama_url", mode="after")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    # JWT
    jwt_secret: SecretStr = SecretStr("change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 30
    jwt_refresh_expire_days: int = 7

    # Rate limiting
    rate_limit_per_minute: int = 60
    # Tighter limit applied specifically to auth endpoints (login, register, refresh)
    auth_rate_limit_per_minute: int = 10
    # Track failed logins per account; lock after this many failures
    login_max_failures: int = 5
    login_lockout_seconds: int = 1800  # 30 minutes

    # CORS — comma-separated list of allowed origins
    cors_allowed_origins: str = "http://localhost:3000"

    # Observability — optional bearer token protecting /metrics
    # Leave empty string to allow unauthenticated access (local dev only)
    metrics_token: str = ""

    # App
    app_name: str = "cortex-api"
    app_version: str = "2.0.0"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("jwt_secret", mode="after")
    @classmethod
    def reject_default_secret_in_production(cls, v: SecretStr, info) -> SecretStr:
        debug = (info.data or {}).get("debug", True)
        if not debug and v.get_secret_value() == "change-me-in-production":
            raise ValueError("JWT_SECRET must be changed from the default value before running in production")
        return v

    def get_cors_origins(self) -> List[str]:
        """Parse the comma-separated CORS origins string into a list."""
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


settings = Settings()
