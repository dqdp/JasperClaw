# Current Priorities

## Purpose

Capture the near-term execution order after the current repo-wide review.

This file is intentionally narrower than `roadmap.md` and less issue-granular
than `backlog.md`.

Use it when deciding what to do next without re-deriving priority from the full
architecture and backlog set.

## Current Read

The repository is no longer just scaffold.

Working vertical slices now include:

- real text control-plane behavior in `agent-api`
- persistence and readiness for the text path
- baseline retrieval-aware memory behavior
- in-process tools boundary with policy and audit
- working Telegram ingress
- working buffered STT and TTS slices behind `agent-api`
- deploy-gated smoke coverage for chat, STT, and TTS when voice is enabled

The project is still not fully "done" as a platform because several important
cross-cutting areas are only partially closed:

- docs and metadata still contain stale placeholder language in some files
- voice exists as endpoints and runtime slices, but is not yet fully converged
  into the canonical persistence story
- STT runtime policy is still valid but not yet ideal for production cold-start
- ops hardening is incomplete around backup, restore, rollback, and version
  policy
- memory lifecycle rules are still incomplete

## Recommended Direction

The recommended path is `stabilize-first`, not `feature-first`.

Rationale:

- the system already has several real slices worth protecting
- a new feature wave now would increase doc drift and operability debt
- the highest-value next work is making current behavior honest,
  deterministic, and easier to run

## Phase A: Stabilization

Goal: make the current system coherent, documented, and operationally
predictable before another feature expansion wave.

### Phase A Exit Criteria

Phase A is complete only when all of the following are true:

- top-level docs no longer describe `agent-api`, STT, or TTS as placeholders
  where the code is already real
- voice input participates in canonical transcript persistence and voice output
  has explicit audit and observability semantics instead of living as isolated
  endpoint behavior
- the default production-like voice profile does not depend on accidental
  runtime model download during first readiness
- backup, restore, and rollback procedures are explicit and testable
- one canonical smoke flow cleanly covers both `text-only` and `voice-enabled`
  deployment modes

### A1. Truth Pass For Docs And Metadata

Update files that still describe old stub or placeholder states when the code is
already real.

Primary targets:

- `docs/roadmap.md`
- `docs/service-contracts/agent-api.md`
- `services/README.md`
- `infra/compose/README.md`
- service metadata such as `services/tts-service/pyproject.toml`

Done when:

- no top-level doc incorrectly claims that `agent-api` chat or STT/TTS are
  still placeholders
- remaining placeholder language is limited to genuinely inactive scaffold such
  as `tools-gateway`

### A2. Define Voice Persistence Contract

Close the design gap between "voice endpoints exist" and "voice is part of the
same canonical interaction record as text".

Phase A contract:

- successful STT persists exactly one canonical transcript row in `messages`
- that row uses `role='user'`, `content=<normalized transcript>`, and
  `source='audio_transcription'`
- voice-originated transcript rows participate in normal conversation
  continuity and memory retrieval
- raw uploaded audio is not stored in Postgres in the first slice
- TTS does not create transcript rows
- TTS audit remains in request tracing, logs, and metrics during Phase A
  instead of overloading the current chat-centric database audit tables

Explicitly deferred:

- richer modality metadata on transcript rows
- database-backed TTS audit tables
- raw audio blob retention

Done when:

- the persistence shape for STT and TTS is explicitly documented against the
  current schema, not an aspirational future schema
- tests can be written against one stable contract instead of implicit behavior

### A3. Implement Voice Persistence Convergence

Apply the contract from `A2` in the real code path.

Primary targets:

- persist `audio/transcriptions` output into canonical conversation state
- ensure voice-originated turns remain compatible with retrieval and continuity
- keep synthesis debuggable through request tracing, logs, and metrics without
  inventing a premature TTS database schema
- explicitly guard against transcript ordering races when text and audio turns
  append to the same conversation

Done when:

- voice input produces persisted conversation state through the canonical model
- retrieval can operate on the resulting transcript path
- tests cover `audio/transcriptions -> persistence`

### A4. Fix STT Runtime Acquisition Policy

Decide how model preload and cold-start behavior should work for STT in
production-like deployments.

Current observation:

- STT is functional, but the first `readyz` may include model download/load

Recommended direction:

- remove network-dependent first-readiness behavior from the default production
  profile
- use explicit prewarm or prefetch behavior instead of accidental runtime
  acquisition

Done when:

- STT cold-start behavior is intentional and bounded
- operators do not depend on implicit runtime downloads during first traffic

### A5. Define Voice Deployment Profiles

Make the supported runtime modes explicit instead of letting them emerge from
env defaults and ad hoc assumptions.

Recommended baseline profiles:

- `text-only`
- `voice-enabled-cpu`

Deferred:

- premium GPU voice profiles such as XTTS

Done when:

- supported deployment profiles are documented
- readiness and smoke expectations are tied to the chosen profile

