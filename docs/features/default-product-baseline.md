# Default Product Baseline Plan

## Purpose

Describe the next planned product baseline after MVP sign-off.

This document is intentionally forward-looking.
It captures intended default behavior and implementation sequencing, not the
current repository truth.

## Current repository truth

Today the repository baseline is still text-first:

- the default startup does not enable voice
- Spotify support is limited to `spotify-search`, `spotify-play`,
  `spotify-pause`, and `spotify-next`
- Telegram exists as an ingress channel, not yet as a narrow outbound typed
  tool for normal user requests
- Telegram command routing is currently limited to `/help`, `/status`, and
  `/ask`

This means the current default startup is not yet a batteries-included product
baseline for voice plus external actions.

## Chosen direction

The next product baseline should be the default system startup, not a separate
opt-in profile.

The intended first-run user experience is documented in
`docs/features/first-run-experience.md`.
The intended transition into real-provider mode is documented in
`docs/runbooks/default-baseline-onboarding.md`.
Detailed Spotify auth bootstrap is documented in
`docs/runbooks/spotify-auth-bootstrap.md`.
Detailed user-facing discovery and status behavior is documented in
`docs/features/capability-discovery.md`.
The implementation-first test order is documented in
`docs/features/default-product-baseline-tdd-checklist.md`.

Planned user-visible behavior:

- e2e voice interaction works on first startup
- the assistant can discover what it knows how to do
- the assistant can invoke baseline Spotify actions by voice
- the assistant can invoke baseline Telegram send actions by voice
- Telegram bot command routing stays intentionally minimal in v1 and is not a
  second Spotify command surface

## Constraints and hidden assumptions

- `agent-api` remains the only canonical orchestration and policy boundary
- no new public tool HTTP surface is introduced
- the default startup may include demo adapters or capability markers, but the
  real provider path must preserve the same typed tool contract
- the first real-provider baseline assumes a single self-hosted household
  rather than multi-user provider bindings
- Telegram assistant access must stay inside an operator-managed trusted chat
  boundary
- Telegram scope must stay narrow: alias-based outbound send only, not
  arbitrary chat discovery, history access, or unrestricted messaging
- no command or voice path may bypass the same policy, audit, and request
  correlation rules used by the text path

## Non-goals

- arbitrary Telegram chat access
- general Telegram inbox or history management
- broad workflow automation
- replacing the typed tools boundary with raw provider calls
- building the whole design around deprecated Spotify recommendation endpoints

## Spotify API facts that constrain the plan

Stable Spotify capabilities relevant to this baseline:

- create a playlist
- add tracks to a playlist
- start playback for a playlist context

Important constraints:

- real playlist mutation and playback control require user-scoped OAuth rather
  than `client_credentials`
- the chosen baseline direction is `Authorization Code + refresh token` for a
  single household-owned Spotify account
- playback control depends on a Spotify Premium user and an active playback
  device
- an active playback device means a Spotify Connect target already available to
  the account, such as an open phone, desktop client, or Web Player session
- Spotify's recommendations endpoints are currently deprecated, so
  recommendation-assisted playlist generation may exist only as an optional
  helper path, not the only baseline strategy

Recommended baseline stance:

- treat playlist CRUD plus explicit playback as the stable real-provider target
- treat recommendation-assisted generation as optional and replaceable

## Chosen design decisions

These decisions are now part of the intended baseline plan.

- provider ownership model: one self-hosted household account, not per-user or
  per-chat provider bindings
- Spotify auth model: `Authorization Code + refresh token`
- playback prerequisite: require an already active playback device in the first
  slice instead of adding automatic device transfer logic
- user-facing Spotify surface should be intent-level (`play playlist`, `start
  station`, `pause`, `next`, `list playlists`), not raw playlist CRUD verbs
- recommendation-assisted station building may exist only as an optional helper
  path
- Telegram free chat remains deny-by-default for model-driven external effects
- Telegram slash commands get a narrow allowlisted exception for approved typed
  capabilities
- alias registry should live in a small operator-managed file, not an env blob
  or new database mapping
- trusted Telegram chats should live in the same household config file as alias
  metadata
