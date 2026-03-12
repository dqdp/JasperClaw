# Telegram Ingress Services

Purpose:
This directory contains the bridge logic that normalizes Telegram updates and the durable alert-delivery workflow.

Start here:
- `bridge.py`: open first for update parsing, rate limiting, command routing, and downstream completion flow.

Index:
- `alert_delivery.py`: open when changing durable alert enqueueing, retry/dedupe semantics, or outbox persistence boundaries.
- `bridge.py`: open when changing Telegram message normalization, dedupe/rate limits, command behavior, or reply sending.
