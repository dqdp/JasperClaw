#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _is_truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _resolve_api_key() -> str:
    value = (
        os.getenv("SMOKE_INTERNAL_OPENAI_API_KEY", "").strip()
        or os.getenv("INTERNAL_OPENAI_API_KEY", "").strip()
    )
    if not value:
        raise SystemExit(
            "Missing required environment variable: SMOKE_INTERNAL_OPENAI_API_KEY"
        )
    return value


def _request_json(
    url: str, *, headers: dict[str, str] | None = None, body: dict | None = None
) -> tuple[int, dict]:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, headers=request_headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode()
            return response.status, json.loads(payload)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode()
        try:
            body_json = json.loads(payload)
        except json.JSONDecodeError:
            body_json = {"raw": payload}
        return exc.code, body_json


def _request_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict | None = None,
) -> tuple[int, bytes, str]:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, headers=request_headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return (
                response.status,
                response.read(),
                response.headers.get("Content-Type", ""),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


def _wait_for_success(
    *,
    request_fn,
    success_predicate,
    timeout_seconds: float,
    error_context: str,
) -> tuple[int, dict]:
    deadline = time.monotonic() + timeout_seconds
    last_result: tuple[int, dict] = (0, {"error": "not started"})

    while True:
        try:
            last_result = request_fn()
        except (urllib.error.URLError, OSError) as exc:
            last_result = (0, {"error": str(getattr(exc, "reason", exc))})

        status, payload = last_result
        if success_predicate(status, payload):
            return last_result
        if time.monotonic() >= deadline:
            raise SystemExit(f"{error_context}: {status} {payload}")
        time.sleep(2)


def main() -> int:
    base_url = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:18080").rstrip("/")
    api_key = _resolve_api_key()
    timeout_seconds = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "120"))
    deadline = time.monotonic() + timeout_seconds

    while True:
        try:
            status, payload = _request_json(f"{base_url}/readyz")
        except (urllib.error.URLError, OSError) as exc:
            status, payload = 0, {"error": str(getattr(exc, "reason", exc))}
        if status == 200 and payload.get("status") == "ready":
            break
        if time.monotonic() >= deadline:
            raise SystemExit(
                f"/readyz did not become ready before timeout: {status} {payload}"
            )
        time.sleep(2)

    auth_headers = {"Authorization": f"Bearer {api_key}"}
    status, payload = _wait_for_success(
        request_fn=lambda: _request_json(f"{base_url}/v1/models", headers=auth_headers),
        success_predicate=lambda status, payload: status == 200,
        timeout_seconds=30.0,
        error_context="/v1/models did not stabilize before timeout",
    )

    model_ids = {
        entry.get("id") for entry in payload.get("data", []) if isinstance(entry, dict)
    }
    required_models = {"assistant-v1", "assistant-fast"}
    if not required_models.issubset(model_ids):
        raise SystemExit(
            f"Required public model IDs missing from model list: {sorted(model_ids)}"
        )

    status, payload = _wait_for_success(
        request_fn=lambda: _request_json(
            f"{base_url}/v1/chat/completions",
            headers=auth_headers,
            body={
                "model": "assistant-fast",
                "messages": [{"role": "user", "content": "Reply with ok."}],
            },
        ),
        success_predicate=lambda status, payload: status == 200,
        timeout_seconds=45.0,
        error_context="/v1/chat/completions did not stabilize before timeout",
    )

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SystemExit(f"Chat response missing choices: {payload}")

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content", "").strip() if isinstance(message, dict) else ""
    if not content:
        raise SystemExit(f"Chat response content was empty: {payload}")

    if _is_truthy_env("SMOKE_CHECK_VOICE"):
        status, body, content_type = _request_bytes(
            f"{base_url}/v1/audio/speech",
            headers=auth_headers,
            body={
                "model": "tts-1",
                "input": "Скажи привет.",
                "voice": os.getenv("SMOKE_TTS_VOICE", "assistant-default"),
            },
        )
        if status != 200:
            try:
                payload = json.loads(body.decode())
            except Exception:
                payload = {"raw": body.decode(errors="ignore")}
            raise SystemExit(f"/v1/audio/speech failed: {status} {payload}")
        if not content_type.startswith("audio/wav"):
            raise SystemExit(
                f"/v1/audio/speech returned unexpected content type: {content_type}"
            )
        if len(body) < 16 or not body.startswith(b"RIFF"):
            raise SystemExit("/v1/audio/speech did not return RIFF/WAV audio")

    print("Smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
