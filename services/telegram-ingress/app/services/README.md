# Telegram Ingress Services

Purpose:
This directory contains the bridge logic that normalizes Telegram updates and the durable alert-delivery workflow.

Current alert-delivery guarantee:
- operational Telegram fanout is `at-least-once` per target chat; immediate per-target persistence narrows duplicate windows after partial success, but crash boundaries can still duplicate the in-flight target.
- lifecycle observability is log-based via `telegram_ingress` structured events such as `telegram_alert_delivery_claimed`, `telegram_alert_delivery_target_attempt_recorded`, `telegram_alert_delivery_finalized`, and `telegram_alert_delivery_finalize_failed`.

Start here:
- `bridge.py`: open first for update parsing, rate limiting, command routing, and downstream completion flow.

Index:
- `alert_delivery.py`: open when changing durable alert enqueueing, retry/dedupe semantics, or outbox persistence boundaries.
- `bridge.py`: open when changing Telegram message normalization, dedupe/rate limits, command behavior, or reply sending.
