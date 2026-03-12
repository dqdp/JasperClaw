# Runbook: Bootstrap Ubuntu 24.04 Host

## Purpose

Prepare a fresh Ubuntu 24.04 host for the production deployment model used by this repository.

This runbook is intentionally executable: it includes the exact package-install and validation commands needed to get from a clean host to the first successful deployment.

## Scope

Use this runbook for the canonical v1 deployment target:

- Ubuntu 24.04 LTS
- NVIDIA GPU available for local inference
- Docker Engine as the container runtime
- NVIDIA Container Toolkit for GPU access inside containers
- repository checkout on the host at `/opt/local-assistant`
- deployment triggered either manually on the host or through the existing GitHub Actions SSH workflow

This runbook assumes a single-host deployment. It does not cover Kubernetes or a remote managed inference provider.

## Desired host state

Only the minimal runtime remains native on the host:

- NVIDIA driver
- Docker Engine
- Docker Compose plugin
- Docker Buildx plugin
- NVIDIA Container Toolkit
- SSH access for deployment

All application components run in containers.

## Required inputs

Collect these before you start:

- SSH access to the Ubuntu host with `sudo`
- the GitHub repository SSH URL: `git@github.com:dqdp/JasperClaw.git`
- a GHCR pull token and username
- production domain name
- production secrets for:
  - `INTERNAL_OPENAI_API_KEY`
  - `WEBUI_SECRET_KEY`
  - `POSTGRES_PASSWORD`
- chosen runtime model IDs for:
  - `OLLAMA_CHAT_MODEL`
  - `OLLAMA_FAST_CHAT_MODEL`
  - `OLLAMA_EMBED_MODEL` if `MEMORY_ENABLED=true`

## 1. Base OS preparation

Update the base system and install general-purpose host tools:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl git gnupg jq openssh-client
```

Validate the OS version:

```bash
source /etc/os-release
printf '%s %s\n' "$PRETTY_NAME" "$VERSION_CODENAME"
uname -r
```

Expected result:

- Ubuntu 24.04 LTS (`noble`)
- kernel boots cleanly
- the host has enough free disk for container images and Ollama model weights

Recommended quick checks:

```bash
df -h /
free -h
```

## 2. Install the NVIDIA driver

Canonical’s Ubuntu Server documentation recommends the `ubuntu-drivers` flow for servers and GPU compute workloads.

Install the driver-management helper:

```bash
sudo apt update
sudo apt install -y ubuntu-drivers-common
```

List the compute-oriented drivers available for the current GPU:

```bash
sudo ubuntu-drivers list --gpgpu
```

Install the recommended compute driver automatically:

```bash
sudo ubuntu-drivers install --gpgpu
```

If you need to pin a specific server driver series instead of using auto-detection, use the exact version shown by `ubuntu-drivers list --gpgpu`, for example:

```bash
sudo ubuntu-drivers install --gpgpu nvidia:535-server
sudo apt install -y nvidia-utils-535-server
```

Reboot after driver installation:

```bash
sudo reboot
```

After reconnecting, validate that the driver is loaded:

```bash
nvidia-smi
cat /proc/driver/nvidia/version
```

Expected result:

- `nvidia-smi` returns successfully
- the host sees the intended GPU
- driver version and CUDA compatibility are visible

If `nvidia-smi` fails immediately after package installation, the most common cause is that the host has not been rebooted yet.

## 3. Install Docker Engine from Docker’s apt repository

Remove conflicting distro-provided packages first:

```bash
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt remove -y "$pkg"
done
```

Configure Docker’s official apt repository:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
```

Install Docker Engine and the required plugins:

