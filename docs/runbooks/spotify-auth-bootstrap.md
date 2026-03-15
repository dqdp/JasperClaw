# Runbook: Spotify Auth Bootstrap

## Purpose

Define the intended operator path for connecting the default baseline to the
real household Spotify account.

This runbook answers one operational question:

- how does the stack move from `demo` or `unconfigured` Spotify capabilities to
  the accepted real-provider auth model?

## Scope

Applies to the planned default product baseline with:

- `spotify-list-playlists`
- `spotify-play-playlist`
- `spotify-start-station`
- `spotify-pause`
- `spotify-next`

## Forward-looking note

This runbook is intentionally forward-looking.

It documents the accepted target auth model, not the current runtime
implementation in every detail.

Current scaffold truth:

- the repository still exposes `SPOTIFY_ACCESS_TOKEN`,
  `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, and `SPOTIFY_REDIRECT_URI`
  in `docs/ops/configuration.md`
- the current settings scaffold does not yet prove a full refresh-token-based
  bootstrap and storage path

Target baseline truth:

- the accepted real-provider model is `Authorization Code + refresh token`
- `client_credentials` is not sufficient for state-changing playback or helper
  playlist mutation

## Non-goals

- Spotify API troubleshooting beyond the baseline contract
- multi-user Spotify bindings
- exposing Spotify auth as a public user self-service feature
- keeping static `SPOTIFY_ACCESS_TOKEN` as the long-term real baseline

## Related contracts

- `docs/features/default-product-baseline.md`
- `docs/runbooks/default-baseline-onboarding.md`
- `docs/features/spotify-station-behavior.md`
- `docs/ops/configuration.md`

## Accepted auth model

The intended real baseline is:

- one household-owned Spotify account
- user-scoped `Authorization Code + refresh token`
- refresh-capable secret storage controlled by the operator/runtime

The real baseline should not depend on:

- `client_credentials`
- manually rotating short-lived access tokens
- per-user account selection in v1

## Ownership and trust boundary

The connected Spotify account is a household-level capability.

Implications:

- one operator-managed Spotify identity backs the baseline
- all household playback and station requests share that account
- token material is runtime configuration or secret state, not prompt context
- model output must never see or manipulate raw tokens

## Redirect ownership

The assistant stack should own one canonical redirect URI for the Spotify app.

Recommended baseline:

- one stable redirect URI controlled by the deployment
- one runtime component responsible for completing the auth-code exchange
- one secret/config storage path for the resulting refresh-capable auth state

The baseline should avoid ad hoc operator copy-paste of raw bearer tokens as
the steady-state model.

## Bootstrap sequence

The intended bootstrap flow is:

1. register the Spotify application
2. configure the canonical redirect URI
3. place client credentials in operator-managed runtime config
4. start the authorization flow for the household account
5. exchange the auth code for refresh-capable auth state
6. persist the resulting auth state in runtime secret/config storage
7. validate playlist discovery and playback

## Step 1: Register the Spotify application

The operator should create or select one Spotify application intended for the
household baseline.

Required outputs:

- client ID
- client secret
- one redirect URI matching the deployment

## Step 2: Configure runtime inputs

The runtime should receive:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`

These values belong to operator-managed configuration.

`SPOTIFY_ACCESS_TOKEN` may still exist as a current scaffold variable, but it
should not be treated as the long-term real baseline target.

## Step 3: Complete household authorization

The household Spotify account should complete the authorization flow against
the configured redirect URI.

Expected outcome:

- the runtime obtains refresh-capable auth state

The exact UX may vary, but the contract should preserve:

- one explicit operator-controlled account binding
- no silent account switching
- no dependence on manual repeated access-token pasting

## Step 4: Persist refresh-capable auth state

The resulting auth state should be stored in operator-managed secret or config
storage.

Required properties:

- durable across restarts
- not embedded in prompts
- not logged in plaintext
- rotatable without changing the typed capability contract

The exact storage mechanism may vary, but the product contract assumes one
stable refresh-capable path rather than ephemeral session-only state.

## Step 5: Validate the connected account

After auth bootstrap, the operator should validate:

- playlist discovery works
- playlist playback works when prerequisites are met
- station start works through the same account binding

These checks should use bounded real actions, not deep provider debugging.

## Prerequisites after auth

Successful auth bootstrap is necessary but not sufficient for playback.

Real playback still depends on:

- Spotify Premium
- an already active playback device

These are prerequisite failures, not auth-bootstrap failures.

## Failure classification

The auth bootstrap contract should distinguish:

### Missing auth material

Examples:

- no client ID
- no client secret
- no redirect URI

Expected capability state:

- Spotify capabilities remain `unconfigured`

### Bootstrap incomplete

Examples:

- auth flow never completed
- no refresh-capable state persisted

Expected capability state:

- Spotify capabilities remain `unconfigured`

### Playback prerequisite missing

Examples:

- no active playback device
- Spotify account lacks Premium playback capability

Expected capability state:

- Spotify capabilities remain `real`

Expected request behavior:

- fail with a bounded prerequisite message

### Runtime failure

Examples:

- temporary provider timeout
- transient upstream error

Expected capability state:

- Spotify capabilities remain `real`

Expected request behavior:

- fail as a transient runtime problem, not as lost onboarding

## Security expectations

The bootstrap path should respect these rules:

- token material never enters prompt context
- tokens and secrets are not logged in plaintext
- client secret and refresh-capable state are operator-managed secrets
- token rotation or re-auth should not require changing user-facing capability
  IDs

## Acceptance criteria

The auth bootstrap contract is acceptable when:

- the target auth model is explicit and not confused with the current scaffold
- the runtime ownership of the redirect and token exchange is clear
- refresh-capable auth state is part of the baseline, not an optional afterthought
- playback prerequisites are separated from auth bootstrap success
- operators can tell the difference between `unconfigured` auth and a `real`
  account with temporary runtime or playback issues
