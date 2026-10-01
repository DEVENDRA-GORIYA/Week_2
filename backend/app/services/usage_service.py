from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import BudgetExceeded
from app.core.time import utcnow
from app.models.usage import UsageEvent
from app.schemas.common import UsageEventPublic, UsageMeResponse, UsageStats, UsageSummaryResponse


class UsageService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def used_today(self, user_id: int) -> int:
        total = await self.session.scalar(self._sum_query(user_id))
        return int(total or 0)

    async def assert_within_budget(self, user_id: int, estimated_prompt_tokens: int) -> None:
        used = await self.used_today(user_id)
        if used + estimated_prompt_tokens > self.settings.daily_token_budget:
            raise BudgetExceeded(
                f"Daily token budget exceeded ({used}/{self.settings.daily_token_budget})."
            )

    async def record(
        self,
        *,
        user_id: int,
        endpoint: str,
        provider: str,
        model: str,
        usage: UsageStats,
        latency_ms: float,
    ) -> None:
        self.session.add(
            UsageEvent(
                user_id=user_id,
                endpoint=endpoint,
                provider=provider,
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                latency_ms=round(latency_ms, 1),
            )
        )
        await self.session.commit()

    async def for_user(self, user_id: int) -> UsageMeResponse:
        used = await self.used_today(user_id)
        rows = await self.session.scalars(
            select(UsageEvent)
            .where(UsageEvent.user_id == user_id)
            .order_by(UsageEvent.created_at.desc(), UsageEvent.id.desc())
            .limit(50)
        )
        remaining = max(0, self.settings.daily_token_budget - used)
        return UsageMeResponse(
            day_tokens=used,
            daily_budget=self.settings.daily_token_budget,
            remaining_tokens=remaining,
            events=[UsageEventPublic.model_validate(row, from_attributes=True) for row in rows],
        )

    async def summary(self) -> UsageSummaryResponse:
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        row = await self.session.execute(
            select(
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
                func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            ).where(UsageEvent.created_at >= start)
        )
        requests, prompt_tokens, completion_tokens = row.one()
        prompt = int(prompt_tokens or 0)
        completion = int(completion_tokens or 0)
        return UsageSummaryResponse(
            day_requests=int(requests or 0),
            day_prompt_tokens=prompt,
            day_completion_tokens=completion,
            day_total_tokens=prompt + completion,
            daily_budget_per_user=self.settings.daily_token_budget,
        )

    def _sum_query(self, user_id: int):
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return select(
            func.coalesce(func.sum(UsageEvent.prompt_tokens + UsageEvent.completion_tokens), 0)
        ).where(UsageEvent.user_id == user_id, UsageEvent.created_at >= start)