```bash
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Validate the daemon:

```bash
sudo systemctl enable --now docker
sudo systemctl status docker --no-pager
sudo docker run --rm hello-world
```

Optional but recommended for operator ergonomics:

```bash
sudo groupadd docker || true
sudo usermod -aG docker "$USER"
```

Then either log out and back in, or start a new shell with:

```bash
newgrp docker
```

After the new shell picks up group membership, validate the non-`sudo` Docker path:

```bash
docker version
docker compose version
docker buildx version
```

Note: membership in the `docker` group effectively grants root-equivalent access on the host. Use a dedicated deploy user if that matters for your environment.

If you previously ran Docker as `sudo` and later switch to the `docker` group, you may need to fix `~/.docker` ownership:

```bash
sudo chown "$USER":"$USER" "$HOME/.docker" -R
sudo chmod g+rwx "$HOME/.docker" -R
```

## 4. Install the NVIDIA Container Toolkit

Add NVIDIA’s container-toolkit repository and install the toolkit:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
```

Configure Docker to use the NVIDIA runtime and restart the daemon:

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Validate GPU access from a container:

```bash
sudo docker run --rm --runtime=nvidia --gpus all ubuntu nvidia-smi
```

Expected result:

- the container can see the GPU
- `nvidia-smi` from inside the container matches the host driver stack closely enough to run GPU workloads

## 5. Prepare the deployment directory

The production workflow assumes the repository exists on the host at `/opt/local-assistant`.

Create the directory and hand ownership to the deploy user:

```bash
sudo mkdir -p /opt/local-assistant
sudo chown -R "$USER":"$USER" /opt/local-assistant
```

If this is the first checkout:

```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
git clone git@github.com:dqdp/JasperClaw.git /opt/local-assistant
```

If the checkout already exists:

```bash
cd /opt/local-assistant
git fetch --tags
git status --short
```

## 6. Prepare environment files

The current deployment path uses two local operator-managed files:

- root compose env file: `/opt/local-assistant/.env`
- runtime service env file: `/opt/local-assistant/infra/env/app.env`

Create them from the committed templates:

```bash
cd /opt/local-assistant
cp infra/env/prod.example.env .env
cp infra/env/app.example.env infra/env/app.env
```

Edit `.env` and set at minimum:

```env
GHCR_OWNER=dqdp
APP_VERSION=<immutable-image-tag>
DOMAIN=<production-domain>
INTERNAL_OPENAI_API_KEY=<strong-random-secret>
WEBUI_SECRET_KEY=<strong-random-secret>
POSTGRES_PASSWORD=<strong-random-secret>
```

Edit `infra/env/app.env` and set at minimum:

```env
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_CHAT_MODEL=<required-chat-model>
OLLAMA_FAST_CHAT_MODEL=<required-fast-chat-model>
MEMORY_ENABLED=false
```

If you enable memory, set the embedding model explicitly too:

```env
MEMORY_ENABLED=true
OLLAMA_EMBED_MODEL=<required-embedding-model>
```

Important:

- `OLLAMA_CHAT_MODEL` must be set explicitly
- `OLLAMA_FAST_CHAT_MODEL` should also be set explicitly in production, even though the app can default it internally
- `OLLAMA_EMBED_MODEL` must be set if `MEMORY_ENABLED=true`
- deployment now auto-pulls missing Ollama models based on these values

## 7. Log in to GHCR on the host

The host must be able to pull the published images:

```bash
echo '<GHCR_PULL_TOKEN>' | docker login ghcr.io -u '<GHCR_PULL_USER>' --password-stdin
```

If you use the GitHub Actions deploy workflow, the same login happens inside the remote SSH session. This manual login step is still useful for the first bootstrap and for validating image access before automation is involved.

## 8. Validate rendered Compose config before first deploy

Render the production config once before pulling images:

```bash
cd /opt/local-assistant
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml config >/tmp/local-assistant.compose.rendered.yaml
```

Review the rendered config if needed:

```bash
sed -n '1,220p' /tmp/local-assistant.compose.rendered.yaml
```

Minimum things to confirm:

- the expected image tags are selected
- `GHCR_OWNER` and `APP_VERSION` resolved correctly
- `ollama` is present
- `agent-api` reads `infra/env/app.env`
- the prod overlay adds the NVIDIA GPU reservation for `ollama`

## 9. Run the first deployment manually

