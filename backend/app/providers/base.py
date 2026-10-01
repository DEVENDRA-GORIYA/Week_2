from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Generation:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    model: str


class InferenceProvider(Protocol):
    name: str
    model: str

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> Generation: ...

    async def health(self) -> bool: ...

    async def aclose(self) -> None: ...
