from fastapi.testclient import TestClient

from tests.conftest import auth, register


def test_health_and_root(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["docs"] == "/docs"
    assert root.headers["X-Request-ID"]

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["service"] == "helix"


def test_ready_reflects_provider(client: TestClient) -> None:
    ready = client.get("/api/v1/ready")
    assert ready.status_code == 200
    assert ready.json()["provider"] == "ollama"

    client.fake.healthy = False  # type: ignore[attr-defined]
    down = client.get("/api/v1/ready")
    assert down.status_code == 503
    assert down.json()["error"]["code"] == "provider_unavailable"


def test_register_login_and_me(client: TestClient) -> None:
    created = register(client, email="Ada@Example.com")
    assert created["user"]["email"] == "ada@example.com"
    assert created["user"]["role"] == "user"
    assert created["token_type"] == "bearer"

    me = client.get("/api/v1/auth/me", headers=auth(created["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == created["user"]["id"]

    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "password123"},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["access_token"]


def test_duplicate_email_and_bad_password(client: TestClient) -> None:
    register(client)
    duplicate = client.post(
        "/api/v1/auth/register",
        json={"email": "ada@example.com", "password": "password123"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"

    bad = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "wrong-password"},
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["message"] == "Invalid email or password."

    missing = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "password123"},
    )
    assert missing.status_code == 401


def test_protected_route_requires_bearer(client: TestClient) -> None:
    response = client.post(
        "/api/v1/completions",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


def test_request_schema_rejects_extra_fields(client: TestClient) -> None:
    token = register(client)["access_token"]
    response = client.post(
        "/api/v1/completions",
        headers=auth(token),
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "unexpected": True,
        },
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"]


def test_password_too_short(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "ada@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_admin_summary_is_role_gated(admin_client: TestClient) -> None:
    admin = register(admin_client, email="admin@example.com")
    user = register(admin_client, email="user@example.com")

    forbidden = admin_client.get("/api/v1/usage/summary", headers=auth(user["access_token"]))
    assert forbidden.status_code == 403

    allowed = admin_client.get("/api/v1/usage/summary", headers=auth(admin["access_token"]))
    assert allowed.status_code == 200
    assert allowed.json()["day_requests"] == 0
