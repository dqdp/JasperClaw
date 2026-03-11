# ADR 0002: Make `agent-api` the Canonical Control Plane

- Status: Accepted
- Date: 2026-03-11

## Context

The system uses Open WebUI for UX and self-hosted local inference through Ollama.

Open WebUI is capable of much more than UI:

- model/provider integration
- tool integration
- knowledge features
- voice features
- admin configuration

That flexibility is useful, but it creates a structural risk:

> the project can accidentally develop two control planes,
> one inside Open WebUI and one inside custom backend services.

For a long-lived home/work assistant, that would lead to:

- divergent behavior between text and voice paths
- duplicated configuration
- unclear ownership of memory and tool policy
- harder testing and debugging
- increased blast radius for future integrations

## Decision

`agent-api` becomes the **only canonical AI/backend ingress**.

Open WebUI is retained as the UX shell.

### Architectural meaning

- Open WebUI calls only `agent-api`
- Open WebUI does not call Ollama directly in production
- Open WebUI does not directly execute production tools in the primary assistant path
- `agent-api` owns memory, routing, tool policy, and audit
- voice and text share the same backend orchestration path

## Consequences

### Positive

- one source of truth for assistant behavior
- easier extension to new clients beyond Open WebUI
- better testability of orchestration logic
- stronger control over tool invocation and secrets
- lower long-term architecture drift

### Negative

- additional backend engineering work up front
- less direct use of some Open WebUI convenience features
- need to define explicit internal contracts earlier

## Rejected alternative

### Open WebUI as first-class agent layer

This would speed up early prototyping, but was rejected because:

- it couples core assistant behavior to the UI platform
- it increases risk of hidden state/configuration drift
- it makes future multi-client evolution harder
- it weakens the boundary around privileged tools and policies

## Invariants resulting from this decision

1. Every user-facing AI request passes through `agent-api`.
2. Open WebUI is not canonical for assistant memory or policy.
3. Ollama is internal runtime only.
4. Speech flows through the same backend control path as text.
