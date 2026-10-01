from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.core.deps import CurrentUser, SettingsDep, get_inference_service, get_provider
from app.providers.base import InferenceProvider
from app.schemas.inference import (
    CompletionRequest,
    CompletionResponse,
    ExtractRequest,
    ExtractResponse,
    ModelInfo,
    ProviderStatus,
    ProviderSwitchRequest,
)
from app.services.inference_service import InferenceService
from app.services.provider_service import provider_status, switch_runtime_provider

router = APIRouter()


def _rate_headers(response: Response, limit: int, remaining: int) -> None:
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)


@router.get("/models", response_model=ModelInfo)
async def models(
    _user: CurrentUser,
    provider: Annotated[InferenceProvider, Depends(get_provider)],
) -> ModelInfo:
    ready = await provider.health()
    return ModelInfo(
        provider=provider.name,
        model=provider.model,
        ready=ready,
        capabilities=["chat", "structured_output", "tools"],
    )


@router.get("/provider", response_model=ProviderStatus)
async def get_provider_status(
    request: Request,
    _user: CurrentUser,
    provider: Annotated[InferenceProvider, Depends(get_provider)],
) -> ProviderStatus:
    return await provider_status(request.app, provider)


@router.put("/provider", response_model=ProviderStatus)
async def put_provider(
    body: ProviderSwitchRequest,
    request: Request,
    _user: CurrentUser,
) -> ProviderStatus:
    provider = await switch_runtime_provider(request.app, body.provider)
    return await provider_status(request.app, provider)


@router.post("/completions", response_model=CompletionResponse)
async def completions(
    body: CompletionRequest,
    user: CurrentUser,
    settings: SettingsDep,
    response: Response,
    service: Annotated[InferenceService, Depends(get_inference_service)],
) -> CompletionResponse:
    result, remaining = await service.complete(user, body)
    _rate_headers(response, settings.rate_limit_rpm, remaining)
    return result


@router.post("/extract", response_model=ExtractResponse)
async def extract(
    body: ExtractRequest,
    user: CurrentUser,
    settings: SettingsDep,
    response: Response,
    service: Annotated[InferenceService, Depends(get_inference_service)],
) -> ExtractResponse:
    result, remaining = await service.extract(user, body)
    _rate_headers(response, settings.rate_limit_rpm, remaining)
    return result
