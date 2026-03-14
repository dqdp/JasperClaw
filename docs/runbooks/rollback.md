# Runbook: Rollback

## Purpose

Recover from a failed or degraded deployment.

## Rollback philosophy

Rollback for v1 is image-version rollback, not infrastructure re-provisioning.

Because the runtime is containerized, the normal rollback path is:

1. restore previous known-good image tags
2. re-run Compose update
3. verify smoke checks

Rollback targets must be immutable image versions, not floating tags.

## Preconditions

- previous known-good version is known
- images for that version still exist in GHCR
- host and volumes are intact
- the root Compose env used by the stack is loaded, or commands are prefixed
  with the required root variables such as `APP_VERSION`, `GHCR_OWNER`, and
  `POSTGRES_PASSWORD`

## Standard rollback procedure

1. Identify last known-good version
2. Restore any rollout-time env changes that were coupled to the failed version
3. Update deployment environment to the previous immutable `APP_VERSION`
4. Pull matching images
5. Recreate containers with the previous version
6. Run smoke checks
7. Confirm service stability

Example:

```bash
export APP_VERSION=<known-good-sha-or-release-tag>
docker compose pull
docker compose up -d postgres ollama
docker compose up -d --remove-orphans agent-api open-webui caddy
COMPOSE_OVERRIDE_FILE=infra/compose/compose.prod.yml bash infra/scripts/smoke.sh
```

If voice-related config changed in the failed rollout, restore that profile
configuration as well before rerunning smoke.

## Important checks during rollback

- ensure rollback target matches all interdependent services
- verify database migrations are backward-compatible or handled safely
- confirm no incompatible environment change was introduced
- inspect whether failure came from code, config, or external integration
- never treat `latest` as a valid rollback target

## Rollback drill expectation

Rollback is not considered operationally valid until it has been rehearsed
against a real immutable image target.

At minimum, the drill should prove:

- the target image tag still exists in GHCR
- Compose can pull and start the target images
- the post-rollback smoke flow passes against that specific target

For a deterministic local proof against explicit immutable tags, prefer the
helper script:

```bash
bash infra/scripts/drill-rollback.sh
```

That helper uses `compose.ci.yml` and fake runtime dependencies so the rollback
mechanics can be validated without depending on a real model runtime.

## When rollback may not be sufficient

Rollback alone may not solve the problem if:

- a destructive schema migration was applied
- persistent data is already corrupted
- external credentials changed
- host-level runtime changed unexpectedly

If rollback is not sufficient because data state must be recovered, switch to
the backup and restore runbooks instead of retrying image rollback blindly.

## Success criteria

Rollback is complete when:

- previous stable version is running
- user-facing chat path works again
- critical tool paths behave normally
- operational logs show normal startup and steady-state behavior
