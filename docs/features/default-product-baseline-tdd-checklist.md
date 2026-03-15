# Default Product Baseline TDD Checklist

## Purpose

Translate the planned default product baseline into one implementation-first
TDD checklist.

This document answers one execution question:

- what should be tested, and in what order, before the default-startup
  convergence code is allowed to flip behavior?

## Scope

Applies to the full default-baseline expansion block:

- capability-state semantics
- discovery and status surface
- Spotify auth bootstrap and playback behavior
- Spotify station behavior
- trusted-chat Telegram send and alias discovery
- voice confirmation for `telegram-send`
- deterministic smoke for the default startup
- final default-startup flip

## Non-goals

- replacing the product plan documents
- deep performance benchmarking
- broader post-v1 incident-management
- speculative features outside the accepted baseline

## Related contracts

- `docs/features/default-product-baseline.md`
- `docs/features/capability-planning.md`
- `docs/features/capability-discovery.md`
- `docs/features/first-run-experience.md`
- `docs/features/spotify-station-behavior.md`
- `docs/features/telegram-send-confirmation.md`
- `docs/ops/household-config.md`
- `docs/ops/demo-household-config.md`
- `docs/runbooks/default-baseline-onboarding.md`
- `docs/runbooks/spotify-auth-bootstrap.md`

## Global TDD rules

- write or update tests before changing runtime behavior
- prefer the lowest test layer that can prove the contract cleanly
- when behavior crosses layers, add both local contract tests and one
  higher-level integration proof
- do not flip the ordinary default startup until the deterministic smoke matrix
  is green
- do not use `SPOTIFY_ACCESS_TOKEN` support as the success criterion for the
  real Spotify auth slice
- do not let Telegram demo behavior bypass trusted-chat or alias rules

## Recommended test layers

Use these layers consistently:

- unit tests for pure mapping, parsing, and validation rules
- contract tests for capability selection, policy outcomes, and response shapes
- integration tests for end-to-end `agent-api` behavior with fake dependencies
- deterministic smoke for the default startup contract
- optional real-provider smoke for live third-party validation

## Workstream 1: Capability state and discovery

### Tests to add first

- [ ] capability-state resolution returns only `demo`, `real`, or
  `unconfigured`
- [ ] `unconfigured` capabilities are not selected by the planner
- [ ] discovery/help surfaces disclose state without exposing raw config
- [ ] `/help` and `/status` stay inside the intended narrow discovery surface
- [ ] discovery surfaces do not expose internal helper capabilities

### Edge cases

- [ ] mixed state: voice `real`, Spotify `demo`, Telegram `unconfigured`
- [ ] mixed state: Spotify `real`, Telegram `demo`
- [ ] missing discovery data degrades to bounded help instead of raw failures

## Workstream 2: Real and demo household config loading

### Tests to add first

- [ ] valid real `household.toml` -> Telegram capabilities resolve to `real`
- [ ] valid demo `household.demo.toml` with no real config -> Telegram
  capabilities resolve to `demo`
- [ ] both real and demo configs present -> real wins
- [ ] missing both configs -> Telegram capabilities resolve to `unconfigured`
- [ ] invalid real config fails closed
- [ ] invalid demo config fails closed
- [ ] no implicit fake aliases appear when config is missing

### Edge cases

- [ ] duplicate trusted chat IDs rejected
- [ ] malformed alias keys rejected
- [ ] missing alias description rejected
- [ ] alias discovery never exposes raw `chat_id`

## Workstream 3: Spotify auth bootstrap

### Tests to add first

- [ ] real Spotify capability does not become `real` from
  `client_credentials` alone
- [ ] real Spotify capability does not use static `SPOTIFY_ACCESS_TOKEN` as
  the completion criterion for PB-3
- [ ] missing client auth material -> Spotify remains `unconfigured`
- [ ] incomplete refresh-capable bootstrap -> Spotify remains `unconfigured`
- [ ] refresh-capable auth state is treated as the real baseline path

### Edge cases

- [ ] playback prerequisite failures do not demote Spotify from `real` to
  `unconfigured`
- [ ] runtime Spotify failures do not look like onboarding loss

## Workstream 4: Spotify playlist discovery and playback

### Tests to add first

- [ ] `spotify-list-playlists` returns the user-facing playlist surface
- [ ] `spotify-play-playlist` resolves a known playlist correctly
- [ ] named playlist ambiguity triggers one bounded clarification path when
  needed
- [ ] playback request with no active playback device returns a prerequisite
  failure
- [ ] playback request does not silently fall back to station behavior

### Edge cases

- [ ] missing Premium or equivalent playback prerequisite is surfaced cleanly
- [ ] provider timeout is classified as runtime failure, not config failure

## Workstream 5: Spotify station behavior

### Tests to add first

- [ ] mood requests map into the canonical mood set
- [ ] genre, artist, track, and mood seeds all resolve through
  `spotify-start-station`