- voice-driven `telegram-send` should require confirmation
- slash-command `/send` may execute immediately because it is already explicit

Detailed voice confirmation semantics are documented in
`docs/features/telegram-send-confirmation.md`.

## Three-layer baseline model

The baseline should be described through three layers instead of leaking raw
provider verbs into the user-facing contract.

### 1. User-facing intents

This is the product surface the user should experience.

Discovery and help:

- "what can you do?"
- "what bot commands are available?"
- "what aliases do I have?"
- "what Spotify actions do you support?"
- "what playlists do I have?"

Spotify control:

- play a named playlist
- start a station by genre
- start a station by similarity to an artist or track
- start a station by mood or intent such as focus or energy
- pause playback
- skip to the next track
- list available playlists

Detailed user-facing station semantics are documented in
`docs/features/spotify-station-behavior.md`.

Telegram actions:

- send a message to a configured alias
- list configured aliases
- describe the meaning of a configured alias

Telegram bot commands:

- `/help`
- `/status`
- `/ask <message>`
- `/aliases`
- `/send <alias> <text>`

V1 bot-command non-goal:

- no Spotify playback or station-control commands through the Telegram bot

### 2. Internal typed capabilities

This is the stable orchestration boundary inside `agent-api`.

User-facing capabilities:

- `capabilities-help`
- `spotify-list-playlists`
- `spotify-play-playlist`
- `spotify-start-station`
- `spotify-pause`
- `spotify-next`
- `telegram-list-aliases`
- `telegram-send`

Internal helper capabilities:

- `spotify-search`
- `spotify-create-playlist`
- `spotify-add-to-playlist`

The helper capabilities exist to support station-building and playlist-backed
execution paths.
They are not the primary user-facing contract.

### 3. Provider adapters

This is where Spotify and Telegram API details live.

- Spotify playlist CRUD and playback stay provider-specific implementation
  details
- Spotify recommendations may be used opportunistically, but never as the only
  foundation for the product contract
- Telegram alias resolution and outbound send stay bounded by operator-managed
  configuration

## Planned baseline surface

### Voice path

- default startup enables the supported CPU voice profile
- spoken requests flow through `STT -> agent-api -> tools -> TTS`
- voice remains converged with the same memory, audit, and policy path as text

### Planned user-facing capability surface

- `capabilities-help`
- `spotify-list-playlists`
- `spotify-play-playlist`
- `spotify-start-station`
- `spotify-pause`
- `spotify-next`
- `telegram-list-aliases`
- `telegram-send`

### Planned helper capability surface

- `spotify-search`
- `spotify-create-playlist`
- `spotify-add-to-playlist`

### Telegram send scope

`telegram-send` should remain intentionally small:

- `telegram-send(alias, text)`
- alias values come from explicit operator-managed file-based configuration
- unknown aliases fail validation
- the target chat must resolve from household-owned alias configuration rather
  than free-form user input

`telegram-list-aliases` should expose only the configured alias names and short
descriptions needed for user discovery.

### Trusted Telegram chats

Telegram assistant access should be limited to a small operator-managed list of
trusted household chats.

Rules:

- unknown chats do not get the full assistant path
- unknown chats may receive only a bounded local rejection such as
  "chat not authorized"
- trusted chats may use `/ask`, `/aliases`, `/send`, `/help`, and `/status`
- trusted-chat configuration should live in the same household config file as
  alias metadata

### Telegram command surface

Planned deterministic bot commands:

- `/help`
- `/status`
- `/ask <message>`
- `/aliases`
- `/send <alias> <text>`

Command-policy rule:

- ordinary Telegram free chat remains deny-by-default for model-driven external
  effects
- the slash-command path gets a narrow allowlisted exception for approved
  baseline capabilities only
- v1 keeps the bot-command surface minimal and household-oriented rather than
  turning the bot into a Spotify command controller

Playlist creation should remain an internal helper path in the first baseline
slice.
It does not need a dedicated slash command or primary voice intent.

## Demo-to-real capability model

True out-of-the-box real Spotify and Telegram actions are impossible without
external credentials and user-owned destinations.

