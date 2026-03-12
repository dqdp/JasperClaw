# Configuration

## Purpose

Define the canonical v1 configuration surface for `local-assistant`.

This document specifies:

- which variables exist
- which service owns them
- which ones are required
- which ones are optional or feature-gated
- where current scaffold gaps still exist

## Current configuration sources

Today the repository has three relevant configuration layers:

### 1. Root compose substitution

Primary template:

- `.env.example`

This layer feeds:

- Compose variable substitution
- Caddy domain configuration
- image tag selection
- some service environment values injected directly in `compose.yml`

### 2. Service env files

Recommended templates:

- `infra/env/app.example.env`
- `infra/env/prod.example.env`

These correspond to the `env_file` pattern already referenced by `infra/compose/compose.yml`.

### 3. Hardcoded compose defaults

Some settings are currently pinned directly in `infra/compose/compose.yml`, for example:

- Open WebUI feature flags
- Open WebUI model IDs
- container image names

Those values still count as part of the configuration surface even when they are not yet externalized.

## Current scaffold note

The repository now contains committed `infra/env/*.example.env` templates that match the `env_file` pattern used by `infra/compose/compose.yml`.

The accepted v1 baseline is:

- keep `.env.example` as the root compose-substitution template
- add `infra/env/*.example.env` as service-oriented env templates
- treat `infra/env/app.env` and `infra/env/prod.env` as local, uncommitted operator files derived from the examples

## Configuration ownership model

### Root deployment configuration

Owned by:

- operator or deploy environment

Examples:

- image version selection
- domain
- shared internal credentials
- database password

### `agent-api` runtime configuration

Owned by:

- `agent-api`

Examples:

- runtime endpoints
- model profile targets
- embeddings target
- feature toggles
- tool provider credentials

### Speech runtime configuration

Owned by:

- `stt-service`
- `tts-service`

Examples:

- default speech model
- default voice

### UI shell configuration

Owned by:

- `Open WebUI`

Examples:

- WebUI secret
- backend API URL
- OpenAI-compatible backend credential

## Variable catalog

## Root deployment and compose variables

### `GHCR_OWNER`

Required: yes

Used by:

- `infra/compose/compose.yml`

Purpose:

- namespace for published container images

Example:

```env
GHCR_OWNER=your-github-user-or-org
```

### `APP_VERSION`

Required: yes

Used by:

- `infra/compose/compose.yml`
- deployment workflows and operator rollouts

Purpose:

- pin the image tag to deploy

Example:

```env
APP_VERSION=dev
```

### `DOMAIN`

Required: yes for proxied deployments

Used by:

- `infra/caddy/Caddyfile`

Purpose:

- public host name served by Caddy

### `INTERNAL_OPENAI_API_KEY`

Required: yes

Used by:

- `Open WebUI -> agent-api` authentication

Purpose:

- trusted internal client credential for the UI shell

Notes:

- this is not an end-user credential
- it must not be exposed publicly
- it is enforced on all `/v1/*` routes in `agent-api`
- it is not required for `GET /healthz` or `GET /readyz`
- it must match the bearer token configured in trusted internal clients such as `Open WebUI`
- placeholder values such as `change-me` are treated as not configured and keep `/v1/*` unavailable

### `WEBUI_SECRET_KEY`

Required: yes

Used by:

- `Open WebUI`

Purpose:

- secret for UI session and application security

### `POSTGRES_PASSWORD`

Required: yes

Used by:

- `postgres`
- `agent-api`

Purpose:

- password for the assistant database

## `agent-api` runtime variables

These values should live in `infra/env/app.env`, derived from `infra/env/app.example.env`.

### `OLLAMA_BASE_URL`

Required: yes

Used by:

- `agent-api`

Purpose:

- base URL for the internal `Ollama` runtime

### `OLLAMA_CHAT_MODEL`

Required: yes

Used by:

- `agent-api`

Purpose:

- default runtime target for the primary chat profile mapping

Notes:

- public profile IDs remain `assistant-v1` and `assistant-fast`
- this value is an internal runtime target, not a public contract
- deployment automation uses this value to ensure the required Ollama model exists locally before serving traffic

