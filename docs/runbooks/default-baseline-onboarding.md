# Runbook: Default Baseline Onboarding

## Purpose

Define the intended operator path from the ordinary first startup to a real
single-household baseline.

This runbook answers one operational question:

- how does a default startup move from `demo` or `unconfigured` capability
  states into a usable real household setup?

## Scope

Applies to the planned default voice-first baseline with:

- real Spotify playback and station support
- real household Telegram send and alias discovery
- one operator-managed household configuration

## Forward-looking note

This runbook is intentionally forward-looking.

It documents the accepted onboarding target for the default baseline, not the
current repository truth in every detail.

In particular:

- the chosen Spotify baseline is `Authorization Code + refresh token`
- the current repository configuration surface still exposes
  `SPOTIFY_ACCESS_TOKEN` and client credentials scaffolding
- the eventual real baseline should converge on the accepted auth model without
  changing the typed capability contract

## Non-goals

- deep provider-specific troubleshooting
- multi-user identity or per-chat provider bindings
- a browser-by-browser walkthrough for every Spotify developer-console step
- arbitrary Telegram contact discovery

## Related contracts

- `docs/features/default-product-baseline.md`
- `docs/runbooks/spotify-auth-bootstrap.md`
- `docs/features/first-run-experience.md`
- `docs/features/capability-planning.md`
- `docs/ops/demo-household-config.md`
- `docs/ops/household-config.md`
- `docs/ops/configuration.md`

## Target outcome

Onboarding is complete when the default startup can truthfully report:

- voice interaction is available
- Spotify playlist discovery and playback are `real`
- Spotify station generation is `real`
- Telegram alias discovery is `real`
- Telegram send is `real`

and when those claims are validated through one bounded real-provider check per
capability family.

## Preconditions

The operator should have:

- a running default startup stack
- access to the operator-managed env files derived from `infra/env/*.example.env`
- access to the operator-managed household config file
- a Spotify Premium account intended to act as the single household account
- a Spotify Connect playback target that can be made active
- a Telegram bot token for `telegram-ingress`
- at least one trusted Telegram chat and at least one target chat for alias
  delivery

## Canonical onboarding sequence

The preferred sequence is:

1. verify the plain first-run state
2. connect Spotify
3. define household Telegram config
4. verify trusted Telegram ingress
5. verify real household actions

This order keeps failure diagnosis narrow.

## Step 1: Verify first-run state

Before real-provider setup, confirm the current startup state honestly.

Expected checks:

- voice path responds
- help or status can disclose `demo`, `real`, and `unconfigured`
- Spotify and Telegram are not silently presented as real if they are not

If the stack cannot describe its own current capability state, stop here.
The baseline is not ready for real onboarding.

## Step 2: Connect Spotify

### Intended auth model

The accepted real-provider baseline is:

- one household-owned Spotify account
- `Authorization Code + refresh token`

The system should not rely on `client_credentials` for real playback or
playlist mutation.

### Operator steps

1. Register the Spotify application and configure the redirect URI expected by
   the assistant stack.
2. Place the Spotify client configuration in the operator-managed runtime env.
3. Complete the user authorization flow for the household Spotify account.
4. Persist the resulting refresh-capable authorization state in the runtime's
   chosen secret/config storage.
5. Restart or reload the affected runtime if required by the implementation.

### Spotify-specific prerequisites

Real playback also requires:

- Spotify Premium
- an already active playback device

An active playback device means a Spotify Connect target already visible to the
household account, such as:

- a phone with Spotify open
- a desktop Spotify client
- an active Web Player session

### Expected post-step state

After Spotify onboarding:

- `spotify-list-playlists` is `real`
- `spotify-play-playlist` is `real`
- `spotify-start-station` is `real`
- playback failures caused by missing active device are treated as prerequisite
  failures, not configuration failures

## Step 3: Define household Telegram config

Create the operator-managed household config file described in
`docs/ops/household-config.md`.

Minimum shape:

```toml
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.home]
chat_id = 111111111
description = "Home chat"
```

Required outcomes:

- trusted chats are explicit
- at least one alias exists
- alias descriptions are suitable for user-facing discovery

If the file is missing or invalid, Telegram household capabilities must remain
`unconfigured`.

## Step 4: Verify trusted Telegram ingress

Ensure the Telegram bot itself is configured and reachable through the normal
`telegram-ingress` path.

This includes:

- valid `TELEGRAM_BOT_TOKEN`
- webhook or polling mode configured correctly
- trusted chat IDs matching the intended household bot chat

Trusted Telegram chats should be able to use:

- `/help`
- `/status`
- `/ask`
- `/aliases`
- `/send`

Untrusted chats must not reach the full assistant path.

## Step 5: Verify real household actions

After both provider families are configured, verify one bounded action from
each side.

Recommended checks:

### Spotify

- ask for playlist discovery
- play a known playlist
- start a station from a simple seed such as genre or mood

### Telegram

- ask for alias discovery from a trusted chat
- send one bounded test message through `telegram-send`

### Voice

- ask by voice for one Spotify action
- ask by voice for one Telegram send action and confirm it explicitly

## Expected capability-state transitions

The desired transition shape is:

- first startup:
  - voice: `real`
  - Spotify: `demo`, `real`, or `unconfigured`
  - Telegram send: usually `unconfigured`
- after Spotify onboarding:
  - Spotify playback and station: `real`
- after valid household Telegram setup:
  - Telegram alias discovery and send: `real`

Runtime outages do not change these states to `unconfigured`.
They are operational failures, not onboarding-state transitions.

## Failure classification

The onboarding contract should distinguish these cases:

### Configuration failure

Examples:

- missing Spotify auth material
- missing or invalid `household.toml`
- missing Telegram bot token

Expected surface:

- capability is `unconfigured`

### Prerequisite failure

Examples:

- Spotify is connected but no active playback device exists
- request comes from an untrusted Telegram chat

Expected surface:

- capability remains configured
- the request fails with a bounded prerequisite or authorization message

### Runtime failure

Examples:

- provider timeout
- temporary upstream outage

Expected surface:

- capability remains `real`
- the request fails as a transient runtime problem, not as onboarding drift

## Operator checklist

Use this checklist when moving a stack to the real baseline:

- default startup boots successfully
- voice interaction works
- capability disclosure works
- Spotify auth material is configured
- Spotify household account has completed authorization
- an active playback device is available
- household config file exists and validates
- trusted Telegram chat IDs are correct
- at least one alias resolves correctly
- trusted Telegram bot commands work
- one real Spotify action succeeds
- one real Telegram send succeeds

## Acceptance criteria

The onboarding contract is acceptable when:

- an operator can tell which steps convert `unconfigured` into `real`
- Spotify auth, household config, and trusted-chat setup are clearly separated
- missing active playback device is treated as a prerequisite gap, not a bad
  configuration
- Telegram send cannot silently become available without explicit household
  config
- the runbook gives one bounded verification step for Spotify, Telegram, and
  voice
