from app.config import ProviderName, Settings, get_settings
from app.core.errors import SchemaViolation
from app.providers.base import InferenceProvider
from app.providers.factory import build_provider
from app.schemas.inference import ProviderOption, ProviderStatus

_KNOWN = {"ollama", "groq", "anthropic", "openai_compatible"}


def list_provider_options(settings: Settings) -> list[ProviderOption]:
    options = [
        ProviderOption(
            name="ollama",
            label="Ollama (local)",
            model=settings.ollama_model,
            configured=True,
        ),
        ProviderOption(
            name="groq",
            label="Groq (free API)",
            model=settings.groq_model,
            configured=bool(settings.groq_api_key.strip()),
        ),
        ProviderOption(
            name="anthropic",
            label="Anthropic (Claude)",
            model=settings.anthropic_model,
            configured=bool(settings.anthropic_credential),
        ),
    ]
    if settings.openai_base_url.strip() and settings.openai_model.strip():
        options.append(
            ProviderOption(
                name="openai_compatible",
                label="OpenAI-compatible",
                model=settings.openai_model,
                configured=True,
            )
        )
    return options


def active_provider_name(app_state: object, settings: Settings) -> ProviderName:
    name = getattr(app_state, "inference_provider", None)
    if name in _KNOWN:
        return name  # type: ignore[return-value]
    return settings.inference_provider


async def switch_runtime_provider(app: object, provider: ProviderName) -> InferenceProvider:
    settings = get_settings()
    options = {item.name: item for item in list_provider_options(settings)}
    choice = options.get(provider)
    if choice is None:
        raise SchemaViolation(f"Provider '{provider}' is not available on this server.")
    if not choice.configured:
        if provider == "groq":
            raise SchemaViolation(
                "Groq is not configured. Set GROQ_API_KEY in backend/.env and restart once."
            )
        if provider == "anthropic":
            raise SchemaViolation(
                "Claude is not configured. Set ANTHROPIC_AUTH_TOKEN (ICA) or "
                "ANTHROPIC_API_KEY in backend/.env, set ANTHROPIC_BASE_URL if needed, "
                "and restart once."
            )
        raise SchemaViolation(f"Provider '{provider}' is not configured.")

    updated = settings.model_copy(update={"inference_provider": provider})
    try:
        new_provider = build_provider(updated)
    except RuntimeError as exc:
        raise SchemaViolation(str(exc)) from exc

    old_provider = app.state.provider
    app.state.provider = new_provider
    app.state.inference_provider = provider
    if old_provider is not None and old_provider is not new_provider:
        await old_provider.aclose()
    return new_provider


async def provider_status(app: object, provider: InferenceProvider) -> ProviderStatus:
    settings = get_settings()
    return ProviderStatus(
        active=active_provider_name(app.state, settings),
        model=provider.model,
        ready=await provider.health(),
        options=list_provider_options(settings),
    )
