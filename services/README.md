# Services

Purpose:
This directory contains runtime services and service placeholders that make up the v1 stack.

Start here:
- `agent-api/`: open first for the canonical control-plane implementation.

Index:
- `agent-api/`: open when changing the canonical backend ingress, orchestration, persistence, or tools path.
- `ollama-fake/`: open when CI smoke or local runtime verification needs a deterministic fake model runtime.
- `telegram-fake/`: open when changing the test-only fake Telegram Bot API used by smoke validation.
- `telegram-ingress/`: open when changing Telegram webhook/polling ingress or alert relay behavior.
- `stt-service/`: open when touching the deferred speech-to-text placeholder or future voice work.
- `tts-service/`: open when touching the deferred text-to-speech placeholder or future voice work.
- `tools-gateway/`: open only when auditing legacy scaffold material; it is not a canonical v1 runtime path.
