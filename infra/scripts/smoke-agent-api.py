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


def _request_json(url: str, *, headers: dict[str, str] | None = None, body: dict | None = None) -> tuple[int, dict]:
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


def main() -> int:
    base_url = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:18080").rstrip("/")
    api_key = _require_env("SMOKE_INTERNAL_OPENAI_API_KEY")
    timeout_seconds = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "120"))
    deadline = time.monotonic() + timeout_seconds

    while True:
        try:
            status, payload = _request_json(f"{base_url}/readyz")
        except urllib.error.URLError as exc:
            status, payload = 0, {"error": str(exc.reason)}
        if status == 200 and payload.get("status") == "ready":
            break
        if time.monotonic() >= deadline:
            raise SystemExit(f"/readyz did not become ready before timeout: {status} {payload}")
        time.sleep(2)

    auth_headers = {"Authorization": f"Bearer {api_key}"}
    status, payload = _request_json(f"{base_url}/v1/models", headers=auth_headers)
    if status != 200:
        raise SystemExit(f"/v1/models failed: {status} {payload}")

    model_ids = {entry.get("id") for entry in payload.get("data", []) if isinstance(entry, dict)}
    if "assistant-fast" not in model_ids:
        raise SystemExit(f"assistant-fast missing from model list: {sorted(model_ids)}")

    status, payload = _request_json(
        f"{base_url}/v1/chat/completions",
        headers=auth_headers,
        body={
            "model": "assistant-fast",
            "messages": [{"role": "user", "content": "Reply with ok."}],
        },
    )
    if status != 200:
        raise SystemExit(f"/v1/chat/completions failed: {status} {payload}")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SystemExit(f"Chat response missing choices: {payload}")

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content", "").strip() if isinstance(message, dict) else ""
    if not content:
        raise SystemExit(f"Chat response content was empty: {payload}")

    print("Smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
