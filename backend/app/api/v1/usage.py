from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import AdminUser, CurrentUser, get_usage_service
from app.schemas.common import UsageMeResponse, UsageSummaryResponse
from app.services.usage_service import UsageService

router = APIRouter()


@router.get("/me", response_model=UsageMeResponse)
async def my_usage(
    user: CurrentUser,
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> UsageMeResponse:
    return await service.for_user(user.id)


@router.get("/summary", response_model=UsageSummaryResponse)
async def usage_summary(
    _admin: AdminUser,
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> UsageSummaryResponse:
    return await service.summary()
