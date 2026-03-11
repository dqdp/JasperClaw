# Runbook: Rollback

## Purpose

Recover from a failed or degraded deployment.

## Rollback philosophy

Rollback for v1 is image-version rollback, not infrastructure re-provisioning.

Because the runtime is containerized, the normal rollback path is:

1. restore previous known-good image tags
2. re-run Compose update
3. verify smoke checks

## Preconditions

- previous known-good version is known
- images for that version still exist in GHCR
- host and volumes are intact

## Standard rollback procedure

1. Identify last known-good version
2. Update deployment environment to that version
3. Pull matching images
4. Recreate containers with previous version
5. Run smoke checks
6. Confirm service stability

## Important checks during rollback

- ensure rollback target matches all interdependent services
- verify database migrations are backward-compatible or handled safely
- confirm no incompatible environment change was introduced
- inspect whether failure came from code, config, or external integration

## When rollback may not be sufficient

Rollback alone may not solve the problem if:

- a destructive schema migration was applied
- persistent data is already corrupted
- external credentials changed
- host-level runtime changed unexpectedly

## Success criteria

Rollback is complete when:

- previous stable version is running
- user-facing chat path works again
- critical tool paths behave normally
- operational logs show normal startup and steady-state behavior
