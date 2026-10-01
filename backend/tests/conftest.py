import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import reset_db
from app.main import app
from tests.fakes import ScriptedProvider


@contextmanager
def open_client(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    **env: str,
) -> Iterator[tuple[TestClient, ScriptedProvider]]:
    database_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-with-32-bytes-ok")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("INFERENCE_PROVIDER", "ollama")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setenv("OLLAMA_MODEL", "smollm2:135m")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    asyncio.run(reset_db())
    fake = ScriptedProvider()

    def _build(settings):  # noqa: ANN001
        fake.name = settings.inference_provider
        if settings.inference_provider == "ollama":
            fake.model = settings.ollama_model
        elif settings.inference_provider == "groq":
            fake.model = settings.groq_model
        elif settings.inference_provider == "anthropic":
            fake.model = settings.anthropic_model
        else:
            fake.model = settings.openai_model or "compat-model"
        return fake

    monkeypatch.setattr("app.main.build_provider", _build)
    monkeypatch.setattr("app.services.provider_service.build_provider", _build)
    with TestClient(app) as client:
        yield client, fake
    asyncio.run(reset_db())
    get_settings.cache_clear()


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with open_client(tmp_path, monkeypatch) as (test_client, fake):
        test_client.fake = fake  # type: ignore[attr-defined]
        yield test_client


@pytest.fixture
def limited_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with open_client(tmp_path, monkeypatch, RATE_LIMIT_RPM="2") as (test_client, fake):
        test_client.fake = fake  # type: ignore[attr-defined]
        yield test_client


@pytest.fixture
def budget_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with open_client(tmp_path, monkeypatch, DAILY_TOKEN_BUDGET="8") as (test_client, fake):
        test_client.fake = fake  # type: ignore[attr-defined]
        yield test_client


@pytest.fixture
def admin_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with open_client(tmp_path, monkeypatch, ADMIN_EMAILS="admin@example.com") as (
        test_client,
        fake,
    ):
        test_client.fake = fake  # type: ignore[attr-defined]
        yield test_client


def register(
    client: TestClient,
    email: str = "ada@example.com",
    password: str = "password123",
) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