### `OLLAMA_FAST_CHAT_MODEL`

Required: no

Used by:

- `agent-api`

Purpose:

- explicit runtime target for the lower-latency public profile mapping

Notes:

- defaults to `OLLAMA_CHAT_MODEL` if unset
- production deployment should still set this explicitly in `infra/env/app.env` so model provisioning is deterministic

### `OLLAMA_TIMEOUT_SECONDS`

Required: no

Used by:

- `agent-api`

Purpose:

- timeout budget for runtime readiness checks and chat calls

### `OLLAMA_EMBED_MODEL`

Required: no until retrieval is enabled

Used by:

- `agent-api`

Purpose:

- embedding model for memory and future document retrieval

Notes:

- when `MEMORY_ENABLED=true`, production deployment should set this explicitly so local model provisioning can ensure it is present before traffic

### `MEMORY_ENABLED`

Required: no

Used by:

- `agent-api`

Purpose:

- enable or disable Memory Slice 1 retrieval and materialization behavior

Notes:

- defaults to `false`
- when `false`, chat proceeds without retrieval even if `OLLAMA_EMBED_MODEL` is set

### `MEMORY_TOP_K`

Required: no

Used by:

- `agent-api`

Purpose:

- maximum number of memory hits included in prompt assembly

Notes:

- defaults to `3`

### `MEMORY_MIN_SCORE`

Required: no

Used by:

- `agent-api`

Purpose:

- minimum similarity threshold for memory retrieval inclusion

Notes:

- defaults to `0.35`

### `DATABASE_URL`

Required: no if component Postgres variables are provided

Used by:

- `agent-api`

Purpose:

- explicit database DSN override for `agent-api`

Notes:

- if set, it takes precedence over component Postgres variables

### `POSTGRES_HOST`

Required: yes unless `DATABASE_URL` is set

Used by:

- `agent-api`

Purpose:

- hostname for canonical assistant storage

### `POSTGRES_PORT`

Required: yes unless `DATABASE_URL` is set

Used by:

- `agent-api`

Purpose:

- port for canonical assistant storage

### `POSTGRES_DB`

Required: yes unless `DATABASE_URL` is set

Used by:

- `agent-api`

Purpose:

- database name for canonical assistant storage

### `POSTGRES_USER`

Required: yes unless `DATABASE_URL` is set

Used by:

- `agent-api`

Purpose:

- database user for canonical assistant storage

### `LOG_LEVEL`

Required: no

Used by:

- `agent-api`

Purpose:

- minimum emitted severity for structured JSON logs

### `SEARCH_API_KEY`

Required: no until search adapters are enabled

Used by:

- in-process tools integration layer inside `agent-api`

Purpose:

- credential for the configured search provider

### `SEARCH_BASE_URL`

Required: no until search adapters are enabled

Used by:

- in-process tools integration layer inside `agent-api`

Purpose:

- provider endpoint for search requests

Notes:

- current `web-search` adapter expects `GET {SEARCH_BASE_URL}/search?q=<query>&limit=<k>`

### `WEB_SEARCH_ENABLED`

Required: no

Used by:

- `agent-api`

Purpose:

- enable or disable `web-search` prompt augmentation inside the chat path

Notes:

- defaults to `false`
- when `false`, `metadata.web_search=true` is treated as a denied optional tool request

### `WEB_SEARCH_TOP_K`

Required: no

Used by:

- `agent-api`

Purpose:

- maximum number of normalized search results injected into the runtime prompt

Notes:

- defaults to `3`

### `WEB_SEARCH_TIMEOUT_SECONDS`

Required: no

Used by:

- `agent-api`

Purpose:

- timeout budget for outbound `web-search` provider calls

Notes:

- defaults to `5`

### `SPOTIFY_CLIENT_ID`

Required: no until Spotify adapters are enabled

Used by:

- in-process tools integration layer inside `agent-api`

### `SPOTIFY_CLIENT_SECRET`

Required: no until Spotify adapters are enabled

Used by:

- in-process tools integration layer inside `agent-api`

### `SPOTIFY_REDIRECT_URI`

