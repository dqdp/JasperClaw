# Telegram Ingress Services

Purpose:
This directory contains the bridge logic that normalizes Telegram updates and relays responses.

Start here:
- `bridge.py`: open first for update parsing, rate limiting, command routing, and downstream completion flow.

Index:
- `bridge.py`: open when changing Telegram message normalization, dedupe/rate limits, command behavior, or reply sending.
