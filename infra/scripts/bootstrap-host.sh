#!/usr/bin/env bash
set -euo pipefail

echo "Install on Ubuntu 24.04: NVIDIA driver, Docker Engine, docker-compose-plugin, docker-buildx-plugin, NVIDIA Container Toolkit."
echo "Then place root env file at .env, app runtime env file at infra/env/app.env, and run docker compose pull && up -d."
