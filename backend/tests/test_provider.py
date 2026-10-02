from fastapi.testclient import TestClient

from tests.conftest import auth, open_client, register


def test_provider_status_and_switch(tmp_path, monkeypatch) -> None:
    with open_client(
        tmp_path,
        monkeypatch,
        GROQ_API_KEY="test-groq-key",
        GROQ_MODEL="qwen/qwen3.8-27b",
        OLLAMA_MODEL="smollm2:135m",
        INFERENCE_PROVIDER="ollama",
    ) as (client, fake):
        token = register(client)["access_token"]
        status = client.get("/api/v1/provider", headers=auth(token))
        assert status.status_code == 200, status.text
        body = status.json()
        assert body["active"] == "ollama"
        names = {item["name"] for item in body["options"]}
        assert {"ollama", "groq"} <= names
        assert "anthropic" not in names

        switched = client.put(
            "/api/v1/provider",
            headers=auth(token),
            json={"provider": "groq"},
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["active"] == "groq"
        assert switched.json()["model"] == "qwen/qwen3.8-27b"
        assert fake.name == "groq"

        ollama = client.put(
            "/api/v1/provider",
            headers=auth(token),
            json={"provider": "ollama"},
        )
        assert ollama.status_code == 200
        assert ollama.json()["active"] == "ollama"


def test_groq_switch_requires_key(client: TestClient) -> None:
    token = register(client)["access_token"]
    response = client.put(
        "/api/v1/provider",
        headers=auth(token),
        json={"provider": "groq"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "schema_violation"


def test_anthropic_provider_rejected(client: TestClient) -> None:
    token = register(client)["access_token"]
    response = client.put(
        "/api/v1/provider",
        headers=auth(token),
        json={"provider": "anthropic"},
    )
    assert response.status_code == 422
