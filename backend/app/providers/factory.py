from app.config import Settings
from app.providers.anthropic import AnthropicProvider
from app.providers.base import InferenceProvider
from app.providers.openai_compatible import OpenAICompatibleProvider


def build_provider(settings: Settings) -> InferenceProvider:
    if settings.inference_provider == "ollama":
        base = settings.ollama_base_url.rstrip("/")
        url = base if base.endswith("/v1") else f"{base}/v1"
        return OpenAICompatibleProvider(
            name="ollama",
            base_url=url,
            api_key=settings.ollama_api_key or "ollama",
            model=settings.ollama_model,
            unreachable_hint=(
                f"Ollama is not reachable at {settings.ollama_base_url}. "
                f"Start it and run `ollama pull {settings.ollama_model}`."
            ),
        )

    if settings.inference_provider == "groq":
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is required when INFERENCE_PROVIDER=groq.")
        return OpenAICompatibleProvider(
            name="groq",
            base_url=settings.groq_base_url.rstrip("/"),
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            unreachable_hint="Could not reach the Groq API. Check the network and GROQ_API_KEY.",
        )

    if settings.inference_provider == "anthropic":
        credential = settings.anthropic_credential
        if not credential:
            raise RuntimeError(
                "ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY is required when "
                "INFERENCE_PROVIDER=anthropic."
            )
        return AnthropicProvider(
            api_key=credential,
            model=settings.anthropic_model,
            base_url=settings.anthropic_base_url,
            api_version=settings.anthropic_api_version,
        )

    if not settings.openai_base_url or not settings.openai_model:
        raise RuntimeError(
            "OPENAI_BASE_URL and OPENAI_MODEL are required when "
            "INFERENCE_PROVIDER=openai_compatible."
        )
    return OpenAICompatibleProvider(
        name="openai_compatible",
        base_url=settings.openai_base_url.rstrip("/"),
        api_key=settings.openai_api_key or "not-needed",
        model=settings.openai_model,
        unreachable_hint=f"Could not reach the model server at {settings.openai_base_url}.",
    )
