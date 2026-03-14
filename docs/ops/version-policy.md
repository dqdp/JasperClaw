# Version Policy

## Purpose

Define the minimum pinning and upgrade policy for runtime versions in v1.

## Core rule

Production-like deployments must prefer explicit, reviewable versions over
floating upgrades.

## Pinning rules

### 1. Custom service images

Pin custom images through `APP_VERSION`.

Allowed forms:

- git SHA
- release tag

Disallowed for production-like rollouts:

- implicit `latest`
- untracked local image tags used as if they were a release

### 2. Third-party container images

Third-party images in Compose must use explicit version tags in the repository.

Examples from the current stack:

- `ghcr.io/open-webui/open-webui:v0.8.6`
- `ollama/ollama:0.12.4`
- `caddy:2`
- `pgvector/pgvector:pg17`

Changing those versions is a repo change, not an ad hoc host-side override.

### 3. Python dependencies

Python runtime dependencies are owned by the repo and rebuilt into service
images.

Rules:

- do not upgrade Python dependencies directly on the host
- keep changes reviewable through `requirements.txt` or `pyproject.toml`
- prefer bounded version ranges or exact pins over open-ended dependencies
- verify affected services with targeted tests and smoke before rollout

### 4. Voice runtime and model artifacts

Voice runtime selection is part of the deployment contract and must be explicit.

Current supported CPU voice profile:

- `VOICE_ENABLED=true`
- `STT_MODEL=base`
- `STT_DEVICE=cpu`
- `STT_COMPUTE_TYPE=int8`
- `STT_PREWARM_ON_STARTUP=true`
- `TTS_DEFAULT_VOICE=assistant-default`

Changing those values counts as a runtime change and requires smoke validation.

## Upgrade policy

Treat each version change as one of these categories:

- custom service image bump
- third-party container image bump
- Python dependency bump
- model or voice profile change

Minimum expected validation:

- targeted automated tests for affected services
- rebuild of affected images
- `text-only` smoke for text-path changes
- `voice-enabled-cpu` smoke when STT, TTS, or voice-related config changes

## Rollback rule

Rollback targets must also be immutable and known-good.

If a rollout changes both code and runtime configuration, restore both:

- `APP_VERSION`
- any changed env profile values such as STT or TTS runtime settings

## Non-goals

This policy does not introduce:

- automatic dependency update tooling
- lockfile-based reproducibility for every Python service
- multi-environment version orchestration beyond the current single-host model