Required: no until Spotify adapters are enabled

Used by:

- in-process tools integration layer inside `agent-api`

### `SPOTIFY_ACCESS_TOKEN`

Required: no until Spotify adapters are enabled

Used by:

- in-process tools integration layer inside `agent-api`

Purpose:

- direct OAuth token override used for Spotify playback/search requests

Notes:

- Spotify tools require either a static access token or both `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`.
- static token mode is explicit and does not auto-refresh.

### `SPOTIFY_BASE_URL`

Required: no until Spotify adapters are enabled

Used by:

- in-process tools integration layer inside `agent-api`

Notes:

- defaults to `https://api.spotify.com`

### `SPOTIFY_TIMEOUT_SECONDS`

Required: no

Used by:

- in-process tools integration layer inside `agent-api`

Purpose:

- timeout budget in seconds for Spotify API calls

Notes:

- defaults to `5`

### `SPOTIFY_SEARCH_TOP_K`

Required: no

Used by:

- in-process tools integration layer inside `agent-api`

Purpose:

- maximum number of Spotify tracks injected into the runtime context

Notes:

- defaults to `3`

## Telegram ingress variables

### `TELEGRAM_WEBHOOK_PATH`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- webhook route that receives Telegram updates

Notes:

- keep route narrow and stable for operator and firewall allowlisting
- examples in repo use `/telegram/webhook`

### `TELEGRAM_WEBHOOK_URL`

Required: no when polling fallback enabled

Used by:

- `telegram-ingress`

Purpose:

- absolute Telegram webhook target for automatic `setWebhook` registration during startup

Notes:

- when present, ingress runs in webhook mode and `TELEGRAM_POLLING_ENABLED` is ignored

### `TELEGRAM_WEBHOOK_SECRET_TOKEN`

Required: yes for Telegram-hosted webhook delivery

Used by:

- `telegram-ingress`

Purpose:

- constant-time compare secret token from header `X-Telegram-Bot-Api-Secret-Token`

Notes:

- this is a webhook authenticity guard, not a full auth for downstream user actions
- rotate this value with the bot token as part of the same security domain

### `TELEGRAM_BOT_TOKEN`

Required: yes once Telegram ingress is enabled

Used by:

- `telegram-ingress`

Purpose:

- Telegram Bot API authentication token

### `TELEGRAM_API_BASE_URL`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- base URL for Telegram Bot API

Notes:

- defaults to `https://api.telegram.org`

### `AGENT_API_BASE_URL`

Required: yes

Used by:

- `telegram-ingress`

Purpose:

- upstream `agent-api` endpoint for `/v1/chat/completions`

### `AGENT_API_KEY`

Required: yes

Used by:

- `telegram-ingress`

Purpose:

- bearer token for `agent-api` internal chat API

Notes:

- use the same value as `INTERNAL_OPENAI_API_KEY` unless a dedicated ingress key is required

### `TELEGRAM_POLLING_ENABLED`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- enable long-polling fallback when no webhook URL is configured

Notes:

- default is `false`
- set `true` only when `TELEGRAM_WEBHOOK_URL` is not configured

### `TELEGRAM_POLLING_TIMEOUT_SECONDS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- Telegram `getUpdates` long-poll timeout in seconds when polling mode is active

Notes:

- defaults to `30`

### `TELEGRAM_POLLING_BATCH_SIZE`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- maximum number of Telegram updates fetched per `getUpdates` poll cycle

Notes:

- defaults to `100`

### `TELEGRAM_RATE_LIMIT_WINDOW_SECONDS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- controls the sliding-window period for chat-level and global rate limits

Notes:

- defaults to `60`

### `TELEGRAM_RATE_LIMIT_PER_CHAT`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- maximum number of accepted Telegram messages allowed per chat within the window

Notes:

- defaults to `20`

### `TELEGRAM_RATE_LIMIT_GLOBAL`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- maximum number of accepted Telegram messages allowed across all chats within the window

Notes:

- defaults to `500`

### `TELEGRAM_MAX_INPUT_CHARS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- maximum size of incoming message text in characters before update is ignored

Notes:

