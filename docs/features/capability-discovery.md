# Capability Discovery Contract

## Purpose

Define how the assistant explains available capabilities, capability state, and
baseline commands to the user.

This document answers one product question:

- how should a user discover what the assistant can do without knowing provider
  internals?

## Scope

Applies to:

- first-run discovery
- ongoing help and status answers
- baseline command and alias discovery
- capability-state disclosure for `demo`, `real`, and `unconfigured`

## Non-goals

- a full UI information architecture
- raw config inspection
- provider-specific API documentation
- long-form onboarding or troubleshooting steps

## Related contracts

- `docs/features/default-product-baseline.md`
- `docs/features/first-run-experience.md`
- `docs/features/capability-planning.md`
- `docs/features/spotify-station-behavior.md`
- `docs/ops/demo-household-config.md`
- `docs/ops/household-config.md`

## Discovery principles

Discovery should be:

- short
- action-oriented
- honest about current capability state
- framed in user tasks rather than provider internals

Discovery should not:

- start with environment variables
- expose raw IDs or secrets
- require the user to know Spotify or Telegram API semantics

## Discovery surfaces

The baseline should support at least these discovery surfaces:

- broad capability help
- current status
- Spotify-specific discovery
- Telegram alias discovery
- Telegram bot command discovery

## Canonical user questions

The baseline should answer these cleanly:

- "what can you do?"
- "what works right now?"
- "what Spotify actions do you support?"
- "what playlists do I have?"
- "can you send Telegram messages?"
- "what aliases do I have?"
- "what bot commands are available?"

## Deterministic versus planned discovery

Two approaches are possible:

1. Route all discovery through the planner.
2. Handle a narrow discovery surface in the deterministic pre-router and leave
   the rest to the planner.

The accepted baseline should prefer `2`.

Why:

- discovery wording is product-critical and should be stable
- capability-state disclosure should not depend on model improvisation
- it reduces accidental tool selection during simple help/status questions

Recommended deterministic surface:

- `/help`
- `/status`
- `/aliases`
- the narrow local equivalents of "what can you do?" and "what works right now?"

## Broad help contract

Broad help should answer:

1. what works now
2. what is demo-only
3. what is not configured
4. one or two valid next actions

Recommended content areas:

- voice conversation
- Spotify playback and station abilities
- Telegram send and alias discovery
- minimal bot commands

The response should stay compact and should not enumerate internal helper
capabilities.

## Status contract

Status should disclose capability state in a concise user-facing form.

Minimum baseline status areas:

- voice
- Spotify playlist playback
- Spotify station
- Telegram alias discovery
- Telegram send

Recommended user-facing labels:

- `connected` or equivalent for `real`
- `demo` for `demo`
- `not configured` for `unconfigured`

Status should not dump raw config values.

## Spotify discovery contract

Spotify discovery should explain the user-facing surface, not the adapter
internals.

It should cover:

- play a named playlist
- start a station from genre, artist, track, or mood
- pause playback
- skip to the next track
- list available playlists

Spotify discovery may also mention bounded prerequisites when relevant:

- Premium playback requirement
- active playback device requirement

It should not foreground helper operations such as internal playlist creation.

## Mood discovery

If the user asks what kinds of station requests are supported, the baseline
should expose the canonical mood vocabulary rather than leaving it hidden.

Recommended v1 mood tags:

- `focus`
- `calm`
- `energy`
- `party`
- `sleep`

Natural-language variants may map into these tags, but discovery should mention
the canonical user-facing concepts.

## Telegram discovery contract

Telegram discovery should separate:

- alias discovery
- send capability
- bot commands

The user-facing Telegram surface should explain:

- whether send is `real`, `demo`, or `unconfigured`
- that sending works only through configured aliases
- that alias descriptions are available for discovery

It should not expose:

- raw `chat_id`
- arbitrary contact discovery
- unrestricted Telegram chat access

## Bot command discovery

The v1 bot surface should remain minimal.

Discovery should list only:

- `/help`
- `/status`
- `/ask <message>`
- `/aliases`
- `/send <alias> <text>`

It should also make clear what is intentionally absent:

- no Spotify control commands through the Telegram bot in v1

## Demo disclosure

When a capability is in `demo`, discovery should say so before suggesting the
action.

Examples:

- "Spotify station is available in demo mode"
- "Telegram send is available in demo mode"

If demo aliases are shown, they should already be framed as demo aliases rather
than presented as real household contacts.

## Unconfigured disclosure

When a capability is `unconfigured`, discovery should:

- say that it is not configured yet
- avoid pretending the action can be taken immediately
- point to the next operator or setup step at a high level

Discovery should not turn into a long troubleshooting flow.

## Example response shapes

### Broad help

Expected shape:

- "I can talk by voice"
- "I can play Spotify playlists or start a station"
- "I can send Telegram messages to configured aliases"
- "Right now Spotify is `demo|connected|not configured`"
- "Right now Telegram send is `demo|connected|not configured`"
- one or two example prompts

### Spotify-specific help

Expected shape:

- explain playlist playback
- explain station start by genre, similarity, or mood
- mention `focus`, `calm`, `energy`, `party`, `sleep`
- mention active-device requirement only when useful

### Telegram-specific help

Expected shape:

- explain alias-scoped sending
- explain whether aliases are available now
- list commands or suggest `/aliases`

## Acceptance criteria

The discovery contract is acceptable when:

- users can discover the baseline surface without provider knowledge
- `demo`, `real`, and `unconfigured` are disclosed consistently
- help/status do not expose helper capabilities or raw config
- Spotify moods and playlist-versus-station behavior are discoverable
- Telegram alias discovery is honest about configured versus demo aliases
- bot command discovery stays narrow and matches the intended v1 surface
