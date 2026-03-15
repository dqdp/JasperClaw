# First-Run Experience Contract

## Purpose

Define the user-facing experience for the ordinary default startup of the
single-household baseline.

This document answers one product question:

- what should a user see and be able to do immediately after first startup?

## Scope

Applies to:

- first launch of the default voice-first baseline
- early discovery of capabilities
- the transition between `demo`, `real`, and `unconfigured` capability states

## Non-goals

- full provider onboarding flow
- deep operator runbooks
- long-form marketing copy
- mobile-specific UX

Provider onboarding is documented separately.

Related contracts:

- `docs/features/default-product-baseline.md`
- `docs/features/capability-planning.md`
- `docs/ops/demo-household-config.md`
- `docs/ops/household-config.md`
- `docs/runbooks/default-baseline-onboarding.md`

## First-run product promise

The first run should feel like a usable assistant, not a pile of disconnected
services.

Minimum user-visible promise:

- the assistant can talk back and forth by voice
- the assistant can explain what it knows how to do
- the assistant can disclose which capabilities are in `demo`, `real`, or
  `unconfigured` state
- the assistant can demonstrate at least one external action through the same
  orchestration path used by normal requests

Target baseline packaging should go further:

- Spotify should be exercisable on first startup in either `demo` or `real`
  mode
- Telegram send should be exercisable on first startup only when the startup
  package includes either real household config or explicit demo household
  config

If neither real nor explicit demo Telegram config exists, the system must
report Telegram capabilities as `unconfigured` rather than pretending the full
baseline is ready.

## First-run assumptions

The default first run may start in a mixed state:

- voice: expected to be available
- Spotify: `demo`, `real`, or `unconfigured`
- Telegram send: `demo`, `real`, or `unconfigured` depending on whether an
  explicit demo or real household config is present

The assistant must communicate this explicitly instead of silently behaving as
if everything is real.

## First-run packaging requirement

The intended default product startup should ship with one of these Telegram
config paths:

- real household config
- explicit demo household config

Implicit fake aliases are not allowed.
If neither path exists, Telegram household capabilities remain
`unconfigured`, and the startup package does not meet the full target first-run
baseline.

## Capability disclosure contract

When the user asks what the system can do, the response should summarize:

- available baseline capabilities
- whether each capability is `demo`, `real`, or `unconfigured`
- what the user can try immediately
- what still requires operator/provider setup

The disclosure should be short and action-oriented, not a raw config dump.

## Recommended first-run prompts

The default baseline should support these first-run discovery prompts cleanly:

- "what can you do?"
- "what works right now?"
- "what Spotify actions do you support?"
- "can you send Telegram messages?"
- "what aliases do I have?"

## First-run success path

The first successful session should ideally look like this:

1. user starts the assistant
2. user asks what it can do
3. assistant explains current capability state
4. user tries one supported voice action
5. assistant executes or explains why the action is currently demo-only or
   unconfigured

This path must work without requiring the user to understand provider APIs.

Recommended first successful actions:

- a Spotify station or playlist action
- alias discovery
- a Telegram send action only when household or explicit demo config is present

## Capability-state language

User-facing wording should be stable and simple.

### `real`

Meaning:

- the capability is connected to the real provider and expected to perform the
  actual action

Suggested wording:

- "Spotify playback is connected"
- "Telegram send is configured"

### `demo`

Meaning:

- the capability can be exercised through a fake or local demo path
- it demonstrates orchestration behavior but not a real external side effect

Suggested wording:

- "Spotify station is available in demo mode"
- "Telegram send is available in demo mode"

### `unconfigured`

Meaning:

- the capability is not available until additional setup is completed

Suggested wording:

- "Telegram send is not configured yet"
- "Spotify playback needs account setup"

## First-run help responses

Help and status responses should prefer this structure:

1. what works now
2. what is demo-only
3. what is not configured
4. one or two suggested next actions

The response should not begin with infrastructure details or raw config terms.

## First-run examples

### Example: broad help

User:

`Что ты умеешь?`

Expected shape:

- voice chat is available
- Spotify playback/station is `demo` or `real`
- Telegram send is `real`, `demo`, or `unconfigured`
- suggest a concrete next prompt such as:
  - "Попробуй сказать: включи что-нибудь бодренькое"
  - "Попробуй спросить: какие у меня есть алиасы?"

### Example: Telegram not configured

User:

`Можешь отправить сообщение в Telegram?`

Expected shape:

- answer whether Telegram send is `real`, `demo`, or `unconfigured`
- if `unconfigured`, explain that household config is required
- do not pretend the capability exists if it does not

### Example: Telegram in demo mode

User:

`Какие у меня есть адресаты?`

Expected shape:

- state clearly that Telegram alias discovery is in `demo` mode
- list only demo aliases from the explicit demo household config
- avoid presenting demo aliases as real household contacts

### Example: Spotify in demo mode

User:

`Включи что-нибудь для фокуса`

Expected shape:

- if Spotify station is `demo`, say so briefly and proceed through the demo path
- if `real`, execute normally
- if `unconfigured`, explain what is missing

## Error and rejection behavior

The first-run UX should distinguish:

- `capability unavailable because unconfigured`
- `capability available only in demo mode`
- `capability configured but blocked by current prerequisite`

Example prerequisite:

- Spotify playback configured, but no active playback device is available

This should not be phrased as a generic internal failure.

## Telegram-specific first-run behavior

- if the current Telegram chat is untrusted, the bot should return a bounded
  local rejection rather than exposing the full assistant path
- `/aliases` should only work for trusted chats
- `/send` should not appear usable from untrusted chats
- if Telegram household config is absent, alias discovery and send should both
  report `unconfigured`

## Acceptance criteria

The first-run experience is acceptable when:

- a new user can understand what works immediately
- a new user can tell the difference between `demo`, `real`, and
  `unconfigured`
- the assistant suggests at least one valid next action
- unavailable capabilities fail honestly rather than ambiguously
- trusted and untrusted Telegram experiences differ in a clear but bounded way
