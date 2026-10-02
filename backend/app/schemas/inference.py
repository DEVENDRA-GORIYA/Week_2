from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import UsageStats


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class CompletionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "messages": [{"role": "user", "content": "Explain JWT in one sentence."}],
                    "temperature": 0.2,
                    "max_tokens": 512,
                }
            ]
        },
    )

    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    prompt_id: str | None = Field(default=None, max_length=40)
    tools_enabled: bool = False

    @field_validator("messages")
    @classmethod
    def require_user_message(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if not any(message.role == "user" for message in value):
            raise ValueError("messages must include at least one user message")
        return value


class ToolTraceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any]
    result: str


class CompletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    model: str
    provider: str
    output: str
    finish_reason: Literal["stop", "tool_limit", "degraded"]
    usage: UsageStats
    latency_ms: float
    tool_trace: list[ToolTraceItem] = Field(default_factory=list)


class SupportTicket(BaseModel):
    """Model-emitted object. Unknown keys are dropped; required fields stay strict."""

    model_config = ConfigDict(extra="ignore")

    category: Literal["billing", "technical", "account", "other"]
    priority: Literal["low", "medium", "high"]
    summary: str = Field(min_length=1, max_length=300)
    customer_intent: str = Field(min_length=1, max_length=300)

    @field_validator("category", "priority", mode="before")
    @classmethod
    def normalize_label(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class SentimentResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: Literal["positive", "neutral", "negative"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=500)

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class ActionItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    owner: str = Field(min_length=1, max_length=80)
    task: str = Field(min_length=1, max_length=300)
    due: str | None = Field(default=None, max_length=80)


class ActionItems(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1, max_length=300)
    items: list[ActionItem] = Field(default_factory=list, max_length=10)


ExtractTask = Literal["support_ticket", "sentiment", "action_items"]


class ExtractRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "task": "support_ticket",
                    "text": "I was charged twice for the same invoice and need it reversed.",
                }
            ]
        },
    )

    task: ExtractTask
    text: str = Field(min_length=1, max_length=8000)
    max_tokens: int = Field(default=800, ge=1, le=4096)


class ExtractResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task: ExtractTask
    result: SupportTicket | SentimentResult | ActionItems
    model: str
    provider: str
    usage: UsageStats
    latency_ms: float
    retries: int


class PromptPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["chat", "extract"]
    title: str
    description: str
    system: str


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    ready: bool
    capabilities: list[str]


class ProviderOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["ollama", "groq", "openai_compatible"]
    label: str
    model: str
    configured: bool


class ProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: Literal["ollama", "groq", "openai_compatible"]
    model: str
    ready: bool
    options: list[ProviderOption]


class ProviderSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["ollama", "groq", "openai_compatible"]
