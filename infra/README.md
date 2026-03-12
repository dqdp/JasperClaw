# Infra

Purpose:
This directory contains deployable infrastructure artifacts: reverse proxy config, Compose topology, env templates, and helper scripts.

Start here:
- `compose/`: open first when changing service topology or runtime wiring.

Index:
- `caddy/`: open when changing public ingress, TLS, or reverse-proxy routes.
- `compose/`: open when changing container topology, service wiring, or deployment overrides.
- `env/`: open when changing example env files or smoke/deploy configuration inputs.
- `scripts/`: open when changing bootstrap, deploy, smoke, or local validation automation.