For the first bootstrap, run the production rollout manually on the host before relying only on GitHub Actions:

```bash
cd /opt/local-assistant
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml pull
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml up -d postgres ollama stt-service tts-service
COMPOSE_OVERRIDE_FILE=infra/compose/compose.prod.yml bash infra/scripts/ensure-ollama-models.sh
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml run --rm --no-deps agent-api python -m app.cli migrate
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml up -d --remove-orphans agent-api open-webui caddy
COMPOSE_OVERRIDE_FILE=infra/compose/compose.prod.yml bash infra/scripts/smoke.sh
```

What this does:

- pulls pinned images from GHCR
- starts storage, inference, and speech dependencies
- ensures all configured Ollama models exist locally
- applies database migrations before serving traffic
- starts the user-facing services
- executes automated smoke validation

## 10. Validate the deployed stack

Check container state:

```bash
cd /opt/local-assistant
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml ps
```

Inspect logs if needed:

```bash
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml logs --tail=100 postgres ollama agent-api open-webui caddy
```

The automated smoke script validates:

- host-local reverse proxy response through Caddy
- `agent-api` `/readyz`
- `GET /v1/models`
- a basic `POST /v1/chat/completions` request through the canonical backend path

For the broader checklist, continue with [smoke-tests.md](./smoke-tests.md).

## 11. Enable GitHub Actions production deployment

The production workflow in `.github/workflows/deploy-prod.yml` expects:

- the repository checkout to exist at `/opt/local-assistant`
- Docker and NVIDIA runtime already working on the host
- the environment files to be present on the host
- these GitHub Actions secrets configured:
  - `PROD_HOST`
  - `PROD_USER`
  - `PROD_SSH_KEY`
  - `GHCR_PULL_TOKEN`
  - `GHCR_PULL_USER` or a valid default to `github.repository_owner`

After the host is bootstrapped, subsequent rollouts should normally happen through the deploy workflow rather than by hand.

## 12. Troubleshooting

### `nvidia-smi` fails on the host

Check:

- the driver installation actually completed
- the host was rebooted after driver installation
- Secure Boot did not block driver loading

Useful commands:

```bash
nvidia-smi
lsmod | grep nvidia
dmesg | tail -n 100
```

### GPU works on host but not inside containers

Check:

- `nvidia-container-toolkit` is installed
- `sudo nvidia-ctk runtime configure --runtime=docker` was run
- Docker was restarted afterward

Useful commands:

```bash
sudo systemctl status docker --no-pager
sudo cat /etc/docker/daemon.json
sudo docker run --rm --runtime=nvidia --gpus all ubuntu nvidia-smi
```

### `agent-api` readiness fails with `runtime_model_unavailable`

This means Ollama is up but the configured model is missing locally.

Run:

```bash
cd /opt/local-assistant
COMPOSE_OVERRIDE_FILE=infra/compose/compose.prod.yml bash infra/scripts/ensure-ollama-models.sh
```

Then re-check:

```bash
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml logs --tail=100 ollama agent-api
```

### GHCR pulls fail

Check:

- token scope allows package read access
- the token matches the image namespace in `GHCR_OWNER`
- the host is logged in to `ghcr.io`

Re-run:

```bash
echo '<GHCR_PULL_TOKEN>' | docker login ghcr.io -u '<GHCR_PULL_USER>' --password-stdin
```

## Post-bootstrap expected outcome

The host should now be able to:

- receive a deploy over SSH
- pull images from GHCR
- run the full Compose stack
- start a GPU-backed `ollama` container
- keep internal services private
- expose only the reverse proxy publicly

## References

The package-install steps above were aligned to these current official sources:

- Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
- Docker Linux post-install steps: https://docs.docker.com/engine/install/linux-postinstall/
- Ubuntu Server NVIDIA driver installation: https://documentation.ubuntu.com/server/how-to/graphics/install-nvidia-drivers/
- NVIDIA Container Toolkit install guide: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
- NVIDIA sample workload validation: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/sample-workload.html