The baseline therefore needs one explicit capability model:

- demo-capable on first startup
- real-provider capable after credential onboarding
- explicitly unconfigured when a capability cannot be exercised even in demo
  mode

The typed tool IDs and orchestration path must stay the same across both modes.
Only the adapter mode should change.

Discovery and status paths should be able to report whether a capability is in
`demo`, `real`, or `unconfigured` state.

Recommended reporting surface:

- voice and chat discovery answers
- Telegram `/status`
- local capability registry inside `agent-api`

## Confirmation and safety rules

- voice-driven `telegram-send` requires explicit confirmation before execution
- slash-command `/send` executes immediately after validation
- normal playlist playback requests may execute immediately
- station-building requests may execute immediately
- Telegram free chat must not gain model-driven outbound side effects just
  because slash commands exist

## Household configuration shape

The preferred v1 operator contract is one small household config file rather
than several unrelated env blobs.

The configuration contract itself is documented in
`docs/ops/household-config.md`.
The explicit demo-household path is documented in
`docs/ops/demo-household-config.md`.

Conceptual shape:

```toml
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
```

This keeps trusted-chat policy, alias resolution, and local discovery in one
operator-managed place.

## Recommended execution order

1. Define capability-state semantics for `demo`, `real`, and `unconfigured`.
2. Add the correct Spotify auth model for state-changing actions.
3. Add the user-facing Spotify playback and station capabilities plus their
   helper paths.
4. Add trusted-chat Telegram send and alias discovery.
5. Keep Telegram bot commands minimal under the narrow allowlisted exception.
6. Add smoke coverage for the ordinary default startup.
7. Flip the default startup contract from text-first to voice-first.

## Implementation workstreams

1. Define the capability-state contract and local discovery surface.
2. Add real Spotify auth handling for user-scoped OAuth instead of treating
   `client_credentials` as sufficient for state-changing actions.
3. Add user-facing Spotify playlist playback, station start, and playlist-list
   capabilities.
4. Add the internal helper capabilities needed for stable playlist-backed
   execution.
5. Evaluate recommendation-assisted playlist generation only as an optional
   helper path that does not make deprecated Spotify endpoints baseline-
   critical.
6. Add trusted-chat Telegram send and alias discovery.
7. Keep Telegram bot commands minimal under the narrow allowlisted exception.
8. Add canonical end-to-end smoke for voice to Spotify and voice to Telegram
   send flows under the new default startup, with explicit `demo` versus
   `real-provider` expectations.
9. Flip the default startup contract from text-first to voice-first.

## Smoke matrix

### Mandatory deterministic smoke

- default startup boots with the voice path enabled
- capability discovery works
- Spotify baseline intents work in `demo` or fake mode
- Telegram send and alias discovery work in `demo` or fake mode
- trusted and untrusted Telegram chat behavior is validated

### Optional real-provider smoke

- real Spotify auth flow is configured
- active playback device and Premium prerequisites are visible
- real Telegram send succeeds
- this smoke remains opt-in rather than mandatory CI because it depends on live
  third-party state

## Acceptance criteria for this expansion block

- the ordinary default startup enables the supported voice profile
- users can discover commands, aliases, and baseline capabilities without
  guessing low-level provider verbs
- voice can reach at least one Spotify action and one Telegram send action
  through the canonical `agent-api` path
- Spotify playback uses a correct user-scoped auth model rather than
  `client_credentials`
- playlist playback and station start are supported in the real Spotify path
- any playlist CRUD used for station building remains an internal helper rather
  than the primary user-facing contract
- recommendation-assisted playlist generation is documented as optional rather
  than baseline-critical
- Telegram outbound actions remain limited to trusted chats and configured
  aliases
- Telegram slash commands route to the same typed capability layer through a
  narrow allowlisted exception instead of a broad privileged bypass
- ordinary Telegram free chat remains deny-by-default for model-driven external
  effects
- Telegram bot commands remain limited to the minimal household helper surface
  and do not become a Spotify command center in v1
- smoke coverage proves the default startup contract rather than an opt-in
  specialty profile
