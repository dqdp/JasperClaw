# local-assistant

Self-hosted home/work assistant built around a single control plane:

- **Open WebUI** as the user оболочка / UX layer
- **agent-api** as the canonical AI/backend entrypoint
- **Ollama** as the internal inference runtime
- **Postgres + pgvector** as canonical assistant state
- **STT/TTS services** as deferred internal speech executors after the text path is stable
- **typed tools integration** inside `agent-api` in v1, with a clean extraction path if a standalone gateway becomes justified later
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
- typed tools integration layer
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
│  └─ tts-service/
└─ .github/
   └─ workflows/
```

## Documentation map

- [`docs/architecture.md`](docs/architecture.md) — target architecture v1
- [`docs/implementation-status.md`](docs/implementation-status.md) — what is actually implemented versus only documented as target state
- [`docs/data-model.md`](docs/data-model.md) — canonical Postgres and pgvector schema plan for transcript, audit, and memory
- [`docs/features/chat.md`](docs/features/chat.md) — canonical text request flow from Open WebUI through persistence and response
- [`docs/features/memory.md`](docs/features/memory.md) — canonical derived-memory model, provenance, and retrieval behavior
- [`docs/roadmap.md`](docs/roadmap.md) — implementation milestones and delivery order
- [`docs/backlog.md`](docs/backlog.md) — epics and task breakdown for execution tracking
- [`docs/adr/0001-monorepo.md`](docs/adr/0001-monorepo.md) — monorepo decision
- [`docs/adr/0002-agent-api-control-plane.md`](docs/adr/0002-agent-api-control-plane.md) — canonical control plane decision
- [`docs/adr/0003-deploy-via-ssh.md`](docs/adr/0003-deploy-via-ssh.md) — deploy strategy decision
- [`docs/adr/0004-open-webui-non-canonical-ux-projection.md`](docs/adr/0004-open-webui-non-canonical-ux-projection.md) — make Open WebUI a non-canonical UX projection
- [`docs/adr/0005-canonical-assistant-state-model.md`](docs/adr/0005-canonical-assistant-state-model.md) — separate transcript, execution audit, and derived memory state
- [`docs/adr/0006-agent-api-single-public-surface-layered-internals.md`](docs/adr/0006-agent-api-single-public-surface-layered-internals.md) — one public `agent-api` surface with layered internals
- [`docs/adr/0007-tools-boundary-in-process-in-v1.md`](docs/adr/0007-tools-boundary-in-process-in-v1.md) — keep tools in-process in v1
- [`docs/adr/0008-profile-routing-without-automatic-fallback.md`](docs/adr/0008-profile-routing-without-automatic-fallback.md) — profile routing without hidden fallback
- [`docs/adr/0009-auth-and-secret-boundaries-for-v1.md`](docs/adr/0009-auth-and-secret-boundaries-for-v1.md) — narrow auth and secret boundary for v1
- [`docs/adr/0010-voice-after-text-path-stability.md`](docs/adr/0010-voice-after-text-path-stability.md) — deliver voice after the text path is stable
- [`docs/adr/0011-readiness-observability-and-error-semantics.md`](docs/adr/0011-readiness-observability-and-error-semantics.md) — define operational probes, request tracing, and stable error behavior
- [`docs/adr/0012-capability-gated-agent-actions.md`](docs/adr/0012-capability-gated-agent-actions.md) — keep agent actions capability-gated, least-privilege, and audit-first
- [`docs/adr/0013-layered-testing-and-linting-gates.md`](docs/adr/0013-layered-testing-and-linting-gates.md) — use layered testing and explicit lint gates for v1 quality control
- [`docs/service-contracts/agent-api.md`](docs/service-contracts/agent-api.md) — public contract for the canonical backend ingress
- [`docs/service-contracts/tools.md`](docs/service-contracts/tools.md) — internal typed contract for the v1 tools integration layer
- [`docs/testing/short-tdd-plan-template.md`](docs/testing/short-tdd-plan-template.md) — compact TDD plan template with a Control Plane MVP example slice
- [`docs/ops/agent-action-policy.md`](docs/ops/agent-action-policy.md) — risk classes, approvals, sandbox profiles, and audit rules for agent actions
- [`docs/ops/configuration.md`](docs/ops/configuration.md) — canonical env-var and config ownership reference
- [`docs/ops/observability.md`](docs/ops/observability.md) — minimum request tracing, health, and readiness semantics
- [`docs/ops/error-semantics.md`](docs/ops/error-semantics.md) — stable error taxonomy and mapping rules
- [`docs/runbooks/bootstrap-ubuntu-24.04.md`](docs/runbooks/bootstrap-ubuntu-24.04.md) — host bootstrap runbook
- [`docs/runbooks/deploy.md`](docs/runbooks/deploy.md) — deployment runbook
- [`docs/runbooks/rollback.md`](docs/runbooks/rollback.md) — rollback runbook
- [`docs/runbooks/smoke-tests.md`](docs/runbooks/smoke-tests.md) — post-deploy smoke test checklist
- [`docs/handoff_to_agent.md`](docs/handoff_to_agent.md) — compact execution brief for an implementation agent

## First implementation milestones

1. Bring up `ollama` + `open-webui`
2. Insert `agent-api` as the only OpenAI-compatible backend
3. Add `postgres + pgvector`
4. Add typed tools integration inside `agent-api`
5. Stabilize the text path and persistence model
6. Add `stt-service` and `tts-service` after the text path is stable
7. Add Caddy and HTTPS
8. Add CI
9. Add CD

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
- layered verification over single-step “it works on my machine” checks

## Starter scaffold included

This repository skeleton also includes:

- `infra/compose/compose.yml`
- `infra/env/*.example.env`
- `infra/caddy/Caddyfile`
- `.github/workflows/*`
- `services/agent-api` minimal FastAPI skeleton
- placeholder `stt-service`, `tts-service`

These files are intended as a bootstrap point for an implementation agent, not as a finished production deployment. Some placeholder scaffolds remain broader than the accepted v1 architecture so implementation should follow the ADR set, not placeholder service count alone.
