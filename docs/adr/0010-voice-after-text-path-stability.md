# ADR 0010: Deliver Voice After the Text Path Stabilizes

- Status: Accepted
- Date: 2026-03-11

## Context

Voice is part of the intended product direction, but the text path is still not implemented end to end.

Treating voice as a first implementation target would blur the first real vertical slice and slow down validation of the canonical control plane.

## Decision

Keep voice **inside v1 scope**, but sequence it **after the text path is stable**.

### Delivery rule

- Control Plane MVP is text-first
- real voice implementation starts only after the text path, persistence model, and profile routing are stable

### Boundary rule

When voice is implemented, keep `stt-service` and `tts-service` as distinct service boundaries because their runtimes and dependencies justify isolation more than the tools layer does.

### Contract rule

`agent-api` remains the public voice ingress and keeps the OpenAI-compatible voice endpoints as the stable external contract.

## Consequences

### Positive

- protects the first working vertical slice
- keeps voice aligned with the same canonical orchestration path
- preserves a reasonable isolation boundary for specialized speech runtimes

### Negative

- voice value arrives later than text
- placeholder voice scaffolds may exist before the real flow is implemented
