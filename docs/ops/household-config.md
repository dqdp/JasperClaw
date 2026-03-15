# Household Config Contract

## Purpose

Define the operator-managed configuration for the single-household baseline.

This contract governs:

- trusted Telegram chats
- Telegram alias resolution
- user-facing alias discovery metadata
- validation and startup behavior

## Scope

Applies to the default product baseline only.

This is not a multi-user identity model.

## Non-goals

- per-user provider bindings
- dynamic alias creation by end users
- database-backed contact management
- arbitrary Telegram chat discovery

## File location

Recommended default:

- `infra/config/household.toml`

The exact path may be configurable, but the runtime contract should assume one
canonical file.

## Ownership model

The file is operator-managed.

Rules:

- end users do not edit it through chat or voice
- runtime reads it as configuration, not mutable user data
- changes require explicit operator action

## Top-level shape

```toml
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
```

## Schema

### `[telegram]`

#### `trusted_chat_ids`

Type:

- array of positive integers

Meaning:

- Telegram chats allowed to use the household assistant bot surface

Rules:

- required for real Telegram assistant access
- duplicates are invalid
- non-positive values are invalid

### `[telegram.aliases.<alias>]`

Alias key:

- lowercase stable identifier
- recommended charset: `a-z`, `0-9`, `_`, `-`

Fields:

#### `chat_id`

Type:

- positive integer

Meaning:

- Telegram target for `telegram-send`

Required:

- yes

#### `description`

Type:

- non-empty string

Meaning:

- short user-facing explanation shown in alias discovery

Required:

- yes for the baseline

## Validation rules

The file is invalid when:

- TOML is malformed
- `trusted_chat_ids` contains invalid or duplicate values
- alias key is malformed
- alias `chat_id` is missing or invalid
- alias `description` is empty

## Runtime behavior on invalid config

Recommended baseline:

- invalid household config is a startup/config error
- runtime must not silently ignore broken aliases or trusted chats
- readiness should fail if the Telegram baseline is configured as required and
  the file is invalid

## Discovery behavior

Alias discovery may expose:

- alias name
- alias description

Alias discovery must not expose:

- raw `chat_id`
- unrelated Telegram metadata

## Trusted-chat behavior

### Trusted chat

May use:

- `/help`
- `/status`
- `/ask`
- `/aliases`
- `/send`

### Untrusted chat

Must not receive:

- full assistant path
- alias discovery
- outbound send behavior

May receive:

- bounded local rejection such as `chat not authorized`

## Interaction with voice path

Voice `telegram-send` uses alias resolution from this file.

Rules:

- alias must resolve from the household config
- unknown alias is a validation error
- voice send still requires confirmation even if alias exists

## Interaction with capability state

If household config is missing or invalid:

- `telegram-send` is `unconfigured`
- `telegram-list-aliases` is `unconfigured`

This is the default baseline behavior.

Demo aliases are allowed only when a separate explicit demo configuration path
exists.
They must not appear implicitly because the real household config is missing.
That explicit demo path is documented in `docs/ops/demo-household-config.md`.

## Testing implications

Tests should cover:

- valid household config load
- malformed TOML
- invalid trusted chat ids
- invalid alias keys
- missing description
- unknown alias resolution
- trusted versus untrusted chat behavior
- readiness/config failure behavior
