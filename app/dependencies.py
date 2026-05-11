from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import UserORM, UserRole

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header),
) -> UserORM:
    if api_key:
        result = await db.execute(select(UserORM).where(UserORM.api_key == api_key))
        user = result.scalar_one_or_none()
        if user:
            return user

    if credentials:
        token = credentials.credentials
        try:
            # Validate iss and aud to prevent token confusion across services
            payload = jwt.decode(
                token,
                settings.jwt_secret.get_secret_value(),
                algorithms=[settings.jwt_algorithm],
                audience=settings.app_name,
                issuer=settings.app_name,
            )
            user_id_str: Optional[str] = payload.get("sub")
            token_type: Optional[str] = payload.get("type")
            if user_id_str is None or token_type != "access":
                raise _credentials_error()
            user_id = UUID(user_id_str)
        except (JWTError, ValueError):
            raise _credentials_error()

        result = await db.execute(select(UserORM).where(UserORM.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise _credentials_error()
        return user

    raise _credentials_error()


def require_role(*roles: UserRole):
    async def _check(current_user: UserORM = Depends(get_current_user)) -> UserORM:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "FORBIDDEN", "message": "Insufficient permissions"}, "request_id": ""},
            )
        return current_user
    return _check


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing credentials"}, "request_id": ""},
        headers={"WWW-Authenticate": "Bearer"},
    )
