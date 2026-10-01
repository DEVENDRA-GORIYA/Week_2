from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.config import Settings
from app.core.deps import CurrentUser, SettingsDep, get_auth_service
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.common import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from app.services.auth_service import AuthService

router = APIRouter()


def _token(user: User, settings: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id=user.id, role=user.role),
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserPublic.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    settings: SettingsDep,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    user = await service.register(body)
    return _token(user, settings)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    settings: SettingsDep,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    user = await service.authenticate(body)
    return _token(user, settings)


@router.get("/me", response_model=UserPublic)
async def me(user: CurrentUser) -> User:
    return user
