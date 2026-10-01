import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.errors import ProviderError
from app.providers.anthropic import AnthropicProvider, _split_system
from tests.conftest import auth, open_client, register


def test_provider_status_and_switch(tmp_path, monkeypatch) -> None:
    with open_client(
        tmp_path,
        monkeypatch,
        GROQ_API_KEY="test-groq-key",
        ANTHROPIC_API_KEY="test-anthropic-key",
        ANTHROPIC_AUTH_TOKEN="",
        GROQ_MODEL="qwen/qwen3.8-27b",
        ANTHROPIC_MODEL="claude-haiku-4-5",
        OLLAMA_MODEL="smollm2:135m",
        INFERENCE_PROVIDER="ollama",
    ) as (client, fake):
        token = register(client)["access_token"]
        status = client.get("/api/v1/provider", headers=auth(token))
        assert status.status_code == 200, status.text
        body = status.json()
        assert body["active"] == "ollama"
        names = {item["name"] for item in body["options"]}
        assert {"ollama", "groq", "anthropic"} <= names
        anthropic = next(item for item in body["options"] if item["name"] == "anthropic")
        assert anthropic["configured"] is True

        switched = client.put(
            "/api/v1/provider",
            headers=auth(token),
            json={"provider": "anthropic"},
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["active"] == "anthropic"
        assert switched.json()["model"] == "claude-haiku-4-5"
        assert fake.name == "anthropic"

        groq = client.put(
            "/api/v1/provider",
            headers=auth(token),
            json={"provider": "groq"},
        )
        assert groq.status_code == 200
        assert groq.json()["active"] == "groq"


def test_groq_switch_requires_key(client: TestClient) -> None:
    token = register(client)["access_token"]
    response = client.put(
        "/api/v1/provider",
        headers=auth(token),
        json={"provider": "groq"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "schema_violation"


def test_anthropic_switch_requires_key(client: TestClient) -> None:
    token = register(client)["access_token"]
    response = client.put(
        "/api/v1/provider",
        headers=auth(token),
        json={"provider": "anthropic"},
    )
    assert response.status_code == 422
    assert "Claude is not configured" in response.json()["error"]["message"]


def test_anthropic_ica_bearer_headers() -> None:
    from app.providers.anthropic import _auth_headers

    public = _auth_headers(
        api_key="sk-ant-test",
        base_url="https://api.anthropic.com",
        api_version="2023-06-01",
    )
    assert public["x-api-key"] == "sk-ant-test"
    assert "Authorization" not in public

    ica = _auth_headers(
        api_key="sk-ica-test",
        base_url="https://api.servicesessentials.ibm.com",
        api_version="2023-06-01",
    )
    assert ica["Authorization"] == "Bearer sk-ica-test"

    nextgen = _auth_headers(
        api_key="sk-ica-test",
        base_url="https://api.nextgen-beta.ica.ibm.com/ica",
        api_version="2023-06-01",
    )
    assert nextgen["Authorization"] == "Bearer sk-ica-test"


def test_split_system_for_anthropic() -> None:
    system, chat = _split_system(
        [
            {"role": "system", "content": "Be brief."},
            {"role": "system", "content": "No fluff."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "What is Terraform?"},
        ]
    )
    assert system == "Be brief.\n\nNo fluff."
    assert chat[0]["role"] == "user"
    assert chat[-1]["content"] == "What is Terraform?"


def test_anthropic_chat_maps_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5")

    class FakeResponse:
        is_success = True

        def json(self) -> dict:
            return {
                "model": "claude-haiku-4-5",
                "content": [{"type": "text", "text": "Terraform is IaC."}],
                "usage": {"input_tokens": 12, "output_tokens": 8},
            }

    async def fake_post(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return FakeResponse()

    monkeypatch.setattr(provider._client, "post", fake_post)

    async def run() -> None:
        generation = await provider.chat(
            [{"role": "user", "content": "What is Terraform?"}],
            temperature=0.2,
            max_tokens=64,
        )
        assert generation.text == "Terraform is IaC."
        assert generation.prompt_tokens == 12
        assert generation.completion_tokens == 8
        await provider.aclose()

    asyncio.run(run())


def test_anthropic_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5")

    class FakeResponse:
        is_success = False
        status_code = 401

        def json(self) -> dict:
            return {"error": {"message": "invalid x-api-key"}}

    async def fake_post(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return FakeResponse()

    monkeypatch.setattr(provider._client, "post", fake_post)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await provider.chat(
                [{"role": "user", "content": "Hi"}],
                temperature=0.2,
                max_tokens=16,
            )
        assert "invalid x-api-key" in exc.value.message
        await provider.aclose()

    asyncio.run(run())


def test_anthropic_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5")

    async def boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(provider._client, "post", boom)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await provider.chat(
                [{"role": "user", "content": "Hi"}],
                temperature=0.2,
                max_tokens=16,
            )
        assert exc.value.status_code == 504
        await provider.aclose()

    asyncio.run(run())
