# Handoff to Implementation Agent

## Mission

Bootstrap the repository for `local-assistant` according to the documented target architecture.

Your job is not to redesign the system.
Your job is to create a clean v1 skeleton that preserves the accepted architectural invariants.

## Non-negotiable architecture rules

1. `agent-api` is the only canonical AI/backend ingress.
2. Open WebUI must not call Ollama directly in production configuration.
3. Open WebUI must not directly own canonical memory, tool routing, or secrets policy.
4. Text and voice paths must converge through `agent-api`.
5. Ollama remains an internal runtime component.
6. Internal services are private on Docker networks; only the reverse proxy is public.
7. In v1, the tools boundary is typed but in-process inside `agent-api`.

## First repository deliverables

Create the initial repository structure with at least:

- `README.md`
- `docs/architecture.md`
- ADR documents from `docs/adr/`
- runbooks from `docs/runbooks/`
- `infra/compose/compose.yml`
- `infra/compose/compose.prod.yml`
- `infra/caddy/Caddyfile`
- `infra/env/app.example.env`
- `infra/env/prod.example.env`
- `infra/scripts/bootstrap-host.sh`
- `infra/scripts/deploy.sh`
- `infra/scripts/smoke.sh`
- `services/agent-api/` skeleton
- `services/stt-service/` skeleton
- `services/tts-service/` skeleton
- `services/tools-gateway/` skeleton
- `.github/workflows/ci.yml`
- `.github/workflows/images.yml`
- `.github/workflows/deploy-prod.yml`
- `Makefile`

## Required runtime topology

### Networks

Create three Compose networks:

- `frontend`
- `control`
- `runtime`

### Boundary requirements

- `open-webui` joins `frontend` and `control`
- `agent-api` joins `control` and `runtime`
- `ollama`, `postgres`, `stt-service`, and `tts-service` join `runtime`
- `open-webui` must not join `runtime`

## Required `agent-api` public endpoints

Provide stubs or initial implementation for:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/audio/transcriptions`
- `POST /v1/audio/speech`
- `GET /healthz`
- `GET /readyz`

## Model exposure rule

Expose logical assistant profile IDs, not raw Ollama model IDs.

Expected initial profiles:

- `assistant-v1`
- `assistant-fast`

## Internal service contracts

Implement minimal internal HTTP contracts for:

### STT
- `POST /transcribe`

### TTS
- `POST /speak`

### tools integration layer
- typed in-process adapter boundary for `web-search`
- placeholder structure for Spotify adapters

## Infrastructure expectations

### Reverse proxy

Use Caddy for HTTPS and proxying.

### Runtime

Use Docker Compose.

### Images

Use GHCR for custom images.

### Deployment

Use GitHub Actions to deploy over SSH with manual approval for production.

## Implementation priorities

Follow this order:

1. Compose skeleton with networks and service boundaries
2. Open WebUI configured to talk only to `agent-api`
3. `agent-api` OpenAI-compatible façade skeleton
4. Postgres integration scaffold
5. Ollama integration scaffold
6. STT/TTS service skeletons
7. typed tools integration scaffold inside `agent-api`
8. CI workflows
9. deploy workflow
10. smoke script

## What not to do in the first pass

Do not:

- add Kubernetes
- add Redis unless strictly needed
- add background workers
- introduce multi-agent orchestration
- connect Open WebUI directly to Ollama for convenience
- make Open Terminal part of the default assistant path
- use Open WebUI Knowledge as canonical memory

## Quality bar

The first pass should optimize for:

- explicitness
- reproducibility
- clean boundaries
- low accidental complexity
- easy handoff to future contributors
