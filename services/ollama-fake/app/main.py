from __future__ import annotations

import json
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict


DEFAULT_MODELS = ("qwen2.5:0.5b", "all-minilm")


@dataclass(slots=True)
class FakeOllamaState:
    chat_requests: list[dict[str, Any]] = field(default_factory=list)
    embed_requests: list[dict[str, Any]] = field(default_factory=list)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[ChatMessage]
    stream: bool = False


class EmbedRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    input: str | list[str]


app = FastAPI(title="ollama-fake", version="0.1.0")
_state = FakeOllamaState()
_lock = Lock()


def _model_entries() -> list[dict[str, str]]:
    return [{"name": name} for name in DEFAULT_MODELS]


def _response_text(messages: list[ChatMessage]) -> str:
    user_messages = [message.content.strip() for message in messages if message.role == "user"]
    if not user_messages:
        return "ok"
    last_message = user_messages[-1]
    return f"ok: {last_message}" if last_message else "ok"


def _snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "chat_requests": list(_state.chat_requests),
            "embed_requests": list(_state.embed_requests),
        }


def _chat_payload(content: str) -> dict[str, Any]:
    return {
        "model": "ollama-fake",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "prompt_eval_count": 3,
        "eval_count": 2,
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tags")
def tags() -> dict[str, Any]:
    return {"models": _model_entries()}


@app.post("/api/chat", response_model=None)
def chat(request: ChatRequest) -> Response:
    content = _response_text(request.messages)
    payload = _chat_payload(content)
    with _lock:
        _state.chat_requests.append(request.model_dump())

    if request.stream:
        stream_chunks = [
            json.dumps(
                {
                    "model": "ollama-fake",
                    "message": {"role": "assistant", "content": "ok"},
                    "done": False,
                }
            )
            + "\n",
            json.dumps(payload) + "\n",
        ]
        return StreamingResponse(iter(stream_chunks), media_type="application/x-ndjson")

    return JSONResponse(payload)


@app.post("/api/embed")
def embed(request: EmbedRequest) -> dict[str, Any]:
    with _lock:
        _state.embed_requests.append(request.model_dump())

    inputs = request.input if isinstance(request.input, list) else [request.input]
    embeddings = [[float(len(text)), 1.0, 0.5] for text in inputs]
    return {"embeddings": embeddings}


@app.get("/test/state")
def test_state() -> dict[str, Any]:
    return _snapshot()


@app.post("/test/reset")
def test_reset() -> dict[str, str]:
    with _lock:
        _state.chat_requests.clear()
        _state.embed_requests.clear()
    return {"status": "ok"}
