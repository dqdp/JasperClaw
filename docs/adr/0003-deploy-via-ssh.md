# ADR 0003: Deploy to the Host via SSH from GitHub Actions

- Status: Accepted
- Date: 2026-03-11

## Context

The target runtime is a single Ubuntu 24.04 host with:

- Docker Engine
- Docker Compose plugin
- NVIDIA runtime support
- images stored in GHCR

The project needs:

- reproducible deployments
- low operational complexity
- manual approval before production rollout
- straightforward rollback

## Decision

Use **GitHub Actions + GHCR + deploy over SSH**.

Deployment flow:

1. CI validates code and Compose configuration
2. images workflow builds and publishes versioned container images to GHCR
3. production deployment requires manual approval through GitHub Environments
4. deploy workflow connects to host over SSH
5. host pulls selected image tags and runs `docker compose up -d`
6. smoke checks verify the rollout

## Consequences

### Positive

- operationally simple for a single-host system
- no separate deployment platform required
- easy to reason about rollback
- good fit for containerized monorepo projects
- integrates well with GitHub Environments and approvals

### Negative

- host remains mutable infrastructure
- no built-in rollout orchestration beyond Compose
- SSH access must be handled carefully
- production topology is intentionally simple rather than highly scalable

## Rejected alternatives

### Kubernetes

Rejected for v1 because it adds significant platform complexity without matching the immediate scale or team needs.

### Manual host-only deploys without CI/CD integration

Rejected because they reduce reproducibility and increase drift between known-good images and host state.

## Rollback model

Rollback means restoring a previously known-good application version and running the compose update again.

That model is considered sufficient for v1.
