import httpx

from app.core.errors import ProviderError
from app.providers.base import Generation


def _auth_headers(*, api_key: str, base_url: str, api_version: str) -> dict[str, str]:
    """Public Anthropic uses x-api-key; ICA and similar gateways use Bearer."""
    headers = {
        "anthropic-version": api_version,
        "content-type": "application/json",
    }
    host = base_url.lower()
    if "api.anthropic.com" in host:
        headers["x-api-key"] = api_key
    else:
        # IBM Consulting Advantage and similar proxies expect Bearer auth.
        headers["Authorization"] = f"Bearer {api_key}"
        headers["x-api-key"] = api_key
    return headers


class AnthropicProvider:
    """Anthropic Messages API client (public Anthropic or ICA gateway)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        api_version: str = "2023-06-01",
    ) -> None:
        self.name = "anthropic"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._headers = _auth_headers(
            api_key=api_key, base_url=self.base_url, api_version=api_version
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> Generation:
        system, chat_messages = _split_system(messages)
        if not chat_messages:
            raise ProviderError("Anthropic requires at least one user message.")

        payload: dict[str, object] = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": min(max(temperature, 0.0), 1.0),
        }
        if system:
            payload["system"] = system

        try:
            response = await self._client.post(
                f"{self.base_url}/v1/messages",
                json=payload,
                headers=self._headers,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("Claude request timed out.", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "Could not reach the Claude API gateway. "
                "Check ANTHROPIC_BASE_URL and your ICA / Anthropic key.",
                status_code=503,
            ) from exc

        if not response.is_success:
            raise ProviderError(_anthropic_error(response), status_code=502)

        try:
            body = response.json()
            text = _extract_text(body)
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        except (ValueError, TypeError, KeyError) as exc:
            raise ProviderError("Anthropic returned an unexpected payload.") from exc

        return Generation(
            text=text[:8000],
            prompt_tokens=_optional_int(usage.get("input_tokens")),
            completion_tokens=_optional_int(usage.get("output_tokens")),
            model=str(body.get("model") or self.model),
        )

    async def health(self) -> bool:
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/models",
                headers=self._headers,
            )
        except httpx.HTTPError:
            return False
        if not response.is_success:
            return False
        try:
            body = response.json()
        except ValueError:
            return False
        models = body.get("data")
        if not isinstance(models, list):
            # Some accounts can call Messages but not list models; treat 200 as ready.
            return True
        names = {item.get("id") for item in models if isinstance(item, dict)}
        if not names:
            return True
        return self.model in names or any(
            isinstance(name, str) and name.startswith(self.model) for name in names
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _split_system(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    system_parts: list[str] = []
    chat: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role", "")
        content = message.get("content", "")
        if role == "system":
            if content.strip():
                system_parts.append(content.strip())
            continue
        if role not in {"user", "assistant"}:
            continue
        chat.append({"role": role, "content": content})

    # Anthropic requires the first message to be from the user.
    while chat and chat[0]["role"] != "user":
        chat.pop(0)
    if not chat:
        return "\n\n".join(system_parts), []

    # Merge consecutive same-role turns (Anthropic expects alternation).
    merged: list[dict[str, str]] = []
    for item in chat:
        if merged and merged[-1]["role"] == item["role"]:
            merged[-1]["content"] = f"{merged[-1]['content']}\n\n{item['content']}"
        else:
            merged.append(dict(item))
    return "\n\n".join(system_parts), merged


def _extract_text(body: dict[str, object]) -> str:
    content = body.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _anthropic_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Anthropic returned HTTP {response.status_code}."
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
    if isinstance(error, str) and error.strip():
        return error.strip()[:300]
    return f"Anthropic returned HTTP {response.status_code}."
