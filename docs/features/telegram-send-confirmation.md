# Telegram Send Confirmation Contract

## Purpose

Define the user-facing confirmation UX for voice-driven `telegram-send` in the
planned default product baseline.

This document answers one product question:

- how should the assistant safely confirm a voice request to send a Telegram
  message before executing the side effect?

## Scope

Applies to:

- voice-initiated `telegram-send`
- confirmation, cancellation, ambiguity, and timeout behavior
- the user-facing dialogue shape around one side-effectful send action

This document does not change the typed capability or policy boundary.

## Non-goals

- general approval workflows for all tools
- Telegram bot slash-command confirmation UX
- long-form dictation workflows for large messages
- multi-step message editing before send
- arbitrary Telegram chat discovery

## Related contracts

- `docs/features/default-product-baseline.md`
- `docs/features/capability-planning.md`
- `docs/features/first-run-experience.md`
- `docs/ops/household-config.md`

## Confirmation boundary

The v1 rule is intentionally narrow:

- voice-driven `telegram-send` requires confirmation before execution
- slash-command `/send <alias> <text>` does not require confirmation once it
  has passed validation
- ordinary Telegram free chat remains deny-by-default for model-driven external
  effects and does not enter this confirmation flow

This keeps one explicit side-effect UX for voice without turning all command
surfaces into approval loops.

## Why confirmation exists

`telegram-send` is a side-effectful action with a household-visible result.

Voice input adds extra risk because:

- STT may mishear names or message content
- alias resolution can still be misunderstood by the user even when it is
  technically valid
- a mistaken send is harder to undo than a mistaken playback request

The confirmation flow exists to prevent accidental sends, not to add generic
friction to every action.

## Canonical flow

The intended voice flow is:

1. user asks to send a Telegram message
2. planner selects `telegram-send`
3. policy returns `require_confirmation`
4. the assistant renders one confirmation prompt
5. the user either confirms or cancels
6. execution happens at most once

Validation should happen before the confirmation prompt whenever possible.

This means the assistant should fail early for:

- unknown alias
- `telegram-send` being `unconfigured`
- obviously malformed or empty message content

The system should not ask the user to confirm an action that is already known
to be invalid.

## Confirmation binding

The pending confirmation must be bound to one explicit action context, not just
to the fact that the last answer asked a yes-or-no question.

Recommended v1 binding fields:

- `pending_action_id`
- canonical `conversation_id`
- initiating source class
- normalized target alias
- normalized message payload or message preview

The same spoken or typed "yes" must not be allowed to confirm a different send
action after the conversation context has changed.

## Confirmation prompt shape

The confirmation prompt should include:

- the target alias
- enough message content to let the user detect a mistaken send
- an explicit request for confirmation or cancellation

Recommended shape:

- "Отправить `<alias>` сообщение: `<message-or-preview>`? Скажи `да` или
  `отмена`."

The prompt should not mention:

- raw `chat_id`
- provider internals
- policy jargon such as `requires_confirmation`

## Short-message assumption

The v1 confirmation UX is optimized for short household messages.

If the message is too long for a safe spoken confirmation, the assistant should
not read out an excessive payload.

Recommended fallback:

- ask the user to shorten the message
- or ask them to use text input for the send action

This keeps confirmation understandable and bounded.

## Confirmation outcome classes

The confirmation response should be normalized into one of:

- `confirm`
- `cancel`
- `unclear`

### Confirm

Examples:

- "да"
- "подтверждаю"
- "отправь"
- "окей"

### Cancel

Examples:

- "нет"
- "отмена"
- "не надо"
- "стоп"

### Unclear

Examples:

- unrelated speech
- partial utterances
- another new request that does not clearly confirm or cancel the pending send

## Ambiguity handling

The assistant may ask at most one bounded repeat question if the confirmation
response is unclear.

Recommended repeat shape:

- "Подтвердить отправку или отменить? Скажи `да` или `отмена`."

If the response remains unclear after one repeat, the send action should be
cancelled rather than guessed.

## Timeout behavior

Voice confirmation should be short-lived.

Recommended v1 contract:

- one pending confirmation per conversation
- a short bounded timeout, recommended at 30 seconds
- timeout cancels the pending send instead of leaving it armed indefinitely

