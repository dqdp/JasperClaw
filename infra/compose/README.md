# Compose

Purpose:
This directory defines the container topology for local, CI, and production-like runs.

Start here:
- `compose.yml`: open first for the canonical base topology.

Index:
- `compose.yml`: open when changing the shared service graph or default wiring.
- `compose.ci.yml`: open when adjusting CI-only overrides or smoke-test topology.
- `compose.prod.yml`: open when changing production-facing overrides without altering the base graph.