- defaults to `4000`

### `TELEGRAM_ALLOWED_COMMANDS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- comma-separated allowlist for Telegram slash commands

Notes:

- when set, only matching commands are forwarded to `agent-api`
- matching is case-insensitive and supports commands with optional `@botname` suffix
- messages starting with `/` are considered commands; all others are treated as free-form text
- example: `/help,/status,/retry`
- defaults to disabled (empty), meaning no command filtering is enforced

### `TELEGRAM_ALERT_BOT_TOKEN`

Required: no unless alert relaying is enabled

Used by:

- `telegram-ingress`

Purpose:

- dedicated Telegram bot token used for operational alert delivery

### `TELEGRAM_ALERT_CHAT_IDS`

Required: no unless alert relaying is enabled

Used by:

- `telegram-ingress`

Purpose:

- comma-separated default Telegram chat IDs that receive accepted operational alerts and direct text alert payloads

### `TELEGRAM_ALERT_WARNING_CHAT_IDS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- comma-separated Telegram chat IDs that additionally receive `warning` and `critical` alert payloads

### `TELEGRAM_ALERT_CRITICAL_CHAT_IDS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- comma-separated Telegram chat IDs that additionally receive only `critical` alert payloads

### `TELEGRAM_ALERT_AUTH_TOKEN`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- shared secret token required in `X-Telegram-Alert-Token` header for `/telegram/alerts`

### `TELEGRAM_ALERT_API_BASE_URL`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- Telegram Bot API base URL for the alert bot

Notes:

- defaults to `https://api.telegram.org`

### `TELEGRAM_ALERT_SEND_RESOLVED`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- whether `resolved` Alertmanager-style payloads are delivered instead of being filtered by policy

Notes:

- defaults to `false`
- direct `text`/`message` alert payloads are not filtered by this setting

### `TELEGRAM_ALERT_RETRY_BACKOFF_SECONDS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- fixed backoff before retrying a retryable Telegram alert-delivery target from the durable outbox

Notes:

- defaults to `30`

### `TELEGRAM_ALERT_RETRY_POLL_SECONDS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- polling interval for the background worker that drains due Telegram alert deliveries from the durable outbox

Notes:

- defaults to `5`

### `TELEGRAM_ALERT_CLAIM_TTL_SECONDS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- lease TTL for an in-flight durable Telegram alert delivery before another worker may reclaim it

Notes:

- defaults to `30`

### `TELEGRAM_ALERT_MAX_ATTEMPTS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- maximum number of attempts per Telegram alert-delivery target before the target becomes terminally failed

Notes:

- defaults to `5`

### `TELEGRAM_ALERT_RETRY_WORKER_ENABLED`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- whether the background worker that drains durable Telegram alert retries is enabled

Notes:

- defaults to `true`

### `AGENT_API_MODEL`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- default runtime model used for Telegram user messages

Notes:

- defaults to `assistant-fast`

### `TELEGRAM_REQUEST_TIMEOUT_SECONDS`

Required: no

Used by:

- `telegram-ingress`

Purpose:

- request timeout for downstream API calls

Notes:

- defaults to `5`

## Speech-related variables

These remain part of the config surface even though real voice delivery comes after the text path stabilizes.

### `STT_BASE_URL`

Required: no until voice is enabled

Used by:

- `agent-api`

Purpose:

- location of `stt-service`

### `STT_MODEL`

Required: no until voice is enabled

Used by:

- `stt-service`

Purpose:

- default speech-to-text model selection

### `TTS_BASE_URL`

Required: no until voice is enabled

Used by:

- `agent-api`

Purpose:

- location of `tts-service`

### `TTS_DEFAULT_VOICE`

Required: no until voice is enabled

Used by:

- `tts-service`

Purpose:

- default text-to-speech voice selection

## Legacy or provisional variables

### `TOOLS_BASE_URL`

Status:

- legacy scaffold variable

Reason:

- accepted v1 architecture keeps the tools boundary in-process inside `agent-api`
- there is no canonical v1 need for a standalone tools base URL

Rule:

- do not treat this as part of the accepted v1 baseline

