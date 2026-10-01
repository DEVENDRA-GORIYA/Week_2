from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import Conflict, Unauthorized
from app.core.security import (
    hash_password_async,
    verify_dummy_password,
    verify_password_async,
)
from app.models.user import User
from app.schemas.common import LoginRequest, RegisterRequest


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def register(self, data: RegisterRequest) -> User:
        email = data.email.lower()
        existing = await self.session.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise Conflict("An account with that email already exists.")

        role = "admin" if email in self.settings.admin_email_set else "user"
        user = User(
            email=email,
            hashed_password=await hash_password_async(data.password),
            role=role,
        )
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise Conflict("An account with that email already exists.") from None
        await self.session.refresh(user)
        return user

    async def authenticate(self, data: LoginRequest) -> User:
        email = data.email.lower()
        user = await self.session.scalar(select(User).where(User.email == email))
        if user is None:
            await verify_dummy_password(data.password)
            raise Unauthorized("Invalid email or password.")
        if not await verify_password_async(data.password, user.hashed_password):
            raise Unauthorized("Invalid email or password.")
        return user
