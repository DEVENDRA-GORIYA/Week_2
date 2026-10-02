from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-change-me-not-for-production"
ProviderName = Literal["ollama", "groq", "openai_compatible"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Helix Inference Gateway"
    app_version: str = "1.0.0"
    api_v1_prefix: str = "/api/v1"
    debug: bool = True

    secret_key: str = DEV_SECRET
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    admin_emails: str = ""

    database_url: str = "sqlite+aiosqlite:///./helix.db"
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"

    inference_provider: ProviderName = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "smollm2:135m"
    ollama_api_key: str = "ollama"

    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""

    rate_limit_rpm: int = Field(default=30, ge=1, le=600)
    daily_token_budget: int = Field(default=20_000, ge=1)
    max_tool_steps: int = Field(default=3, ge=1, le=8)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def admin_email_set(self) -> set[str]:
        return {email.strip().lower() for email in self.admin_emails.split(",") if email.strip()}

    @field_validator("secret_key")
    @classmethod
    def secret_key_length(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return value

    @model_validator(mode="after")
    def reject_dev_secret_outside_debug(self) -> Self:
        if not self.debug and self.secret_key == DEV_SECRET:
            raise ValueError(
                "Refusing to start with the development SECRET_KEY while DEBUG is false."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
