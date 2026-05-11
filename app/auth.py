import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import bcrypt
from jose import jwt

from app.config import settings


def hash_password(password: str) -> str:
    # Use rounds=12 per OWASP recommendation (default 10 is below minimum guidance)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_expire_minutes)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "exp": expire,
        # iss/aud prevent token confusion if additional services are added later
        "iss": settings.app_name,
        "aud": settings.app_name,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        # jti enables server-side revocation: stored in Redis, deleted on logout
        "jti": secrets.token_hex(16),
        "exp": expire,
        "iss": settings.app_name,
        "aud": settings.app_name,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm)


def decode_refresh_token(token: str) -> Optional[dict]:
    """Decode and validate a refresh token. Returns the full payload dict or None."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.app_name,
            issuer=settings.app_name,
        )
        if payload.get("type") != "refresh":
            return None
        return payload
    except Exception:
        return None
