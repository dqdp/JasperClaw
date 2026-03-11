# Short TDD Plan Template

## Purpose

Use this template for short, implementation-facing TDD plans tied to one vertical slice or one tightly related task group.

Keep it short.
If a plan becomes long, the slice is probably too large.

## Template

```md
# TDD Plan: <slice name>

## Scope

- Task IDs: <ids>
- Goal: <one sentence>
- Non-goals: <1-3 bullets>

## Behavior to prove

- <behavior 1>
- <behavior 2>
- <behavior 3>

## Test layers

### 1. Unit

- <unit case>
- <unit case>

### 2. Integration

- <integration case>
- <integration case>

### 3. Smoke or manual verification

- <smoke check>
- <smoke check>

## Failure cases

- <failure case>
- <failure case>

## Exit signal

- <what must be true to close the slice>
```

## Example: `CP-1 .. CP-4`

```md
# TDD Plan: Control Plane MVP Slice 1

## Scope

- Task IDs: `CP-1`, `CP-2`, `CP-3`, `CP-4`
- Goal: replace the stubbed non-streaming text path with a real `agent-api -> Ollama` execution path behind typed schemas and layered code structure
- Non-goals:
  - streaming support
  - Postgres persistence
  - real voice implementation

## Behavior to prove

- `agent-api` accepts valid OpenAI-compatible non-streaming chat requests
- invalid requests fail with stable validation errors
- logical profile resolution reaches the configured `Ollama` runtime
- successful non-streaming model execution returns a normalized OpenAI-style response instead of a stub

## Test layers

### 1. Unit

- request schema accepts minimal valid `chat/completions` payload
- request schema rejects missing `model` or malformed `messages`
- profile resolver maps `assistant-v1` and `assistant-fast` to internal runtime config
- Ollama client maps timeout and bad-response cases to stable internal error classes

### 2. Integration

- `POST /v1/chat/completions` with `stream=false` reaches the real `Ollama` client and returns a response payload with assistant content
- unknown profile returns stable `validation_error`
- runtime timeout or unavailable upstream returns stable dependency or upstream error

### 3. Smoke or manual verification

- `GET /v1/models` returns `assistant-v1` and `assistant-fast`
- a simple non-streaming prompt through `agent-api` returns model output instead of the current stub text

## Failure cases

- malformed request body
- unknown profile
- upstream timeout
- upstream unavailable
- dependency returns malformed payload

## Exit signal

- the non-streaming text path is real, no longer stubbed, and failure behavior is explicit enough to support the next slice
```

## Usage rule

Use one short plan like this for:

- a first real vertical slice
- a risky integration change
- a feature with new failure semantics

Do not create a separate long-lived TDD document for every small refactor or low-risk edit.