The assistant should report the timeout clearly if the user returns too late.

## Source binding

The safest v1 rule is:

- a pending voice `telegram-send` confirmation may be satisfied only from the
  same canonical conversation and the same source class that initiated it

Implications:

- a Telegram message or bot command must not confirm a pending web-voice send
- an unrelated client session must not confirm a pending send from another
  session
- a delayed "yes" after the user has moved to a different source path must be
  ignored or treated as a fresh request

This keeps confirmation local to the initiating interaction path.

## Interruption behavior

If a new unrelated request arrives while a send confirmation is pending, the
pending send should be invalidated before the new request is handled.

This avoids a delayed "yes" applying to the wrong action after the dialogue has
already moved on.

The system should prefer cancellation over hidden carry-over state.

## Duplicate-send protection

The confirmation token for one send action should be single-use.

Rules:

- one explicit confirmation may trigger execution once
- repeated "yes" after execution must not resend the same message
- timeout, cancellation, or interruption invalidates the pending confirmation
- replacing one pending send with a new one must invalidate the previous
  `pending_action_id`

This is required even when the downstream Telegram send path is otherwise
idempotent or audited.

## Capability-state interaction

### `real`

Behavior:

- require confirmation
- execute the real send only after explicit confirmation

### `demo`

Behavior:

- still require confirmation so the UX matches the real side-effect path
- disclose that the action is in demo mode
- do not claim that a real household message was sent

### `unconfigured`

Behavior:

- fail before confirmation
- explain what setup is missing

An `unconfigured` capability must not open a faux confirmation loop.

## Trusted-target assumptions

Voice `telegram-send` still uses the household alias registry.

Implications:

- only configured aliases are valid targets
- alias resolution happens before confirmation
- the spoken confirmation refers to the alias, not the raw Telegram target

## Failure semantics

The confirmation UX should distinguish:

### Validation failure before confirmation

Examples:

- alias is unknown
- message content is empty
- capability is `unconfigured`

Expected behavior:

- do not open the confirmation flow
- explain what is wrong

### Explicit cancellation

Examples:

- user says "нет"
- user says "отмена"

Expected behavior:

- cancel the send
- confirm that nothing was sent

### Timeout or interruption

Examples:

- user does not answer in time
- user starts a different request instead

Expected behavior:

- cancel the send
- do not keep a hidden pending approval alive

### Post-confirmation runtime failure

Examples:

- Telegram send times out
- downstream send fails transiently

Expected behavior:

- report a bounded runtime failure
- do not ask for confirmation again automatically

## User-facing examples

### Happy path

User:

`Отправь жене сообщение, что я задерживаюсь на 20 минут`

Assistant:

`Отправить wife сообщение: "Я задерживаюсь на 20 минут"? Скажи "да" или "отмена".`

User:

`Да`

Expected result:

- one send execution
- one bounded success reply
- the confirmation token is consumed and cannot be reused

### Cancellation

User:

`Отправь сообщение home: Буду позже`

Assistant:

`Отправить home сообщение: "Буду позже"? Скажи "да" или "отмена".`

User:

`Нет`

Expected result:

- no send execution
- explicit acknowledgement that nothing was sent

### Unknown alias

User:

`Отправь сообщение соседу, что я приду позже`

Expected result:

- fail before confirmation
- explain that the alias is unknown

### Ambiguous confirmation

User:

`Отправь home сообщение: Я выехал`

Assistant:

`Отправить home сообщение: "Я выехал"? Скажи "да" или "отмена".`

User:

`Ну давай`

Expected result:

- either normalize this confidently to `confirm`
- or ask one bounded repeat question

The system must not drift into an open-ended dialogue here.

## Acceptance criteria

The confirmation contract is acceptable when:

- voice `telegram-send` always requires confirmation before the side effect
- invalid sends fail before confirmation
- only one pending confirmation can exist per conversation
- ambiguous confirmation gets at most one bounded repeat
- timeout, cancellation, and interruption all invalidate the pending send
- repeated confirmation cannot produce duplicate sends
- demo mode preserves the same confirmation shape without pretending a real
  message was sent
