# Features

Purpose:
This directory explains canonical feature behavior without forcing you to infer it only from code.

Start here:
- `chat.md`: open first when working on the main request path.

Index:
- `capability-planning.md`: open when defining how text or voice requests map into typed capabilities, policy checks, confirmation, and execution.
- `capability-discovery.md`: open when defining how the assistant should explain capabilities, commands, aliases, moods, and `demo|real|unconfigured` state to users.
- `chat.md`: open when implementing or tracing the canonical text-chat flow.
- `default-product-baseline.md`: open when planning the next batteries-included default startup with voice, Spotify, and Telegram send capabilities.
- `default-product-baseline-tdd-checklist.md`: open when implementing the default-baseline expansion and you need the agreed tests-first execution order across capability state, Spotify, Telegram, and smoke.
- `first-run-experience.md`: open when defining what a user should see and be able to do immediately after the default startup.
- `memory.md`: open when changing derived memory behavior, retrieval, or provenance rules.
- `spotify-station-behavior.md`: open when defining the user-facing semantics of `spotify-start-station`, including seed kinds, clarification, playback-set shape, and prerequisite failures.
- `telegram-send-confirmation.md`: open when defining the user-facing confirmation, cancellation, timeout, and duplicate-protection rules for voice-driven `telegram-send`.
- `voice-tts-implementation-plan.md`: open when implementing the first real `tts-service` slice from the agreed Piper-default plan.
- `voice-tts-stack.md`: open when choosing the first real TTS backend or shaping the future voice runtime boundary.
