from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.core.errors import NotFound, SchemaViolation
from app.schemas.inference import ActionItems, SentimentResult, SupportTicket
from app.tools.registry import tool_catalog

PromptKind = Literal["chat", "extract"]


def _tool_protocol() -> str:
    lines = [
        "You are Helix, a precise assistant with tools.",
        "Reply with ONLY one JSON object and no markdown.",
        "To call a tool:",
        '{"action":"tool","name":"<tool>","arguments":{...}}',
        "When you can answer:",
        '{"action":"final","content":"your answer"}',
        "Tools:",
    ]
    for tool in tool_catalog():
        lines.append(f"- {tool['name']}: {tool['description']}")
    lines.extend(
        [
            'calculator arguments: {"expression":"numbers with + - * / and parentheses"}',
            "utc_now arguments: {}",
            'word_stats arguments: {"text":"string to measure"}',
        ]
    )
    return "\n".join(lines)


TOOL_PROTOCOL = _tool_protocol()


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    kind: PromptKind
    title: str
    description: str
    system: str
    output_model: type[BaseModel] | None = None


_SUPPORT_TICKET = """You classify one customer support message.
Return ONLY a JSON object with these keys and no markdown:
- category: billing, technical, account, or other
- priority: low, medium, or high
- summary: one sentence, at most 300 characters
- customer_intent: what the customer wants, at most 300 characters
Do not add keys. Do not wrap the JSON in prose."""

_SENTIMENT = """You label the sentiment of one piece of text.
Return ONLY a JSON object with these keys and no markdown:
- label: positive, neutral, or negative
- confidence: a number from 0 to 1
- rationale: one short sentence
Do not add keys. Do not wrap the JSON in prose."""

_ACTION_ITEMS = """You extract action items from meeting notes.
Return ONLY a JSON object with these keys and no markdown:
- summary: one sentence
- items: an array of objects with owner (string), task (string), and due (string or null)
Use an empty items array when there is nothing to do.
Do not add keys. Keep at most 10 items."""

_CONCISE = """You are Helix, a concise assistant.
Answer in plain prose.
Do not invent facts, numbers, or citations.
If you are unsure, say so."""

_SUPPORT_AGENT = """You are a support agent writing a short reply.
Be polite and specific.
Do not promise refunds, credits, or actions you cannot verify from the message."""


TEMPLATES: dict[str, PromptTemplate] = {
    "concise_assistant": PromptTemplate(
        id="concise_assistant",
        kind="chat",
        title="Concise assistant",
        description="Short answers with an explicit uncertainty rule.",
        system=_CONCISE,
    ),
    "support_agent": PromptTemplate(
        id="support_agent",
        kind="chat",
        title="Support agent",
        description="Customer reply that cannot promise unverified actions.",
        system=_SUPPORT_AGENT,
    ),
    "support_ticket": PromptTemplate(
        id="support_ticket",
        kind="extract",
        title="Support ticket",
        description="Classify a customer message into a ticket.",
        system=_SUPPORT_TICKET,
        output_model=SupportTicket,
    ),
    "sentiment": PromptTemplate(
        id="sentiment",
        kind="extract",
        title="Sentiment",
        description="Label sentiment with a confidence score and a rationale.",
        system=_SENTIMENT,
        output_model=SentimentResult,
    ),
    "action_items": PromptTemplate(
        id="action_items",
        kind="extract",
        title="Action items",
        description="Pull owners, tasks, and optional due dates from notes.",
        system=_ACTION_ITEMS,
        output_model=ActionItems,
    ),
}


def list_prompts() -> list[PromptTemplate]:
    return list(TEMPLATES.values())


def get_prompt(prompt_id: str) -> PromptTemplate:
    template = TEMPLATES.get(prompt_id)
    if template is None:
        raise NotFound(f"Unknown prompt '{prompt_id}'.")
    return template


def require_chat_prompt(prompt_id: str) -> PromptTemplate:
    template = get_prompt(prompt_id)
    if template.kind != "chat":
        raise SchemaViolation("That prompt is an extraction task. Call POST /api/v1/extract.")
    return template


def require_extract_prompt(task: str) -> PromptTemplate:
    template = get_prompt(task)
    if template.kind != "extract" or template.output_model is None:
        raise SchemaViolation("That prompt is not an extraction task.")
    return template
