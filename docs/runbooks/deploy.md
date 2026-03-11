# Runbook: Deploy

## Purpose

Describe the normal production deployment flow.

## Deployment model

- application images are built in GitHub Actions
- images are published to GHCR
- production rollout is manually approved
- host update is executed over SSH
- Compose pulls new images and recreates containers

## Preconditions

- CI for the target commit is green
- required images exist in GHCR
- production environment approval granted
- host is reachable over SSH
- production secrets are present

## Standard deployment steps

1. Select target version
2. Approve production deployment
3. SSH into host through the deploy workflow
4. Log in to GHCR on host if required
5. Pull new images
6. Run Compose update
7. Execute smoke tests
8. Confirm service health

## Operational notes

### Version selection

Use explicit immutable image tags where possible, such as:

- git SHA
- release tag

Avoid production deployment based on floating tags.

### Compose update pattern

Preferred rollout pattern:

- `docker compose pull`
- `docker compose up -d --remove-orphans`

### Health validation

Minimum checks after rollout:

- reverse proxy responds
- Open WebUI is reachable
- `agent-api` is healthy
- Ollama is reachable internally through `agent-api`
- chat request succeeds
- voice path succeeds if enabled
- tool path succeeds for at least one safe tool

## Failure handling

If smoke tests fail:

1. stop the rollout
2. inspect service logs
3. identify failed component
4. revert to previous known-good image version if needed
5. rerun smoke checks

## Success criteria

Deployment is considered successful when:

- target version is running
- containers are healthy
- smoke tests pass
- no unexpected restart loops are present
