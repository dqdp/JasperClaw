# ADR 0006: Keep One Public `agent-api` Surface with Layered Internal Use Cases

- Status: Accepted
- Date: 2026-03-11

## Context

`agent-api` must expose an OpenAI-compatible HTTP surface for `Open WebUI`.

There is a risk of drifting toward one of two bad extremes:

- a thin proxy with business logic scattered through route handlers
- an over-engineered internal network API before a real need exists

## Decision

Expose a **single public OpenAI-compatible HTTP surface** in v1, while organizing the internals around explicit application use cases.

### Public surface

- `GET /healthz`
- `GET /readyz`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/audio/transcriptions`
- `POST /v1/audio/speech`

### Internal structure

- routers map HTTP to application commands
- application services own orchestration flow
- clients talk to downstream runtimes and services
- repositories own persistence access

### Explicit non-decision

Do **not** introduce a separate networked internal domain API in v1.

## Consequences

### Positive

- keeps the public contract simple
- keeps orchestration logic out of transport code
- preserves a clean path to future clients
- improves testability without multiplying APIs

### Negative

- requires more internal structure than a raw FastAPI skeleton
- some future expansion may still require refactoring if a second public API is ever justified
