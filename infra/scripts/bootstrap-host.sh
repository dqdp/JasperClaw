#!/usr/bin/env bash
set -euo pipefail

echo "Install on Ubuntu 24.04: NVIDIA driver, Docker Engine, docker-compose-plugin, docker-buildx-plugin, NVIDIA Container Toolkit."
echo "Then place prod env file at infra/env/app.env and run docker compose pull && up -d."
