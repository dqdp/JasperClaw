# Capability Planning Contract

## Purpose

Define how normalized text and voice requests are mapped into either:

- a final assistant answer
- or one typed capability invocation

This document governs planner behavior, not provider adapter internals.

## Scope

Applies to:

- text requests through `agent-api`
- voice requests after STT normalization
- Telegram requests after ingress normalization

## Non-goals

- raw provider endpoint selection by the model
- arbitrary tool payload invention
- bypassing policy or confirmation rules
- direct external side effects from free-form model output

## Planning pipeline

The canonical decision pipeline is:

1. deterministic pre-router
2. model planner
3. policy evaluation
4. executor
5. response rendering
6. optional TTS synthesis

Each stage has a distinct responsibility boundary.

## Stage 1: Deterministic pre-router

The pre-router handles bounded requests that do not require capability
selection.

Examples:

- `/help`
- `/status`
- `/aliases`
- explicitly supported local discovery prompts

Pre-router outputs:

- local response
- or normalized planner input

## Stage 2: Planner

The planner may produce exactly one of:

- `final_answer`
- `capability_request`

The planner must never emit:

- raw URLs
- provider-specific method names
- shell-like commands
- multiple capability invocations in one pass

### Planner output schema

```json
{
  "type": "capability_request",
  "capability": "spotify-start-station",
  "arguments": {
    "seed_kind": "mood",
    "seed_value": "energy"
  }
}
```

## Stage 3: Policy evaluation

Policy is authoritative over planner output.

For each capability request, policy may return:

- `allow`
- `deny`
- `require_confirmation`

The planner is not allowed to bypass policy.

## Stage 4: Executor

The executor:

- validates typed arguments
- resolves capability state
- invokes the internal capability implementation
- keeps raw provider details outside the planning contract

## Capability state

Each capability has one explicit state:

- `demo`
- `real`
- `unconfigured`

Rules:

- `unconfigured` capabilities should not be selected by the planner
- `demo` capabilities may be selected only when the product contract allows
  demo behavior
- runtime outages are not capability-state transitions

Discovery and status surfaces should be able to report capability state.

## Capability spec schema

Each capability spec should define:

- `name`
- `purpose`
- `when_to_use`
- `when_not_to_use`
- `arguments_schema`
- `availability_states`
- `requires_confirmation`
- `source_restrictions`
- `examples`

## Source restrictions

Planning and policy behavior depend on request source.

Relevant sources:

- `web_text`
- `web_voice`
- `telegram_chat`
- `telegram_command`

Rules:

- `telegram_chat` remains deny-by-default for model-driven external effects
- `telegram_command` may use only a narrow allowlisted subset of capabilities
- source restrictions are enforced by policy, not only by prompt wording
- confirmation-required actions should remain bound to the initiating
  conversation context and source class

## Confirmation flow

Capabilities marked `requires_confirmation=true` follow this contract:

1. planner emits `capability_request`
2. policy returns `require_confirmation`
3. system renders a confirmation question
4. execution happens only after explicit confirmation

Baseline rule:

- voice `telegram-send` requires confirmation
- slash-command `/send` does not

Detailed voice confirmation semantics are documented in
`docs/features/telegram-send-confirmation.md`.

## Discovery and status handling

The intended user-facing discovery and status contract is documented in
`docs/features/capability-discovery.md`.

## Failure handling

When planning or execution cannot safely proceed, the system should choose one
of:

- ask one bounded clarification question
- return a controlled unavailability message
- return a policy denial message
- fall back to a final answer without side effects

The system should not guess ambiguous side-effect targets.

## Baseline capabilities

### `capabilities-help`

Purpose:

- explain what the assistant can do in the current environment

### `spotify-list-playlists`

Purpose:

- list available playlists for the current household account

### `spotify-play-playlist`

Purpose:

- start playback for a named or resolved playlist

### `spotify-start-station`

Purpose:

- start a generated playback set from genre, similarity, or mood-like intent

Detailed product semantics are documented in
`docs/features/spotify-station-behavior.md`.

Recommended baseline inputs:

- `genre`
- `artist`
- `track`
- `mood`

### `spotify-pause`

Purpose:

- pause current playback

### `spotify-next`

Purpose:

- skip current playback to the next track

### `telegram-list-aliases`

Purpose:

- list configured household message aliases

### `telegram-send`

Purpose:

- send a message to a configured alias

Detailed confirmation semantics are documented in
`docs/features/telegram-send-confirmation.md`.

## Helper capabilities

Helper capabilities are internal execution primitives and not the primary
user-facing contract.

Examples:

- `spotify-search`
- `spotify-create-playlist`
- `spotify-add-to-playlist`

The planner should prefer user-facing capabilities over helper capabilities
unless explicitly configured otherwise.

## Household assumptions

The v1 baseline assumes:

- one self-hosted household account model
- one operator-managed household config file
- trusted Telegram chats are defined explicitly
- alias resolution is file-backed rather than inferred dynamically

## Few-shot examples

### Example: mood-based station

User:

`Поставь что-нибудь бодренькое`

Planner:

```json
{
  "type": "capability_request",
  "capability": "spotify-start-station",
  "arguments": {
    "seed_kind": "mood",
    "seed_value": "energy"
  }
}
```

### Example: list aliases

User:

`Какие у меня есть адресаты?`

Planner:

```json
{
  "type": "capability_request",
  "capability": "telegram-list-aliases",
  "arguments": {}
}
```

### Example: send message

User:

`Отправь сообщение жене, что я задерживаюсь`

Planner:

```json
{
  "type": "capability_request",
  "capability": "telegram-send",
  "arguments": {
    "alias": "wife",
    "text": "Я задерживаюсь"
  }
}
```

Expected policy outcome:

- `require_confirmation`

## Testing implications

Tests should cover:

- deterministic pre-router cases
- planner choosing valid capability IDs only
- source-restricted denials
- confirmation-required flows
- capability-state-aware planning
- ambiguity and clarification behavior
