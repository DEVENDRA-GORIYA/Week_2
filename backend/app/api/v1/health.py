from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.core.deps import SettingsDep, get_provider
from app.core.errors import ProviderError
from app.providers.base import InferenceProvider

router = APIRouter()


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    version: str


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"]
    provider: str
    model: str


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(status="ok", service="helix", version=settings.app_version)


@router.get("/ready", response_model=ReadyResponse)
async def ready(
    provider: Annotated[InferenceProvider, Depends(get_provider)],
) -> ReadyResponse:
    if not await provider.health():
        message = f"Model provider '{provider.name}' is not ready for model '{provider.model}'."
        if provider.name == "ollama":
            message += f" Start Ollama and run `ollama pull {provider.model}`."
        raise ProviderError(message, status_code=503)
    return ReadyResponse(status="ready", provider=provider.name, model=provider.model)
