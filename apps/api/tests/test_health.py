from app.config import Settings


def test_health_returns_only_status(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_leak_connection_info(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    secret = "sb_secret_should_never_appear"
    configured = Settings(
        _env_file=None,
        supabase_url="http://127.0.0.1:54321",
        supabase_secret_key=secret,
        gemini_api_key="gemini-secret",
    )
    response = TestClient(create_app(configured)).get("/api/v1/health")
    assert response.status_code == 200
    body = response.text
    for leaked in (secret, "gemini-secret", "127.0.0.1", "54321"):
        assert leaked not in body
    assert not any(secret in value for value in response.headers.values())


def test_health_rejects_unknown_query(client):
    response = client.get("/api/v1/health?debug=1")
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "validation_error", "message": "The request is invalid."}}


def test_unprefixed_path_is_not_served(client):
    response = client.get("/health")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
