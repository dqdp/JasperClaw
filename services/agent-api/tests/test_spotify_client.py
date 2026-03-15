from __future__ import annotations

from app.clients.spotify import SpotifyClient


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "ok"

    def json(self) -> object:
        return self._payload


class _FakeClient:
    requests: list[dict[str, object]] = []
    responses: list[_FakeResponse] = []

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _ = exc_type, exc, tb
        return False

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        **kwargs,
    ) -> _FakeResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "kwargs": kwargs,
            }
        )
        return self.responses.pop(0)


def test_client_credentials_token_uses_spotify_accounts_host(monkeypatch) -> None:
    monkeypatch.setattr("app.clients.spotify.httpx.Client", _FakeClient)
    _FakeClient.requests = []
    _FakeClient.responses = [
        _FakeResponse(
            200,
            {
                "access_token": "fetched-token",
                "expires_in": 3600,
            },
        ),
        _FakeResponse(
            200,
            {
                "tracks": {
                    "items": [
                        {
                            "name": "Calm Piano",
                            "uri": "spotify:track:001",
                            "artists": [{"name": "Piano Studio"}],
                            "album": {"name": "Focus"},
                            "external_urls": {
                                "spotify": "https://open.spotify.com/track/001"
                            },
                        }
                    ]
                }
            },
        ),
    ]

    client = SpotifyClient(
        base_url="https://api.spotify.com",
        access_token="",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="",
        timeout_seconds=5.0,
    )

    results = client.search_tracks(query="lofi", limit=1)

    assert len(results) == 1
    assert _FakeClient.requests[0]["url"] == "https://accounts.spotify.com/api/token"
    assert _FakeClient.requests[1]["url"] == "https://api.spotify.com/v1/search"


def test_list_playlists_uses_me_playlists_endpoint(monkeypatch) -> None:
    monkeypatch.setattr("app.clients.spotify.httpx.Client", _FakeClient)
    _FakeClient.requests = []
    _FakeClient.responses = [
        _FakeResponse(
            200,
            {
                "items": [
                    {
                        "name": "Focus Flow",
                        "uri": "spotify:playlist:001",
                        "owner": {"display_name": "Alex"},
                        "external_urls": {
                            "spotify": "https://open.spotify.com/playlist/001"
                        },
                    }
                ]
            },
        ),
    ]

    client = SpotifyClient(
        base_url="https://api.spotify.com",
        access_token="token",
        client_id="",
        client_secret="",
        redirect_uri="",
        timeout_seconds=5.0,
    )

    results = client.list_playlists(limit=5)

    assert len(results) == 1
    assert results[0].name == "Focus Flow"
    assert results[0].owner == "Alex"
    assert _FakeClient.requests[0]["url"] == "https://api.spotify.com/v1/me/playlists"
    assert _FakeClient.requests[0]["kwargs"]["params"] == {"limit": "5"}
