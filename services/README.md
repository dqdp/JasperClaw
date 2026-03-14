# Services

Purpose:
This directory contains the runtime services that make up the v1 stack, plus
the legacy `tools-gateway` scaffold that is no longer on the canonical path.

Start here:
- `agent-api/`: open first for the canonical control-plane implementation.

Index:
- `agent-api/`: open when changing the canonical backend ingress, orchestration, persistence, or tools path.
- `ollama-fake/`: open when CI smoke or local runtime verification needs a deterministic fake model runtime.
- `telegram-fake/`: open when changing the test-only fake Telegram Bot API used by smoke validation.
- `telegram-ingress/`: open when changing Telegram webhook/polling ingress or alert relay behavior.
- `stt-service/`: open when changing the buffered speech-to-text runtime, readiness, or metrics path.
- `tts-service/`: open when changing the buffered Piper-compatible text-to-speech runtime, voice registry, or observability path.
- `tools-gateway/`: open only when auditing legacy scaffold material; it is not a canonical v1 runtime path.
