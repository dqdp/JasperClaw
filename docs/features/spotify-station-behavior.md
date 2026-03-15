# Spotify Station Behavior Contract

## Purpose

Define the user-facing behavior of `spotify-start-station` in the planned
default product baseline.

This document answers one product question:

- what should the assistant mean when it says it can "start a station"?

## Scope

Applies to:

- voice requests
- text requests
- the user-facing `spotify-start-station` capability

This document defines product semantics, not provider adapter internals.

## Non-goals

- exposing playlist CRUD as a user-facing command surface
- depending entirely on Spotify's deprecated recommendations endpoints
- cross-user personalization
- long-lived recommendation history
- Telegram bot Spotify control in v1

## Related contracts

- `docs/features/default-product-baseline.md`
- `docs/features/capability-planning.md`
- `docs/features/first-run-experience.md`
- `docs/runbooks/default-baseline-onboarding.md`

## Capability definition

`spotify-start-station` is a user-facing playback intent for open-ended
listening.

It exists for requests such as:

- "play something energetic"
- "play something like Radiohead"
- "start a jazz station"
- "put on something for focus"

It does not mean:

- "create and save a user playlist"
- "edit my Spotify library"
- "control Spotify through Telegram bot commands"

The capability may use helper playlist creation internally, but that remains an
implementation detail.

## Station versus playlist

The assistant should distinguish these two intents.

Use `spotify-play-playlist` when the user is asking for:

- a named playlist
- a saved playlist they already know
- explicit playlist discovery followed by playback

Use `spotify-start-station` when the user is asking for:

- genre-based listening
- similarity to an artist or track
- mood-based listening
- open-ended exploratory playback rather than a known saved playlist

If the request is genuinely ambiguous, the assistant may ask one bounded
clarification question.

Example:

- "Play focus" may refer to a playlist named `Focus` or to a focus-style
  station

After one clarification, the system should either act or fail honestly.
It should not continue an unbounded clarification loop.

## Supported inputs

The v1 station surface supports these seed kinds:

- `genre`
- `artist`
- `track`
- `mood`

The planner should map natural language into one of these canonical seed kinds.

### Genre

Examples:

- jazz
- ambient
- house
- hip hop

### Artist

Examples:

- Radiohead
- Massive Attack
- Bjork

### Track

Examples:

- "Teardrop"
- "Paranoid Android"

### Mood

The v1 baseline should treat mood as a small canonical vocabulary rather than
an open-ended latent space.

Recommended canonical mood tags:

- `focus`
- `calm`
- `energy`
- `party`
- `sleep`

Natural-language variants may map into these tags.

Examples:

- "бодренькое" -> `energy`
- "для концентрации" -> `focus`
- "что-нибудь спокойное" -> `calm`

## Output shape

The user-facing result is a generated playback set, not a permanent playlist.

V1 expectations:

- target size: 20 to 30 tracks
- duplicates within one generated set are not allowed
- the station does not need to be persisted as a user-visible saved playlist
- the implementation may internally use a temporary playlist or equivalent
  helper mechanism

The exact provider implementation may vary as long as the user-facing behavior
stays stable.

## Resolution rules

### One clarification maximum

The assistant may ask at most one bounded clarification question when:

- the seed kind is unclear
- the entity match is too ambiguous
- the request could reasonably mean either playlist playback or station start

If the ambiguity remains after one clarification, the assistant should stop and
return a bounded failure rather than guessing.

### Confidence rule

The assistant should not guess a side-effectful playback target when the seed is
weakly resolved.

This is especially important for:

- short track names with many matches
- artist names with multiple plausible entities
- vague mood requests that do not map cleanly into the canonical mood set

### Seed reuse

The station may include the seed artist or seed track, but should not loop the
same track repeatedly or duplicate it within one generated set.

## Provider strategy

`spotify-start-station` is a product capability, not a promise about one
specific Spotify endpoint.

Allowed implementation strategies include:

- Spotify search plus internal ranking
- helper playlist creation plus playback
- optional use of Spotify recommendations when available

The baseline must not depend solely on deprecated recommendation endpoints.

## Capability states

### `real`

Meaning:

- the capability uses the configured household Spotify account and real
  playback path

Expected behavior:

- start the station on the real playback target when prerequisites are met

### `demo`

Meaning:

- the capability uses a fake or local demonstration path

Expected behavior:

- disclose demo mode briefly
- demonstrate the same orchestration and response contract without claiming a
  real Spotify side effect

### `unconfigured`

Meaning:

- the capability is not available because the Spotify real or demo path is not
  configured

Expected behavior:

- explain what is missing
- do not fabricate a station result

## Playback prerequisites

Real station playback depends on:

- a correctly connected household Spotify account
- Spotify Premium
- an already active playback device

An active playback device means a Spotify Connect target already visible to the
household account, such as:

- a phone with Spotify open
- a desktop Spotify client
- an active Web Player session

If these prerequisites are missing, the assistant should report a bounded
prerequisite failure rather than a generic internal error.

The system should not silently fall back from `real` to `demo`.

## Failure semantics

The station contract should distinguish these cases:

### Unconfigured

Examples:

- no Spotify auth material
- no demo adapter configured

Expected response shape:

- explain that Spotify station is not configured yet

### Prerequisite failure

Examples:

- no active playback device
- Spotify account is connected but cannot satisfy playback prerequisites

Expected response shape:

- explain the missing prerequisite
- suggest one concrete next step, such as opening Spotify on a device

### Ambiguous seed

Examples:

- multiple equally plausible track matches
- phrase could mean either a playlist or a station

Expected response shape:

- ask one bounded clarification question

### Runtime failure

Examples:

- temporary provider timeout
- transient upstream failure

Expected response shape:

- report a bounded temporary failure
- avoid implying that onboarding was lost

## User-facing examples

### Mood-based station

User:

`Поставь что-нибудь бодренькое`

Expected planning shape:

- `spotify-start-station`
- `seed_kind=mood`
- `seed_value=energy`

### Artist-similarity station

User:

`Включи что-нибудь как Massive Attack`

Expected planning shape:

- `spotify-start-station`
- `seed_kind=artist`
- `seed_value=Massive Attack`

### Playlist instead of station

User:

`Включи плейлист Focus`

Expected shape:

- prefer `spotify-play-playlist`
- do not route to `spotify-start-station` unless the request is clarified in
  that direction

### Ambiguous request

User:

`Включи focus`

Expected shape:

- ask one bounded clarification question if both playlist and mood-style
  station are plausible

## Acceptance criteria

The station contract is acceptable when:

- users can understand the difference between playlist playback and station
  start
- supported inputs are limited and explicit
- mood handling is canonicalized rather than left fully open-ended
- one clarification maximum is enforced conceptually
- the generated result is defined as an ephemeral playback set rather than a
  saved playlist
- prerequisite failures are distinct from configuration failures
- the contract does not depend on deprecated Spotify recommendations as the
  only foundation
