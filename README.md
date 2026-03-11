# local-assistant

Self-hosted home/work assistant built around a single control plane:

- **Open WebUI** as the user оболочка / UX layer
- **agent-api** as the canonical AI/backend entrypoint
- **Ollama** as the internal inference runtime
- **Postgres + pgvector** as canonical assistant state
- **STT/TTS services** as internal speech executors
- **tools-gateway** as typed adapters to external systems
- **Caddy** as HTTPS reverse proxy and single external ingress

## Why this architecture

This repository starts from one core decision:

> All user-facing AI requests must pass through `agent-api`.

That means:

- Open WebUI does **not** call Ollama directly
- Open WebUI does **not** call production tools directly
- Open WebUI is **not** the source of truth for memory, policies, tool routing, or secrets
- text, voice, and future clients share the same backend path

This avoids split-brain behavior and keeps the assistant extensible.

## Target scope for v1

The first version is intentionally conservative:

- one canonical orchestration layer
- one canonical persistent store
- one inference runtime
- minimal operational complexity
- clean path to later expansion

### Included in v1

- Open WebUI
- agent-api
- Ollama
- Postgres + pgvector
- stt-service
- tts-service
- tools-gateway
- Caddy
- Docker Compose runtime
- GitHub Actions CI/CD
- GHCR image registry
- deploy over SSH

### Explicitly out of scope for v1

- Kubernetes
- event bus / message broker
- multi-agent orchestration
- autonomous long-running workflows
- direct Open WebUI → Ollama path
- direct Open WebUI → tools path
- Open Terminal in the primary assistant path
- using Open WebUI Knowledge as canonical memory

## Repository intent

This repo is expected to become a **monorepo** containing:

- infrastructure definitions
- service code
- deployment scripts
- architecture documentation
- runbooks
- CI/CD workflows

Recommended top-level structure:

```text
local-assistant/
├─ README.md
├─ .gitignore
├─ .env.example
├─ Makefile
├─ docs/
│  ├─ architecture.md
│  ├─ handoff_to_agent.md
│  ├─ adr/
│  │  ├─ 0001-monorepo.md
│  │  ├─ 0002-agent-api-control-plane.md
│  │  └─ 0003-deploy-via-ssh.md
│  └─ runbooks/
│     ├─ bootstrap-ubuntu-24.04.md
│     ├─ deploy.md
│     ├─ rollback.md
│     └─ smoke-tests.md
├─ infra/
│  ├─ compose/
│  ├─ caddy/
│  ├─ env/
│  └─ scripts/
├─ services/
│  ├─ agent-api/
│  ├─ stt-service/
│  ├─ tts-service/
│  └─ tools-gateway/
└─ .github/
   └─ workflows/
```

## Documentation map

- [`docs/architecture.md`](docs/architecture.md) — target architecture v1
- [`docs/adr/0001-monorepo.md`](docs/adr/0001-monorepo.md) — monorepo decision
- [`docs/adr/0002-agent-api-control-plane.md`](docs/adr/0002-agent-api-control-plane.md) — canonical control plane decision
- [`docs/adr/0003-deploy-via-ssh.md`](docs/adr/0003-deploy-via-ssh.md) — deploy strategy decision
- [`docs/runbooks/bootstrap-ubuntu-24.04.md`](docs/runbooks/bootstrap-ubuntu-24.04.md) — host bootstrap runbook
- [`docs/runbooks/deploy.md`](docs/runbooks/deploy.md) — deployment runbook
- [`docs/runbooks/rollback.md`](docs/runbooks/rollback.md) — rollback runbook
- [`docs/runbooks/smoke-tests.md`](docs/runbooks/smoke-tests.md) — post-deploy smoke test checklist
- [`docs/handoff_to_agent.md`](docs/handoff_to_agent.md) — compact execution brief for an implementation agent

## First implementation milestones

1. Bring up `ollama` + `open-webui`
2. Insert `agent-api` as the only OpenAI-compatible backend
3. Add `postgres + pgvector`
4. Add `stt-service` and `tts-service`
5. Add `tools-gateway`
6. Add Caddy and HTTPS
7. Add CI
8. Add CD

## Operating model

Production host should keep only the minimal native runtime:

- NVIDIA driver
- Docker Engine
- Docker Compose plugin
- Docker Buildx plugin
- NVIDIA Container Toolkit

All application components should run in containers.

## Implementation note for future contributors

When making trade-offs, prefer:

- one control plane over multiple convenience paths
- explicit service boundaries over implicit coupling
- typed internal APIs over UI-driven hidden behavior
- pinned image versions over floating tags in production
- reproducibility and rollback over ad hoc convenience

## Starter scaffold included

This repository skeleton also includes:

- `infra/compose/compose.yml`
- `infra/env/*.example.env`
- `infra/caddy/Caddyfile`
- `.github/workflows/*`
- `services/agent-api` minimal FastAPI skeleton
- placeholder `stt-service`, `tts-service`, `tools-gateway`

These files are intended as a bootstrap point for an implementation agent, not as a finished production deployment.
