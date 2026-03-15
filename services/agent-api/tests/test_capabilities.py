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
                "state": "unconfigured",
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
            "not configured; Spotify station is not configured; Telegram send is not "
            "configured.\n"
            "Commands: /help, /status, /ask <message>"
        ),
        "status_text": (
            "Voice conversation: connected\n"
            "Spotify playback: not configured\n"
            "Spotify station: not configured\n"
            "Telegram send: not configured"
        ),
    }


def test_capability_discovery_endpoint_requires_refresh_capable_spotify_bootstrap_for_real(
    client,
    auth_headers,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "spotify-client")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "spotify-secret")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://assistant.test/callback")
    monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "spotify-refresh")

    response = client.get("/v1/capabilities/discovery", headers=auth_headers)

    assert response.status_code == 200
    spotify_playback = next(
        capability
        for capability in response.json()["capabilities"]
        if capability["id"] == "spotify_playback"
    )
    spotify_station = next(
        capability
        for capability in response.json()["capabilities"]
        if capability["id"] == "spotify_station"
    )
    assert spotify_playback["state"] == "real"
    assert spotify_station["state"] == "real"
    assert "Spotify playback is connected" in response.json()["help_text"]
    assert "Spotify station is connected" in response.json()["help_text"]


def test_capability_discovery_endpoint_marks_spotify_demo_when_demo_enabled(
    client,
    auth_headers,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_DEMO_ENABLED", "true")

    response = client.get("/v1/capabilities/discovery", headers=auth_headers)

    assert response.status_code == 200
    spotify_playback = next(
        capability
        for capability in response.json()["capabilities"]
        if capability["id"] == "spotify_playback"
    )
    spotify_station = next(
        capability
        for capability in response.json()["capabilities"]
        if capability["id"] == "spotify_station"
    )
    assert spotify_playback["state"] == "demo"
    assert spotify_station["state"] == "demo"
    assert "Spotify playback is demo" in response.json()["help_text"]
    assert "Spotify station is demo" in response.json()["help_text"]


def test_capability_discovery_endpoint_marks_telegram_send_demo_when_demo_household_exists(
    client,
    auth_headers,
    monkeypatch,
    tmp_path,
) -> None:
    demo_path = tmp_path / "household.demo.toml"
    demo_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.demo_home]
chat_id = 111111111
description = "Demo household alias"
""".strip()
    )
    monkeypatch.setenv("DEMO_HOUSEHOLD_CONFIG_PATH", str(demo_path))

    response = client.get("/v1/capabilities/discovery", headers=auth_headers)

    assert response.status_code == 200
    telegram_send = next(
        capability
        for capability in response.json()["capabilities"]
        if capability["id"] == "telegram_send"
    )
    assert telegram_send["state"] == "demo"
    assert "Telegram send is demo" in response.json()["help_text"]
    assert response.json()["commands"] == [
        "/help",
        "/status",
        "/ask <message>",
        "/aliases",
        "/send <alias> <message>",
    ]


def test_capability_discovery_endpoint_prefers_real_household_over_demo(
    client,
    auth_headers,
    monkeypatch,
    tmp_path,
) -> None:
    real_path = tmp_path / "household.toml"
    demo_path = tmp_path / "household.demo.toml"
    real_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Real household alias"
""".strip()
    )
    demo_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.demo_home]
chat_id = 222222222
description = "Demo household alias"
""".strip()
    )
    monkeypatch.setenv("HOUSEHOLD_CONFIG_PATH", str(real_path))
    monkeypatch.setenv("DEMO_HOUSEHOLD_CONFIG_PATH", str(demo_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-bot-token")

    response = client.get("/v1/capabilities/discovery", headers=auth_headers)

    assert response.status_code == 200
    telegram_send = next(
        capability
        for capability in response.json()["capabilities"]
        if capability["id"] == "telegram_send"
    )
    assert telegram_send["state"] == "real"
    assert "Telegram send is connected" in response.json()["help_text"]
    assert response.json()["commands"] == [
        "/help",
        "/status",
        "/ask <message>",
        "/aliases",
        "/send <alias> <message>",
    ]


def test_capability_discovery_keeps_aliases_but_hides_send_without_bot_token(
    client,
    auth_headers,
    monkeypatch,
    tmp_path,
) -> None:
    real_path = tmp_path / "household.toml"
    real_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Real household alias"
""".strip()
    )
    monkeypatch.setenv("HOUSEHOLD_CONFIG_PATH", str(real_path))

    response = client.get("/v1/capabilities/discovery", headers=auth_headers)

    assert response.status_code == 200
    telegram_send = next(
        capability
        for capability in response.json()["capabilities"]
        if capability["id"] == "telegram_send"
    )
    assert telegram_send["state"] == "unconfigured"
    assert response.json()["commands"] == [
        "/help",
        "/status",
        "/ask <message>",
        "/aliases",
    ]
