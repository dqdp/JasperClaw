# TTS Service App

Purpose:
This directory contains the first real implementation of the internal
text-to-speech service.

Start here:
- `main.py`: open when changing route wiring or app construction.

Index:
- `main.py`: open when changing `/speak`, `healthz`, `readyz`, or `/metrics` route wiring.
- `core/`: open when changing config, service-local error envelopes, logging, or metrics.
- `engines/`: open when changing `TtsEngine` adapters or the Piper-compatible runtime.
- `services/`: open when changing synthesis orchestration, readiness checks, or concurrency limits.
- `voice_registry.py`: open when changing static voice resolution behavior.
- `voices.toml`: open when changing bundled default voice mappings.
