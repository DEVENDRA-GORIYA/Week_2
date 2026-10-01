from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.config import Settings, get_settings
from app.core.errors import Forbidden, Unauthorized
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User
from app.providers.base import InferenceProvider
from app.services.auth_service import AuthService
from app.services.inference_service import InferenceService
from app.services.usage_service import UsageService

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="JWT")

DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_provider(request: Request) -> InferenceProvider:
    return request.app.state.provider


def get_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.rate_limiter


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise Unauthorized("Missing bearer token.")
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise Unauthorized("Invalid or expired token.")
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise Unauthorized("Invalid or expired token.") from None
    user = await session.get(User, user_id)
    if user is None:
        raise Unauthorized("Invalid or expired token.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise Forbidden("Admin role required.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def get_auth_service(session: DbSession, settings: SettingsDep) -> AuthService:
    return AuthService(session, settings)


def get_usage_service(session: DbSession, settings: SettingsDep) -> UsageService:
    return UsageService(session, settings)


def get_inference_service(
    session: DbSession,
    settings: SettingsDep,
    provider: Annotated[InferenceProvider, Depends(get_provider)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_limiter)],
) -> InferenceService:
    return InferenceService(session, provider, limiter, settings)
