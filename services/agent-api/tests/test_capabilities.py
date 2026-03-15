from app.modules.chat.capabilities import (
    CapabilityDiscoveryEntry,
    build_capability_discovery_snapshot,
)


def test_build_capability_discovery_snapshot_discloses_mixed_states() -> None:
    snapshot = build_capability_discovery_snapshot(
        capabilities=(
            CapabilityDiscoveryEntry(
                id="voice",
                label="Voice conversation",
                state="real",
            ),
            CapabilityDiscoveryEntry(
                id="spotify_playback",
                label="Spotify playback",
                state="demo",
            ),
            CapabilityDiscoveryEntry(
                id="telegram_send",
                label="Telegram send",
                state="unconfigured",
            ),
        ),
        commands=("/help", "/status", "/ask <message>"),
    )

    assert "Voice conversation: connected" in snapshot.status_text
    assert "Spotify playback: demo" in snapshot.status_text
    assert "Telegram send: not configured" in snapshot.status_text
    assert "/help" in snapshot.help_text
    assert "spotify-search" not in snapshot.help_text
    assert "SPOTIFY_ACCESS_TOKEN" not in snapshot.help_text


def test_capability_discovery_endpoint_returns_user_facing_surface(
    client,
    auth_headers,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "spotify-token")

    response = client.get("/v1/capabilities/discovery", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "capabilities": [
            {
                "id": "voice",
                "label": "Voice conversation",
                "state": "real",
            },
            {
                "id": "spotify_playback",
                "label": "Spotify playback",
                "state": "real",
            },
            {
                "id": "spotify_station",
                "label": "Spotify station",
                "state": "unconfigured",
            },
            {
                "id": "telegram_send",
                "label": "Telegram send",
                "state": "unconfigured",
            },
        ],
        "commands": ["/help", "/status", "/ask <message>"],
        "help_text": (
            "I can answer questions, talk by voice when enabled, help with Spotify "
            "playback, and send Telegram messages to configured aliases.\n"
            "Current state: Voice conversation is connected; Spotify playback is "
            "connected; Spotify station is not configured; Telegram send is not "
            "configured.\n"
            "Commands: /help, /status, /ask <message>"
        ),
        "status_text": (
            "Voice conversation: connected\n"
            "Spotify playback: connected\n"
            "Spotify station: not configured\n"
            "Telegram send: not configured"
        ),
    }
