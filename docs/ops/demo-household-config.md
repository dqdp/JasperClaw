# Demo Household Config Contract

## Purpose

Define the explicit demo-only household configuration path for the planned
default product baseline.

This contract answers one operational question:

- when should Telegram household capabilities be `demo` instead of
  `unconfigured`?

## Scope

Applies to the planned default startup only.

It governs:

- explicit demo alias discovery
- explicit demo `telegram-send`
- precedence between real, demo, and missing household config

## Non-goals

- live Telegram ingress configuration
- implicit fake aliases when no config exists
- a second schema separate from the real household config
- replacing the real household contract

## Related contracts

- `docs/ops/household-config.md`
- `docs/features/default-product-baseline.md`
- `docs/features/first-run-experience.md`
- `docs/features/telegram-send-confirmation.md`

## Why this contract exists

The product plan now distinguishes three capability states:

- `real`
- `demo`
- `unconfigured`

For Telegram household capabilities, `demo` must come from an explicit package
or operator choice.
It must not be inferred from the absence of the real household config.

Without this document, the plan leaves one ambiguous gap:

- whether first-run Telegram discovery and send are actually part of the
  default package or only aspirational behavior

## Recommended file location

Recommended default path:

- `infra/config/household.demo.toml`

The exact path may be configurable, but the runtime contract should treat the
demo household config as a separate explicit artifact rather than overloading
the real `household.toml`.

## Schema

The demo household config should reuse the same schema as the real household
config documented in `docs/ops/household-config.md`.

Minimum shape:

```toml
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.demo_home]
chat_id = 1001
description = "Demo home chat"
```

The point of the demo file is different, but the shape should remain the same
to avoid branching the alias-resolution contract.

## Precedence rules

The intended precedence order is:

1. real household config
2. explicit demo household config
3. no household config

This means:

- if valid real household config is present, Telegram household capabilities are
  `real`
- if real config is absent and valid demo household config is present,
  Telegram household capabilities are `demo`
- if neither valid config exists, Telegram household capabilities are
  `unconfigured`

The runtime should not silently merge real and demo alias sets.

## Packaging rule

The target default startup may ship with:

- real household config
- or explicit demo household config

If it ships with neither, Telegram send and alias discovery remain
`unconfigured`, and the startup package does not satisfy the full intended
first-run baseline.

## Demo behavior

When the demo household config is active:

- `telegram-list-aliases` is `demo`
- `telegram-send` is `demo`
- discovery must disclose that aliases are demo-only
- send execution must preserve the same confirmation and audit shape as the
  real path
- the system must not claim that a real Telegram household message was sent

The demo path exists to exercise orchestration and product UX, not to simulate
live Telegram delivery invisibly.

## Demo alias presentation

Demo aliases should be operator-defined and user-discoverable.

Recommended rules:

- descriptions should make the demo nature obvious
- discovery surfaces should already disclose `demo` capability state before
  listing aliases
- raw `chat_id` values remain hidden from the user

The system should avoid presenting demo aliases as if they were real household
contacts.

## Trusted-chat behavior

If the demo package also exercises Telegram bot commands, the same trusted-chat
concept applies.

Implications:

- demo trusted chats must still be explicit
- untrusted chats must still receive only a bounded local rejection
- the demo path must not weaken the trusted-chat policy

If the demo package does not expose live Telegram ingress, the trusted-chat
data may be inert, but the schema should still remain consistent.

## Validation rules

The demo file should be validated with the same structural rules as the real
household config:

- valid TOML
- valid `trusted_chat_ids`
- valid alias keys
- valid positive `chat_id`
- non-empty alias descriptions

Invalid demo config should not silently downgrade to implicit fake aliases.

## Startup behavior

Recommended startup behavior:

- invalid real config is a configuration error for the real path
- invalid demo config is a configuration error for the demo path
- missing demo config is not itself an error
- missing both real and demo config leaves Telegram household capabilities
  `unconfigured`

This keeps demo behavior explicit and fail-closed.

## Acceptance criteria

The demo household contract is acceptable when:

- `demo` and `unconfigured` are no longer ambiguous for Telegram household
  capabilities
- the demo path uses an explicit file rather than implicit fake aliases
- the demo file reuses the real household schema
- precedence between real, demo, and missing config is explicit
- discovery/help surfaces can explain demo aliases honestly
