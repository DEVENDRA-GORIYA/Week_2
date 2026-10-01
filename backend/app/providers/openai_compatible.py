import httpx

from app.core.errors import ProviderError
from app.providers.base import Generation


class OpenAICompatibleProvider:
    """Chat client for Ollama, Groq, and other OpenAI-compatible servers."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        unreachable_hint: str,
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._unreachable_hint = unreachable_hint
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> Generation:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("Model request timed out.", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self._unreachable_hint, status_code=503) from exc

        if not response.is_success:
            raise ProviderError(_provider_message(response), status_code=502)

        try:
            body = response.json()
            message = body["choices"][0]["message"]
            content = message.get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Model provider returned an unexpected payload.") from exc

        if not isinstance(content, str):
            content = str(content)

        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return Generation(
            text=content[:8000],
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
            model=str(body.get("model") or self.model),
        )

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self.base_url}/models", headers=self._headers)
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
            return False
        names = {item.get("id") for item in models if isinstance(item, dict)}
        return self.model in names

    async def aclose(self) -> None:
        await self._client.aclose()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _provider_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Model provider returned HTTP {response.status_code}."
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
    return f"Model provider returned HTTP {response.status_code}."
