import json
import logging
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import HelixError, SchemaViolation
from app.core.rate_limit import SlidingWindowLimiter
from app.core.tokens import estimate_messages, estimate_tokens
from app.models.user import User
from app.prompts.json_utils import extract_json_object
from app.prompts.library import TOOL_PROTOCOL, require_chat_prompt, require_extract_prompt
from app.providers.base import Generation, InferenceProvider
from app.schemas.common import UsageStats
from app.schemas.inference import (
    CompletionRequest,
    CompletionResponse,
    ExtractRequest,
    ExtractResponse,
    ToolTraceItem,
)
from app.services.usage_service import UsageService
from app.tools.registry import run_tool

logger = logging.getLogger(__name__)

FinishReason = Literal["stop", "tool_limit", "degraded"]


class ToolCallDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: Literal["tool"]
    name: str = Field(min_length=1, max_length=40)
    arguments: dict[str, Any] = Field(default_factory=dict)


class FinalDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: Literal["final"]
    content: str = Field(min_length=1, max_length=8000)


Decision = Annotated[ToolCallDecision | FinalDecision, Field(discriminator="action")]
_DECISION = TypeAdapter(Decision)


@dataclass
class ToolRun:
    output: str
    trace: list[ToolTraceItem]
    generations: list[Generation]
    finish_reason: FinishReason


