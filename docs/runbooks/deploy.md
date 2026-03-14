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
- backup is taken first when the rollout includes schema risk or another
  elevated-risk change
- for elevated-risk rollout classes, the disposable backup/restore drill should
  already be proven through `infra/scripts/drill-backup-restore.sh`
- rollback should already be proven against an immutable image target through
  `infra/scripts/drill-rollback.sh`

## Standard deployment steps

1. Select target version
2. Approve production deployment
3. SSH into host through the deploy workflow
4. Log in to GHCR on host if required
5. Pull new images
6. Start supporting services needed before schema migration
7. Apply pending database migrations
8. Start or recreate user-facing services
9. Execute smoke tests
10. Confirm service health

## Operational notes

### Version selection

Use explicit immutable image tags where possible, such as:

- git SHA
- release tag

Avoid production deployment based on floating tags.

### Compose update pattern

Preferred rollout pattern:

- `docker compose pull`
- `docker compose up -d postgres ollama`
- `COMPOSE_OVERRIDE_FILE=infra/compose/compose.prod.yml bash infra/scripts/ensure-ollama-models.sh`
- `docker compose build platform-db`
- `docker compose run --rm --no-deps platform-db python -m platform_db.cli migrate`
- `docker compose up -d --remove-orphans agent-api telegram-ingress open-webui caddy` for `text-only`
- `COMPOSE_PROFILES=voice docker compose up -d --remove-orphans agent-api telegram-ingress stt-service tts-service open-webui caddy` for `voice-enabled-cpu`

Keep `COMPOSE_PROFILES` and `VOICE_ENABLED` aligned. A `voice-enabled` env with a
text-only Compose profile is considered an invalid rollout contract. The
canonical `infra/scripts/deploy.sh` now fails fast on that mismatch instead of
continuing with an ambiguous rollout.

For the normal host-local flow, prefer the script entrypoint:

```bash
bash infra/scripts/deploy.sh
```

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
4. revert to previous known-good image version if needed, using the rollback
   procedure already proven through `infra/scripts/drill-rollback.sh`
5. rerun smoke checks

## Success criteria

Deployment is considered successful when:

- target version is running
- containers are healthy
- smoke tests pass
- no unexpected restart loops are present
