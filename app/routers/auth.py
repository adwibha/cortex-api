import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password, verify_password, create_access_token, create_refresh_token, decode_refresh_token
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.events.bus import get_redis
from app.models.user import UserORM
from app.schemas import UserRegister, UserLogin, TokenResponse, AccessTokenResponse, RefreshRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

_GENERIC_ACCOUNT_ERROR = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={"error": {"code": "EMAIL_TAKEN", "message": "An account with these details could not be created"}, "request_id": ""},
)


def _refresh_jti_key(jti: str) -> str:
    return f"refresh_jti:{jti}"


async def _store_refresh_jti(jti: str) -> None:
    """Persist refresh token JTI in Redis so logout can revoke it before expiry."""
    try:
        r = get_redis()
        ttl = settings.jwt_refresh_expire_days * 86400
        await r.setex(_refresh_jti_key(jti), ttl, "1")
    except Exception as exc:
        logger.warning("Could not store refresh JTI in Redis: %s", exc)


async def _revoke_refresh_jti(jti: str) -> None:
    """Remove a refresh token JTI from Redis, effectively revoking it."""
    try:
        r = get_redis()
        await r.delete(_refresh_jti_key(jti))
    except Exception as exc:
        logger.warning("Could not revoke refresh JTI in Redis: %s", exc)


async def _is_refresh_jti_valid(jti: str) -> bool:
    """Return True if the JTI is still active in Redis (or Redis is unavailable — fail open for availability)."""
    try:
        r = get_redis()
        return bool(await r.exists(_refresh_jti_key(jti)))
    except Exception as exc:
        logger.warning("Redis unavailable for JTI check, failing open: %s", exc)
        return True  # graceful degradation: fall back to JWT signature + expiry only


def _login_fail_key(email: str) -> str:
    return f"login_failures:{email}"


def _login_lock_key(email: str) -> str:
    return f"login_locked:{email}"


async def _check_login_lockout(email: str) -> None:
    """Raise 429 if the account is currently locked due to repeated failures."""
    try:
        r = get_redis()
        if await r.exists(_login_lock_key(email)):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": {"code": "ACCOUNT_LOCKED", "message": "Too many failed login attempts. Try again later."}, "request_id": ""},
                headers={"Retry-After": str(settings.login_lockout_seconds)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Redis unavailable for lockout check: %s", exc)


async def _record_login_failure(email: str) -> None:
    """Increment failure counter; lock account after max_failures consecutive failures."""
    try:
        r = get_redis()
        key = _login_fail_key(email)
        failures = await r.incr(key)
        await r.expire(key, 900)  # 15-minute observation window
        if failures >= settings.login_max_failures:
            await r.setex(_login_lock_key(email), settings.login_lockout_seconds, "1")
            await r.delete(key)
    except Exception as exc:
        logger.warning("Redis unavailable for failure tracking: %s", exc)


async def _clear_login_failures(email: str) -> None:
    try:
        r = get_redis()
        await r.delete(_login_fail_key(email))
        await r.delete(_login_lock_key(email))
    except Exception as exc:
        logger.warning("Redis unavailable for clearing failures: %s", exc)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    # Pre-check for a friendly early error on the common path
    result = await db.execute(select(UserORM).where(UserORM.email == payload.email))
    if result.scalar_one_or_none():
        raise _GENERIC_ACCOUNT_ERROR

    user = UserORM(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        api_key=UserORM.generate_api_key(),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Handles the TOCTOU race: two concurrent requests both passed the pre-check
        await db.rollback()
        raise _GENERIC_ACCOUNT_ERROR
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    await _check_login_lockout(payload.email)

    result = await db.execute(select(UserORM).where(UserORM.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        await _record_login_failure(payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password"}, "request_id": ""},
        )

    await _clear_login_failures(payload.email)
    refresh_token = create_refresh_token(user.id)

    # Decode to extract the jti we just embedded, then persist it for revocation support
    token_payload = decode_refresh_token(refresh_token)
    if token_payload and token_payload.get("jti"):
        await _store_refresh_jti(token_payload["jti"])

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_payload = decode_refresh_token(payload.refresh_token)
    if not token_payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_TOKEN", "message": "Invalid or expired refresh token"}, "request_id": ""},
        )

    # Verify the JTI is still active (not revoked via logout)
    jti = token_payload.get("jti")
    if jti and not await _is_refresh_jti_valid(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "TOKEN_REVOKED", "message": "Refresh token has been revoked"}, "request_id": ""},
        )

    user_id = UUID(token_payload["sub"])
    result = await db.execute(select(UserORM).where(UserORM.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "User no longer exists"}, "request_id": ""},
        )

    return AccessTokenResponse(access_token=create_access_token(user.id))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest):
    """Revoke a refresh token so it can no longer be used to mint access tokens."""
    token_payload = decode_refresh_token(payload.refresh_token)
    if token_payload and token_payload.get("jti"):
        await _revoke_refresh_jti(token_payload["jti"])


@router.get("/me", response_model=UserResponse)
async def me(current_user: UserORM = Depends(get_current_user)):
    return current_user
