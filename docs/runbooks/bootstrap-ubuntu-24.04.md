# Runbook: Bootstrap Ubuntu 24.04 Host

## Purpose

Prepare a fresh Ubuntu 24.04 host for running the project.

## Desired host state

Only the minimal runtime remains native:

- NVIDIA driver
- Docker Engine
- Docker Compose plugin
- Docker Buildx plugin
- NVIDIA Container Toolkit
- SSH access for deployment

All application components run in containers.

## Preconditions

- Ubuntu 24.04 installed
- user with sudo access
- SSH access configured
- NVIDIA GPU present if local inference is expected on GPU

## High-level procedure

1. Update the host
2. Install or validate NVIDIA driver
3. Install Docker Engine and plugins
4. Install NVIDIA Container Toolkit
5. Validate Docker GPU access
6. Prepare deployment directory layout
7. Create environment files
8. Perform first image pull and smoke deploy

## Checklist

### 1. Base OS validation

- confirm Ubuntu version
- confirm kernel is stable and boots correctly
- confirm network and DNS are functional
- confirm enough disk space for models and containers

### 2. NVIDIA validation

- install supported driver
- confirm `nvidia-smi` works on host
- record driver version
- confirm GPU memory availability matches intended model sizes

### 3. Docker installation

Install:

- Docker Engine
- docker-buildx-plugin
- docker-compose-plugin

Validate:

- Docker service is running
- user can run Docker commands as intended
- `docker compose version` works
- `docker buildx version` works

### 4. NVIDIA Container Toolkit installation

Validate:

- toolkit installed cleanly
- Docker is configured to expose GPU runtime correctly
- a test GPU container can see the GPU

### 5. Host filesystem layout

Recommended target path:

```text
/opt/local-assistant/
  infra/
  .env files
  compose files
  scripts/
```

### 6. Secrets and environment files

Prepare production environment values for:

- registry access if required
- Postgres password
- Open WebUI secrets
- internal API key between Open WebUI and agent-api
- Spotify credentials if enabled
- search API credentials if enabled

### 7. First deployment validation

Before first real rollout, confirm:

- Docker can pull all required images
- compose configuration resolves successfully
- storage volumes are created correctly
- GPU-backed Ollama container can start

## Post-bootstrap expected outcome

The host should be able to:

- receive a deploy over SSH
- pull images from GHCR
- run the full Compose stack
- expose only the reverse proxy publicly
- keep internal services private
