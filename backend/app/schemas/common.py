from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    email: EmailStr
    role: Literal["user", "admin"]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserPublic


class UsageStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class UsageEventPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    endpoint: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.isoformat() + "Z"


class UsageMeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_tokens: int
    daily_budget: int
    remaining_tokens: int
    events: list[UsageEventPublic]


class UsageSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_requests: int
    day_prompt_tokens: int
    day_completion_tokens: int
    day_total_tokens: int
    daily_budget_per_user: int
