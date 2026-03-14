# STT Service

Purpose:
This service owns the internal speech-to-text runtime behind the `agent-api`
voice ingress.

Start here:
- `app/main.py`: open first for the current HTTP contract.

Index:
- `Dockerfile`: open when changing container build/runtime behavior.
- `pyproject.toml`: open when changing pytest or local project metadata.
- `requirements.txt`: open when changing runtime Python dependencies.
- `app/`: open when changing the FastAPI service, engine boundary, or settings.
- `tests/`: open when changing the transcription contract or liveness coverage.

Current baseline:
- `POST /transcribe`
- `GET /healthz`
- `GET /readyz`
- `GET /metrics`
- supported deployment profiles are `text-only` and `voice-enabled-cpu`
- the current recommended voice-enabled profile is CPU-backed `faster-whisper`
  with startup prewarm enabled
