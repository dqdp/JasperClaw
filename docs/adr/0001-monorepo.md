# ADR 0001: Use a Monorepo for v1

- Status: Accepted
- Date: 2026-03-11

## Context

The project is expected to contain:

- multiple application services
- infrastructure definitions
- CI/CD workflows
- deployment scripts
- architecture documentation
- operational runbooks

The initial team size is small and the system will evolve quickly.

Splitting the repository too early would increase coordination overhead before the component boundaries are fully validated.

## Decision

Use a **single monorepo** for v1.

The monorepo will contain:

- service code
- infrastructure code
- environment templates
- operational scripts
- documentation
- GitHub Actions workflows

## Consequences

### Positive

- simple bootstrap for contributors and agents
- single versioned source of truth for architecture and code
- easier refactors across service boundaries
- simpler CI setup in early stages
- easier to keep docs, infra, and code aligned

### Negative

- repo may grow quickly
- CI can become slower if not scoped carefully
- service ownership boundaries are less explicit than in polyrepo setups

## Why accepted

At this stage, coordination simplicity and cross-cutting refactors matter more than repository isolation.

A move to polyrepo remains possible later if strong ownership or release isolation becomes necessary.
