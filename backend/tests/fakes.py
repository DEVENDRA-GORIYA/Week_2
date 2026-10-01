from app.providers.base import Generation


class ScriptedProvider:
    """Test double. Scripts are returned in order, then the last script repeats."""

    def __init__(self) -> None:
        self.scripts: list[str] = ["Hello from Helix."]
        self.calls = 0
        self.healthy = True
        self.name = "fake"
        self.model = "fake-model"

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> Generation:
        del messages, temperature, max_tokens
        index = min(self.calls, len(self.scripts) - 1)
        self.calls += 1
        return Generation(
            text=self.scripts[index],
            prompt_tokens=5,
            completion_tokens=3,
            model=self.model,
        )

    async def health(self) -> bool:
        return self.healthy

    async def aclose(self) -> None:
        return None