class InferenceService:
    def __init__(
        self,
        session: AsyncSession,
        provider: InferenceProvider,
        limiter: SlidingWindowLimiter,
        settings: Settings,
    ) -> None:
        self.session = session
        self.provider = provider
        self.limiter = limiter
        self.settings = settings
        self.usage = UsageService(session, settings)

    async def complete(
        self, user: User, request: CompletionRequest
    ) -> tuple[CompletionResponse, int]:
        remaining = self.limiter.check(user.id)
        messages = self._messages_for_completion(request)
        generations: list[Generation] = []
        started = time.perf_counter()
        saved = False

        async def persist(endpoint: str) -> UsageStats:
            nonlocal saved
            usage = _combine_usage(generations)
            if generations and not saved:
                await self.usage.record(
                    user_id=user.id,
                    endpoint=endpoint,
                    provider=self.provider.name,
                    model=self.provider.model,
                    usage=usage,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
                saved = True
            return usage

        try:
            if request.tools_enabled:
                result = await self._run_tools(user.id, messages, request)
                generations.extend(result.generations)
                output = result.output
                finish_reason = result.finish_reason
                trace = result.trace
            else:
                generation = await self._chat(
                    user.id, messages, request.temperature, request.max_tokens
                )
                generations.append(generation)
                output = generation.text.strip() or "(empty model response)"
                finish_reason = "stop"
                trace = []

            usage = await persist("completions")
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            self._log("completions", user.id, usage, latency_ms)
            return (
                CompletionResponse(
                    id=_new_id("cmpl"),
                    model=self.provider.model,
                    provider=self.provider.name,
                    output=output,
                    finish_reason=finish_reason,
                    usage=usage,
                    latency_ms=latency_ms,
                    tool_trace=trace,
                ),
                remaining,
            )
        except Exception:
            await persist("completions")
            raise

    async def extract(self, user: User, request: ExtractRequest) -> tuple[ExtractResponse, int]:
        remaining = self.limiter.check(user.id)
        template = require_extract_prompt(request.task)
        assert template.output_model is not None
        messages: list[dict[str, str]] = [
            {"role": "system", "content": template.system},
            {"role": "user", "content": request.text},
        ]
        generations: list[Generation] = []
        started = time.perf_counter()
        saved = False
        retries = 0
        parsed: BaseModel | None = None

        async def persist() -> UsageStats:
            nonlocal saved
            usage = _combine_usage(generations)
            if generations and not saved:
                await self.usage.record(
                    user_id=user.id,
                    endpoint="extract",
                    provider=self.provider.name,
                    model=self.provider.model,
                    usage=usage,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
                saved = True
            return usage

        try:
            for attempt in range(2):
                generation = await self._chat(user.id, messages, 0.0, request.max_tokens)
                generations.append(generation)
                try:
                    payload = extract_json_object(generation.text)
                    parsed = template.output_model.model_validate(payload)
                    break
                except (ValueError, ValidationError) as exc:
                    retries += 1
                    if attempt == 1:
                        raise SchemaViolation(
                            "Model output did not match the task schema after one retry."
                        ) from exc
                    messages = [
                        *messages,
                        {"role": "assistant", "content": generation.text[:2000]},
                        {
                            "role": "user",
                            "content": (
                                "Schema validation failed: "
                                f"{_short_error(exc)}. "
                                "Reply with ONLY a JSON object that matches the schema. "
                                "No markdown."
                            ),
                        },
                    ]

            if parsed is None:
                raise SchemaViolation("Model output did not match the task schema.")

            usage = await persist()
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            self._log("extract", user.id, usage, latency_ms)
            return (
                ExtractResponse(
                    id=_new_id("ext"),
                    task=request.task,
                    result=parsed,
                    model=self.provider.model,
                    provider=self.provider.name,
                    usage=usage,
                    latency_ms=latency_ms,
                    retries=retries,
                ),
                remaining,
            )
        except Exception:
            await persist()
            raise

    def _messages_for_completion(self, request: CompletionRequest) -> list[dict[str, str]]:
        prefix: list[dict[str, str]] = []
        if request.prompt_id:
            prefix.append(
                {"role": "system", "content": require_chat_prompt(request.prompt_id).system}
            )
        if request.tools_enabled:
            prefix.append({"role": "system", "content": TOOL_PROTOCOL})
        body = [{"role": message.role, "content": message.content} for message in request.messages]
        return prefix + body

    async def _chat(
        self,
        user_id: int,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> Generation:
        await self.usage.assert_within_budget(user_id, estimate_messages(messages))
        generation = await self.provider.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        prompt_tokens = (
            generation.prompt_tokens
            if generation.prompt_tokens is not None
            else estimate_messages(messages)
        )
        completion_tokens = (
            generation.completion_tokens
            if generation.completion_tokens is not None
            else estimate_tokens(generation.text)
        )
        return Generation(
            text=generation.text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=generation.model or self.provider.model,
        )

    async def _run_tools(
        self,
        user_id: int,
        messages: list[dict[str, str]],
        request: CompletionRequest,
    ) -> ToolRun:
        trace: list[ToolTraceItem] = []
        generations: list[Generation] = []
        working = list(messages)

        for _step in range(self.settings.max_tool_steps):
            generation = await self._chat(user_id, working, request.temperature, request.max_tokens)
            generations.append(generation)
            decision, error = _parse_decision(generation.text)

            if decision is None:
                if not _looks_like_protocol(generation.text):
                    text = generation.text.strip() or "(empty model response)"
                    return ToolRun(text, trace, generations, "degraded")
                working = [
                    *working,
                    {"role": "assistant", "content": generation.text},
                    {
                        "role": "user",
                        "content": (
                            "That was not valid tool JSON. "
                            f"Problem: {error}. "
                            'Reply with ONLY {"action":"final","content":"..."} '
                            'or {"action":"tool","name":"...","arguments":{}}.'
                        ),
                    },
                ]
                continue

            if isinstance(decision, FinalDecision):
                return ToolRun(decision.content, trace, generations, "stop")

            result_text = _execute_for_trace(decision.name, decision.arguments)
            trace.append(
                ToolTraceItem(
                    name=decision.name,
                    arguments=decision.arguments,
                    result=result_text,
                )
            )
            working = [
                *working,
                {"role": "assistant", "content": generation.text},
                {
                    "role": "user",
                    "content": (f"Tool result for {decision.name}: {result_text}. Continue."),
                },
            ]

        generation = await self._chat(
            user_id,
            [
                *working,
                {
                    "role": "user",
                    "content": (
                        "Tool limit reached. Reply with ONLY "
                        '{"action":"final","content":"your answer"}.'
                    ),
                },
            ],
            request.temperature,
            request.max_tokens,
        )
        generations.append(generation)
        decision, _error = _parse_decision(generation.text)
        if isinstance(decision, FinalDecision):
            return ToolRun(decision.content, trace, generations, "tool_limit")
        text = generation.text.strip() or "(empty model response)"
        return ToolRun(text, trace, generations, "degraded")

    def _log(self, endpoint: str, user_id: int, usage: UsageStats, latency_ms: float) -> None:
        logger.info(
            "inference endpoint=%s user_id=%s provider=%s model=%s tokens=%s latency_ms=%.1f",
            endpoint,
            user_id,
            self.provider.name,
            self.provider.model,
            usage.total_tokens,
            latency_ms,
        )


def _combine_usage(generations: list[Generation]) -> UsageStats:
    prompt = sum(item.prompt_tokens or 0 for item in generations)
    completion = sum(item.completion_tokens or 0 for item in generations)
    return UsageStats(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def _parse_decision(text: str) -> tuple[ToolCallDecision | FinalDecision | None, str | None]:
    try:
        payload = extract_json_object(text)
    except ValueError as exc:
        return None, str(exc)
    try:
        decision = _DECISION.validate_python(payload)
    except ValidationError as exc:
        message = exc.errors()[0]["msg"] if exc.errors() else "invalid decision"
        return None, message
    if isinstance(decision, (ToolCallDecision, FinalDecision)):
        return decision, None
    return None, "invalid decision"


def _looks_like_protocol(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("{") or '"action"' in stripped


def _execute_for_trace(name: str, arguments: dict[str, Any]) -> str:
    try:
        result = run_tool(name, arguments)
    except HelixError as exc:
        result = {"error": exc.message}
    return json.dumps(result)[:2000]


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError) and exc.errors():
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first.get("loc", []))
        msg = str(first.get("msg", "invalid"))
        return f"{loc}: {msg}" if loc else msg
    return str(exc)[:300]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"
