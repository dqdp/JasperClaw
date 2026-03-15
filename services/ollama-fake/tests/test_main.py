from fastapi.testclient import TestClient

from app.main import app


def test_healthz_and_tags() -> None:
    client = TestClient(app)

    healthz = client.get("/healthz")
    tags = client.get("/api/tags")

    assert healthz.status_code == 200
    assert healthz.json() == {"status": "ok"}
    assert tags.status_code == 200
    assert tags.json()["models"] == [{"name": "qwen2.5:0.5b"}, {"name": "all-minilm"}]


def test_chat_returns_non_empty_assistant_message() -> None:
    client = TestClient(app)
    client.post("/test/reset")

    response = client.post(
        "/api/chat",
        json={
            "model": "qwen2.5:0.5b",
            "messages": [{"role": "user", "content": "Reply with ok."}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"]["role"] == "assistant"
    assert payload["message"]["content"].startswith("ok")
    state = client.get("/test/state").json()
    assert state["chat_requests"] == [
        {
            "model": "qwen2.5:0.5b",
            "messages": [{"role": "user", "content": "Reply with ok."}],
            "stream": False,
        }
    ]


def test_chat_returns_spotify_demo_planning_directive_for_smoke_prompt() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "model": "qwen2.5:0.5b",
            "messages": [
                {"role": "system", "content": "Supported examples: {\"tool\":\"spotify-list-playlists\"}"},
                {"role": "user", "content": "smoke spotify demo playlists"},
            ],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["message"]["content"] == '{"tool":"spotify-list-playlists"}'


def test_chat_returns_spotify_demo_final_answer_for_smoke_prompt() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "model": "qwen2.5:0.5b",
            "messages": [
                {
                    "role": "system",
                    "content": "Available Spotify playlists (demo):\n- Focus Flow",
                },
                {"role": "user", "content": "smoke spotify demo playlists"},
            ],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["message"]["content"]
        == "Focus Flow and Energy Kick are available in demo mode."
    )


def test_embed_returns_one_embedding_per_input() -> None:
    client = TestClient(app)
    client.post("/test/reset")

    response = client.post(
        "/api/embed",
        json={"model": "all-minilm", "input": ["first", "second"]},
    )

    assert response.status_code == 200
    assert response.json() == {"embeddings": [[5.0, 1.0, 0.5], [6.0, 1.0, 0.5]]}
