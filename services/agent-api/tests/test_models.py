def test_models(client, auth_headers) -> None:
    response = client.get("/v1/models", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {"id": "assistant-v1", "object": "model", "owned_by": "local-assistant"},
            {"id": "assistant-fast", "object": "model", "owned_by": "local-assistant"},
        ],
    }