## Compose-pinned settings that still matter

The following are not currently sourced from env files, but are part of the effective configuration and should remain visible to operators:

- `OPENAI_API_BASE_URL=http://agent-api:8080/v1`
- `AUDIO_STT_OPENAI_API_BASE_URL=http://agent-api:8080/v1`
- `AUDIO_TTS_OPENAI_API_BASE_URL=http://agent-api:8080/v1`
- `TASK_MODEL_EXTERNAL=assistant-fast`
- `ENABLE_OLLAMA_API=False`
- `ENABLE_OPENAI_API=True`

## Required sets by deployment phase

### Core text path

Minimum required:

- `GHCR_OWNER`
- `APP_VERSION`
- `DOMAIN`
- `INTERNAL_OPENAI_API_KEY`
- `WEBUI_SECRET_KEY`
- `POSTGRES_PASSWORD`
- `OLLAMA_BASE_URL`
- `OLLAMA_CHAT_MODEL`

### Memory and retrieval

Additional recommended:

- `MEMORY_ENABLED`
- `MEMORY_TOP_K`
- `MEMORY_MIN_SCORE`
- `OLLAMA_EMBED_MODEL`

### Search and tool adapters

Additional required only if enabled:

- `SEARCH_API_KEY`
- `SEARCH_BASE_URL`

### Spotify adapters

Additional required only if enabled:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`
- `SPOTIFY_ACCESS_TOKEN` (for direct token mode)
- `SPOTIFY_BASE_URL` (to point to a non-default provider endpoint)
- `SPOTIFY_TIMEOUT_SECONDS` (if custom timeout is required)
- `SPOTIFY_SEARCH_TOP_K` (if non-default result limit is required)

### Telegram ingress

Additional required if enabled:

- `TELEGRAM_BOT_TOKEN`
- `AGENT_API_KEY`
- `TELEGRAM_WEBHOOK_SECRET_TOKEN` (required when webhook mode is used)
- `TELEGRAM_WEBHOOK_URL` (required when webhook mode is used)
- `TELEGRAM_POLLING_ENABLED` (required only when webhook URL cannot be configured)
- `TELEGRAM_RATE_LIMIT_*` values should be tuned for expected traffic and abuse tolerance
### Additional optional variable

- `TELEGRAM_ALLOWED_COMMANDS` (comma-separated command allowlist)

### Voice path

Additional required only if enabled:

- `STT_BASE_URL`
- `STT_MODEL`
- `TTS_BASE_URL`
- `TTS_DEFAULT_VOICE`

## Secret-handling rules

- secrets belong only to the service that directly uses them
- root `.env` files and `infra/env/*.env` files must not be committed
- example files must contain placeholders only
- external provider credentials must never be exposed to `Open WebUI`
- the internal OpenAI-style credential is shared only between `Open WebUI` and `agent-api`
- unauthenticated probes are limited to `healthz` and `readyz`

## Recommended file layout

Committed templates:

- `.env.example`
- `infra/env/app.example.env`
- `infra/env/prod.example.env`
- `infra/env/telegram.example.env`

Local operator files:

- `.env`
- `infra/env/app.env`
- `infra/env/prod.env`
- `infra/env/telegram.env`

## Example operator workflow

1. Copy `.env.example` to `.env`
2. Copy `infra/env/app.example.env` to `infra/env/app.env`
3. Copy `infra/env/prod.example.env` to `infra/env/prod.env` if using a production-specific split
4. Copy `infra/env/telegram.example.env` to `infra/env/telegram.env` if Telegram ingress is enabled
5. Fill in required secrets and runtime targets
6. Apply pending schema changes before serving traffic, for example `make migrate` locally or `docker compose ... run --rm agent-api python -m app.cli migrate` in deployment automation
7. Validate compose configuration before deploy, for example `docker compose --env-file .env -f infra/compose/compose.yml config`

## Follow-up work

Configuration should later be refined by:

- moving more hardcoded compose settings into explicit config when they become operationally significant
- documenting per-profile runtime mapping once the `agent-api` profile registry is implemented
- documenting feature flags for memory, tool adapters, and voice once those paths are real
