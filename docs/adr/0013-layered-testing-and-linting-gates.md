# ADR 0013: Use Layered Testing and Explicit Lint Gates in v1

- Status: Accepted
- Date: 2026-03-11

## Context

The repository is moving from architecture-only scaffolding toward real service implementation.

Without an explicit quality model, testing and verification tend to drift into a mix of ad hoc local checks, inconsistent CI behavior, and runtime-only debugging.

The current repository already contains:

- Python service scaffolds
- a CI workflow that runs `ruff` and `pytest`
- Compose validation
- smoke-test runbooks tied to deployment

What is missing is one clear architectural decision describing how linting and tests are expected to work together across local development, CI, and deployment.

## Decision

Use a **layered testing model with explicit lint gates** in v1.

Use **short-form TDD** for new vertical slices and risky runtime-facing changes.

## Development workflow rule

For any new runtime-facing slice that changes system behavior materially, define the tests before or alongside the implementation work rather than after the fact.

In v1, this does not mean writing long formal TDD specifications for every task.

It means:

- start with a short TDD plan for the slice
- define the behavior to prove before implementation is considered complete
- define the expected failure cases before implementation is considered complete
- use the layered test model to decide which checks belong in unit, integration, and smoke levels

This short-form TDD rule is especially expected for:

- the first real vertical slice of a feature
- risky integration changes
- changes that introduce new failure semantics
- changes that affect the canonical request path

Low-risk refactors or narrow internal edits do not require separate TDD documents if their test impact is already obvious and local.

## Quality layers

### 1. Lint gate

Linting is a required fast-fail quality gate for service code.

For the current Python-first v1 stack:

- `ruff` is the canonical linter
- lint must run in CI
- lint failures block merge readiness

### 2. Unit tests

Unit tests verify local behavior in isolation.

They should:

- run quickly
- avoid external runtime dependencies where possible
- validate schemas, mapping logic, policy logic, and orchestration helpers

### 3. Integration tests

Integration tests verify real contracts between components inside the accepted architecture.

Priority v1 integrations:

- `agent-api -> Ollama`
- `agent-api -> Postgres`
- `agent-api -> tools integration layer`
- later `agent-api -> stt-service`
- later `agent-api -> tts-service`

Integration tests are required for behavior that cannot be trusted through unit tests alone.

### 4. Smoke tests

Smoke tests validate the deployed stack through the canonical request path.

For v1, smoke tests must verify:

- `agent-api` liveness and readiness
- model listing
- at least one real chat path
- storage viability
- optional tool and voice paths only when those features are enabled

## Environment policy

Not every quality layer runs in every environment.

### Local development

Developers may use lightweight local validation for fast iteration:

- lint
- unit tests
- selected local integration tests

### CI

CI must run:

- lint
- unit tests
- contract-oriented integration tests that do not require the full production runtime
- Compose validation

### Target runtime validation

GPU-backed model and deployment-realistic validation belongs to the target runtime path, not to every local machine.

For `local-assistant` v1, the canonical runtime validation environment is **Linux with NVIDIA GPU support**.

MacBook or other local developer machines may be used for fast development loops, but they are not the canonical environment for final model-serving validation.

## Gating rule

No change should be considered production-ready based only on:

- successful lint
- successful unit tests
- mock-only local execution

Runtime-facing features require the appropriate lower and higher layers:

- code quality gate
- isolated correctness checks
- contract verification
- deployed smoke validation

## Consequences

### Positive

- reduces ambiguity around what counts as verified
- keeps fast feedback in CI without pretending mock-only checks are enough
- aligns local development, CI, and deployment verification under one model
- makes Linux + NVIDIA the explicit truth source for runtime-backed model validation

### Negative

- some runtime-facing work will require a heavier validation environment
- local MacBook verification will remain useful but incomplete
- CI may need future expansion as more real integrations are implemented
