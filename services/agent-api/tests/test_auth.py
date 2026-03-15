from app.core.config import get_settings


def test_v1_routes_require_bearer_token(client) -> None:
    response = client.get("/v1/models")

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert response.json()["error"]["code"] == "missing_api_key"


def test_v1_routes_reject_invalid_bearer_token(client) -> None:
    response = client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_v1_routes_reject_malformed_authorization_header(client) -> None:
    response = client.get("/v1/models", headers={"Authorization": "Token wrong-key"})

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_audio_routes_require_bearer_token(client) -> None:
    response = client.post("/v1/audio/speech", json={"input": "hello", "model": "tts-1"})

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert response.json()["error"]["code"] == "missing_api_key"


def test_capability_discovery_requires_bearer_token(client) -> None:
    response = client.get("/v1/capabilities/discovery")

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert response.json()["error"]["code"] == "missing_api_key"


def test_auth_configuration_error_returns_503(client, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_OPENAI_API_KEY", "")
    get_settings.cache_clear()

    response = client.get("/v1/models", headers={"Authorization": "Bearer test-internal-key"})

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "internal_error"
    assert response.json()["error"]["code"] == "auth_not_configured"


def test_placeholder_auth_configuration_returns_503(client, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_OPENAI_API_KEY", "change-me")
    get_settings.cache_clear()

    response = client.get("/v1/models", headers={"Authorization": "Bearer change-me"})

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "internal_error"
    assert response.json()["error"]["code"] == "auth_not_configured"