- [ ] playlist-like requests prefer `spotify-play-playlist`
- [ ] ambiguous playlist-versus-station requests ask at most one clarification
- [ ] weak seed resolution fails honestly instead of guessing

### Edge cases

- [ ] unsupported mood-like phrases do not invent arbitrary latent categories
- [ ] duplicate tracks are prevented within one generated set when that set is
  observable at the tested layer
- [ ] `real` mode does not silently fall back to `demo`

## Workstream 6: Trusted-chat Telegram alias discovery and send

### Tests to add first

- [ ] trusted chats can use `/help`, `/status`, `/ask`, `/aliases`, and `/send`
- [ ] untrusted chats receive only a bounded local rejection
- [ ] `telegram-list-aliases` lists alias names plus descriptions only
- [ ] `telegram-send` validates aliases against the household config
- [ ] unknown alias fails before side effects

### Edge cases

- [ ] demo alias discovery is disclosed as demo-only
- [ ] demo send preserves the same typed contract without claiming a real send
- [ ] free-form Telegram chat remains deny-by-default for model-driven external
  effects

## Workstream 7: Voice `telegram-send` confirmation

### Tests to add first

- [ ] voice `telegram-send` always requires confirmation
- [ ] invalid sends fail before confirmation
- [ ] one pending confirmation exists per conversation at most
- [ ] pending confirmation is bound to `pending_action_id`
- [ ] pending confirmation is bound to the initiating source class
- [ ] explicit confirm executes the send once
- [ ] explicit cancel sends nothing
- [ ] unclear confirmation gets at most one bounded repeat
- [ ] timeout invalidates the pending send
- [ ] interruption invalidates the pending send

### Edge cases

- [ ] repeated confirmation after execution does not duplicate the send
- [ ] new pending send invalidates the previous confirmation token
- [ ] cross-source confirmation is rejected
- [ ] `demo` mode keeps the same confirmation UX without claiming a real send

## Workstream 8: Minimal Telegram bot command surface

### Tests to add first

- [ ] command discovery lists only `/help`, `/status`, `/ask`, `/aliases`, and
  `/send`
- [ ] Telegram bot does not expose Spotify control commands in v1
- [ ] slash-command `/send` uses the same typed capability layer as voice/text
- [ ] slash-command `/send` does not open the voice confirmation flow

### Edge cases

- [ ] commands outside the allowlist are denied cleanly
- [ ] command handling does not create a privileged bypass around typed policy

## Workstream 9: Deterministic default-startup smoke

### Tests to add first

- [ ] ordinary default startup boots with the voice path enabled
- [ ] capability discovery works in the ordinary default startup
- [ ] Spotify baseline intents work in deterministic `demo` or fake mode
- [ ] Telegram send and alias discovery work in deterministic `demo` or fake
  mode
- [ ] trusted and untrusted Telegram behavior is validated in deterministic
  smoke

### Edge cases

- [ ] deterministic smoke proves `demo` versus `real-provider` expectations
  explicitly instead of inferring them
- [ ] smoke failure messages distinguish startup, config, and provider-shape
  failures

## Workstream 10: Optional real-provider smoke

### Tests to add first

- [ ] real Spotify bootstrap can be verified through one bounded playlist
  action
- [ ] real Spotify station can be verified through one bounded seed request
- [ ] real Telegram alias discovery works
- [ ] real Telegram send succeeds through one bounded test action

### Edge cases

- [ ] active playback device and Premium prerequisites are visible in the smoke
  output
- [ ] real-provider smoke stays opt-in and is not required for ordinary CI

## Workstream 11: Final default-startup flip

### Tests to add first

- [ ] default startup enables the supported CPU voice path
- [ ] previously mandatory baseline contracts still pass after the default flip
- [ ] text-first mode, if retained, is now an explicit compatibility override
  rather than the ordinary startup

### Edge cases

- [ ] default flip does not regress canonical chat, STT, or TTS smoke
- [ ] default flip does not silently skip discovery or capability-state
  disclosure

## Final release checklist

- [ ] all lower-layer unit and contract tests for capability state, config
  loading, Spotify auth, station behavior, Telegram send, and confirmation are
  green
- [ ] integration tests prove canonical `agent-api` orchestration for Spotify
  and Telegram actions
- [ ] deterministic default-startup smoke is green
- [ ] optional real-provider smoke has a documented opt-in path
- [ ] no remaining slice claims completion based only on scaffold variables such
  as `SPOTIFY_ACCESS_TOKEN`
- [ ] the default-startup flip happens only after the preceding checklist is
  green

## Definition of done

The TDD checklist is satisfied only when:

- the default startup becomes the intended voice-first baseline
- discovery, Spotify, and Telegram behavior all match the documented product
  contract
- the implementation is proven first in deterministic tests, then in bounded
  higher-level integration and smoke checks
