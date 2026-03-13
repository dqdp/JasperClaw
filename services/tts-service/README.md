# TTS Service

Purpose:
This service now contains the first real buffered text-to-speech slice for the
voice path.

Start here:
- `app/main.py`: open first for route wiring and app construction.

Index:
- `Dockerfile`: open when changing container build/runtime behavior.
- `pyproject.toml`: open when changing pytest or local project metadata.
- `requirements.txt`: open when changing runtime Python dependencies.
- `app/`: open when changing HTTP contract, config, engine wiring, or voice registry behavior.
- `tests/`: open when changing `/speak`, engine, or probe coverage.

Notes:
- Current baseline:
  - one active local engine per deployment
  - buffered `audio/wav` responses
  - service-local `healthz` and `readyz` probes
  - Prometheus-compatible `/metrics` export for request, synthesis, and readiness signals
  - Piper-compatible default profile
  - XTTS remains a later premium GPU profile
- Docker builds preload the Piper models referenced by `app/voices.toml` so the
  default profile does not require runtime downloads.
