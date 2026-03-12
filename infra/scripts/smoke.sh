#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE="${ROOT_ENV_FILE:-.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-infra/compose/compose.yml}"
COMPOSE_OVERRIDE_FILE="${COMPOSE_OVERRIDE_FILE:-infra/compose/compose.prod.yml}"
APP_SERVICE_NAME="${APP_SERVICE_NAME:-agent-api}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_ENV_FILE"
  set +a
fi

compose() {
  local -a cmd=(docker compose --env-file "$ROOT_ENV_FILE" -f "$COMPOSE_BASE_FILE")
  if [[ -n "$COMPOSE_OVERRIDE_FILE" ]]; then
    cmd+=(-f "$COMPOSE_OVERRIDE_FILE")
  fi
  cmd+=("$@")
  "${cmd[@]}"
}

if [[ -n "${DOMAIN:-}" ]]; then
  curl -fsS -o /dev/null -H "Host: ${DOMAIN}" http://127.0.0.1/
fi

compose exec -T -e SMOKE_TIMEOUT_SECONDS="$WAIT_TIMEOUT_SECONDS" "$APP_SERVICE_NAME" python - <<'PY'
import json
import os
import time
import urllib.error
import urllib.request


def request_json(url: str, *, headers: dict[str, str] | None = None, body: dict | None = None) -> tuple[int, dict]:
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


base_url = "http://127.0.0.1:8080"
api_key = os.getenv("INTERNAL_OPENAI_API_KEY", "").strip()
if not api_key:
    raise SystemExit("INTERNAL_OPENAI_API_KEY missing in agent-api container")

deadline = time.monotonic() + float(os.getenv("SMOKE_TIMEOUT_SECONDS", "180"))
while True:
    try:
        status, payload = request_json(f"{base_url}/readyz")
    except urllib.error.URLError as exc:
        status, payload = 0, {"error": str(exc.reason)}
    if status == 200 and payload.get("status") == "ready":
        break
    if time.monotonic() >= deadline:
        raise SystemExit(f"/readyz did not become ready before timeout: {status} {payload}")
    time.sleep(2)

auth_headers = {"Authorization": f"Bearer {api_key}"}
status, payload = request_json(f"{base_url}/v1/models", headers=auth_headers)
if status != 200:
    raise SystemExit(f"/v1/models failed: {status} {payload}")

model_ids = {entry.get("id") for entry in payload.get("data", []) if isinstance(entry, dict)}
required_models = {"assistant-v1", "assistant-fast"}
if not required_models.issubset(model_ids):
    raise SystemExit(f"Required public model IDs missing from model list: {sorted(model_ids)}")

status, payload = request_json(
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
PY

if [[ -n "${TELEGRAM_SMOKE_BASE_URL:-}" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  "${PYTHON_BIN}" infra/scripts/smoke-telegram-ingress.py
fi
