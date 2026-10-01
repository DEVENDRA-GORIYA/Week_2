from fastapi.testclient import TestClient

from tests.conftest import auth, register


def test_completion_records_provider_usage(client: TestClient) -> None:
    token = register(client)["access_token"]
    client.fake.scripts = ["Helix online."]  # type: ignore[attr-defined]

    response = client.post(
        "/api/v1/completions",
        headers=auth(token),
        json={
            "messages": [{"role": "user", "content": "Say hello"}],
            "prompt_id": "concise_assistant",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["output"] == "Helix online."
    assert body["provider"] == "ollama"
    assert body["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] == 8
    assert response.headers["X-RateLimit-Limit"] == "30"

    usage = client.get("/api/v1/usage/me", headers=auth(token))
    assert usage.status_code == 200
    usage_body = usage.json()
    assert usage_body["day_tokens"] == 8
    assert usage_body["events"][0]["endpoint"] == "completions"
    assert usage_body["events"][0]["created_at"].endswith("Z")


def test_unknown_prompt_is_not_found(client: TestClient) -> None:
    token = register(client)["access_token"]
    response = client.post(
        "/api/v1/completions",
        headers=auth(token),
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "prompt_id": "missing_prompt",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_extract_prompt_cannot_be_used_for_chat(client: TestClient) -> None:
    token = register(client)["access_token"]
    response = client.post(
        "/api/v1/completions",
        headers=auth(token),
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "prompt_id": "sentiment",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "schema_violation"


def test_tool_call_then_final_answer(client: TestClient) -> None:
    token = register(client)["access_token"]
    client.fake.scripts = [  # type: ignore[attr-defined]
        '{"action":"tool","name":"calculator","arguments":{"expression":"2*(3+4)"}}',
        '{"action":"final","content":"The answer is 14."}',
    ]
    response = client.post(
        "/api/v1/completions",
        headers=auth(token),
        json={
            "messages": [{"role": "user", "content": "What is 2*(3+4)?"}],
            "tools_enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["output"] == "The answer is 14."
    assert body["finish_reason"] == "stop"
    assert body["tool_trace"][0]["name"] == "calculator"
    assert '"value": 14' in body["tool_trace"][0]["result"]
    assert client.fake.calls == 2  # type: ignore[attr-defined]


def test_weak_model_prose_is_degraded_not_an_error(client: TestClient) -> None:
    token = register(client)["access_token"]
    client.fake.scripts = ["I think the answer is 14."]  # type: ignore[attr-defined]
    response = client.post(
        "/api/v1/completions",
        headers=auth(token),
        json={
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "tools_enabled": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["finish_reason"] == "degraded"
    assert response.json()["output"] == "I think the answer is 14."


def test_extract_validates_and_retries(client: TestClient) -> None:
    token = register(client)["access_token"]
    client.fake.scripts = [  # type: ignore[attr-defined]
        "not json",
        '{"label":"Negative","confidence":0.8,"rationale":"The customer is upset."}',
    ]
    response = client.post(
        "/api/v1/extract",
        headers=auth(token),
        json={
            "task": "sentiment",
            "text": "This charge is wrong and I am done waiting.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["retries"] == 1
    assert body["result"]["label"] == "negative"
    assert body["result"]["confidence"] == 0.8


def test_extract_failure_still_records_usage(client: TestClient) -> None:
    token = register(client)["access_token"]
    client.fake.scripts = ["nope", "still nope"]  # type: ignore[attr-defined]
    response = client.post(
        "/api/v1/extract",
        headers=auth(token),
        json={"task": "support_ticket", "text": "The app will not load."},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "schema_violation"

    usage = client.get("/api/v1/usage/me", headers=auth(token))
    assert usage.json()["day_tokens"] == 16


def test_prompt_catalog_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/prompts").status_code == 401
    token = register(client)["access_token"]
    response = client.get("/api/v1/prompts", headers=auth(token))
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert {"concise_assistant", "support_ticket", "sentiment", "action_items"} <= ids


def test_rate_limit(limited_client: TestClient) -> None:
    token = register(limited_client)["access_token"]
    payload = {"messages": [{"role": "user", "content": "Hello"}]}
    first = limited_client.post("/api/v1/completions", headers=auth(token), json=payload)
    second = limited_client.post("/api/v1/completions", headers=auth(token), json=payload)
    third = limited_client.post("/api/v1/completions", headers=auth(token), json=payload)
    assert first.status_code == 200
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limited"
    assert third.headers["retry-after"] == "60"


def test_daily_budget(budget_client: TestClient) -> None:
    token = register(budget_client)["access_token"]
    payload = {"messages": [{"role": "user", "content": "Hello"}]}
    first = budget_client.post("/api/v1/completions", headers=auth(token), json=payload)
    second = budget_client.post("/api/v1/completions", headers=auth(token), json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "budget_exceeded"