### A6. Finish Ops Hardening Minimum

Close the remaining operational basics before another expansion wave.

#### A6.1. Define Backup Scope And Procedure

Make backup boundaries explicit.

Primary targets:

- canonical Postgres data
- backup trigger, storage location, and retention expectation
- explicit statement that models, caches, containers, and generated audio are
  not the canonical backup target

#### A6.2. Prove Restore In A Disposable Environment

Do not stop at a written runbook; verify that a backup can actually be restored
into a fresh environment.

Primary targets:

- restore procedure
- restore validation checklist
- disposable restore drill

#### A6.3. Validate Rollback Against Immutable Image Versions

Make rollback an exercised procedure instead of a conceptual fallback.

Primary targets:

- rollback runbook
- real tagged image rollback test
- post-rollback smoke validation

#### A6.4. Define Runtime Pinning And Upgrade Policy

Make version policy explicit across the main runtime surfaces.

Primary targets:

- image tag policy
- Python dependency pinning expectations
- STT/TTS runtime and model artifact version policy

#### A6.5. Review Deploy Gate Contract

Ensure deploy, rollback, and smoke behavior align with one operator-facing
contract.

Primary targets:

- deploy runbook
- smoke gate expectations
- rollback and restore references in the normal rollout flow

Done when:

- backup scope is explicit
- restore is documented and proven in a disposable environment
- rollback is documented and validated against immutable image versions
- runtime version policy is explicit
- deploy-time checks match the documented operator contract

### A7. Keep One Canonical Smoke Matrix

Make sure the smoke flow cleanly represents both main deployment modes:

- `text-only`
- `voice-enabled`

Done when:

- text-only smoke does not require voice dependencies
- voice-enabled smoke validates chat, STT, and TTS through the canonical public
  ingress
- the deploy-time smoke contract matches the documented deployment profiles

## Phase B: Next Feature Milestone

After Phase A, the recommended next milestone is `memory lifecycle hardening`.

This is a better next move than premium voice or broader tool surface because it
improves the core assistant state model instead of widening the runtime matrix.

### Phase B Exit Criteria

Phase B is complete only when all of the following are true:

- retention, invalidation, and deletion rules are explicit and covered by tests
- retrieval quality is regression-tested against fixed fixtures
- extraction behavior is broader than the current conservative baseline without
  clearly degrading memory quality
- memory debugging no longer depends on ad hoc database inspection

### B1. Define Lifecycle Contract

Make lifecycle semantics explicit before adding more extraction breadth.

Primary targets:

- active, invalidated, and deleted states on the current schema
- explicit deferral of automatic `expired` handling until the schema carries
  dedicated expiry data
- retention and provenance invariants
- explicit non-goals for early forget flows

### B2. Implement Lifecycle State Transitions

Apply the contract from `B1` to the real memory state model.

Primary targets:

- expiry handling
- invalidation handling
- explicit delete or forget path where scoped for v1

### B3. Add Retrieval Evaluation Fixtures

Move beyond behavioral tests and add fixed relevance fixtures for regression
control.

Primary targets:

- positive relevance cases
- false-positive controls
- stale-memory cases

### B4. Expand Extraction Policy Carefully

The current path is conservative. The next step is to widen useful memory
capture without flooding the store with noise.

Primary targets:

- add narrowly scoped new candidate categories
- preserve explicit low-signal exclusions
- bound false-positive growth with fixture-backed checks

### B5. Improve Memory Observability

Make it easier to answer:

- why a memory was materialized
- why a candidate was skipped
- why a retrieval result was filtered

Primary targets:

- materialization decision logs or metrics
- skip and rejection reason visibility
- retrieval filter and ranking visibility

### B6. Add Operator-Facing Memory Inspection Guidance

Operators should be able to understand memory behavior without resorting to ad
hoc SQL archaeology.

Primary targets:

- memory debugging runbook
- inspection commands or queries
- expected signals in logs and metrics

## Explicit Non-Priorities Right Now

Do not prioritize these before Phase A is complete:

- XTTS or other premium GPU voice profiles
- streaming TTS
- richer Telegram command surface
- standalone tools service extraction
- major new provider integrations

## Practical Order

Execute in this order:

1. truth pass for docs and metadata
2. define voice persistence contract
3. implement voice persistence convergence
4. fix STT runtime acquisition policy
5. define voice deployment profiles
6. define backup scope and procedure
7. prove restore in a disposable environment
8. validate rollback against immutable image versions
9. define runtime pinning and upgrade policy
10. review deploy gate contract
11. keep one canonical smoke matrix
12. define lifecycle contract
13. implement lifecycle state transitions
14. add retrieval evaluation fixtures
15. expand extraction policy carefully
16. improve memory observability
17. add operator-facing memory inspection guidance

## Change Rule

If a new feature request conflicts with this order, prefer changing this file
only after confirming that the new work has higher value than stabilization.
