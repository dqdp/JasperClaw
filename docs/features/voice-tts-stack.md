# Voice TTS Stack

## Purpose

Define the recommended text-to-speech stack for the future voice slice without
silently coupling the implementation to one runtime too early.

This document is a proposal for discussion.

It does not by itself replace accepted ADRs or the current architecture text.

## Context

The repository already fixes these invariants:

- voice is in v1 scope but starts after the text path is stable
- `agent-api` remains the only public voice ingress
- `tts-service` remains a distinct runtime boundary behind `agent-api`
- the current placeholder `POST /v1/audio/speech` contract already returns binary
  audio

At the same time, the architecture text currently names `Piper` as the default
`tts-service` runtime.

That is now too specific for a long-lived implementation because:

- the original `rhasspy/piper` repository is archived
- local TTS options have improved materially
- cloud providers now offer very strong low-latency and expressive TTS paths
- language coverage, latency, hardware profile, and privacy requirements pull in
  different directions

So the real design question is no longer:

- "should we use Piper or not"

The real design question is:

- "what stable service contract and backend strategy let us adopt a good local
  default now without locking the architecture to one engine"

## Scope

This document covers:

- the `agent-api -> tts-service` boundary
- local versus provider-backed TTS backend strategy
- recommended v1 implementation shape
- test and rollout expectations for the first real TTS slice

It does not cover:

- speech-to-text engine choice
- duplex or realtime voice session orchestration
- canonical storage for voice artifacts
- mobile playback UX
- cloud billing or quota management beyond the adapter boundary

## Existing constraints

- `agent-api` keeps the public OpenAI-compatible `/v1/audio/speech` interface
- `tts-service` remains an internal runtime service, not a public surface
- voice readiness must stay optional unless voice is explicitly enabled
- the first real TTS slice must not destabilize the core text path
- the system targets self-hosted, single-host operability by default

## Current working assumptions

For the current planning pass, assume:

- Russian support is required in the first working slice
- GPU is acceptable, but VRAM is still a scarce resource
- the default voice path should remain local-first rather than cloud-first
- the first shipping slice should prioritize operational simplicity over premium
  voice quality

## Hidden assumptions to make explicit

- "voice support" does not automatically mean low-latency streaming synthesis
- "modern stack" may mean different things:
  - best offline quality
  - lowest latency
  - easiest ops
  - best multilingual support
  - strongest voice cloning
- a strong English-only local model is not automatically a good default if the
  product must speak Russian or other languages
- a cloud TTS provider can be technically excellent and still be the wrong v1
  default for a self-hosted stack

## Decision drivers

- correctness and stable public contract
- offline viability
- language coverage, especially whether Russian matters
- latency
- hardware requirements
- operational simplicity on one host
- extraction path for later provider adapters

## Candidate approaches

### Approach A: hard-code `tts-service` to a Piper-compatible runtime

Shape:

- keep the current architecture text literally true
- implement `tts-service` as a thin HTTP wrapper over one Piper-compatible
  engine
- expose a small fixed voice set

Advantages:

- smallest initial scope
- easiest CPU-first deployment path
- good fit for a local-only baseline

Disadvantages:

- hard-codes an engine choice into the service boundary
- makes future migration to a better local runtime or a cloud adapter more
  expensive
- inherits upstream uncertainty from the archived `rhasspy/piper` baseline

### Approach B: keep `tts-service` stable, make the engine pluggable

Shape:

- keep `agent-api -> tts-service -> /speak`
- introduce an internal `TtsEngine` adapter boundary inside `tts-service`
- route public voice IDs through a backend-owned voice registry
- allow one active default local engine plus optional future provider adapters

Advantages:

- preserves the accepted service topology
- avoids binding the architecture to one vendor or runtime
- gives a clean path to local and cloud backends later
- keeps public voice identifiers stable

Disadvantages:

- more design work up front
- requires explicit adapter and voice-registry tests early

### Approach C: skip local-first and go straight to a cloud provider

Shape:

- `tts-service` becomes mainly a normalization and credential boundary
- synthesis is delegated to a provider such as Cartesia, ElevenLabs, or OpenAI

Advantages:

- strongest immediate quality and low-latency options
- less local model packaging work

Disadvantages:

- worse fit for a self-hosted product direction
- introduces network, cost, and privacy dependencies into the first real voice
  slice
- makes voice availability more sensitive to external provider failures

## Runtime candidates

### Piper-compatible baseline

Best fit when:

- offline operation is required
- CPU-first deployment matters
- the initial goal is "reliable local speech" more than "best possible voice
  quality"

Risks:

- the original upstream is archived, so this should be treated as a runtime
  family choice, not as a permanent hard dependency on one repository

### XTTS v2

Best fit when:

- Russian support is required
- multilingual quality matters
- GPU use is acceptable
- the team wants a stronger local quality baseline than a Piper-style engine

Trade-off:

- materially heavier runtime and ops profile than a Piper-style baseline

### Kokoro

Best fit when:

- English-first local TTS quality is the primary driver
- very small modern local models are attractive

Trade-off:

- should not be assumed to be the default if Russian or broader multilingual
  support is required

### Cloud providers

Likely later adapters:

- Cartesia for low-latency conversational TTS
- ElevenLabs for expressive multilingual premium voices
- OpenAI or similar providers when policy and deployment constraints permit

Trade-off:

- better quality and latency in many cases, but worse alignment with the default
  self-hosted operating model

## Recommendation

Use **Approach B**.

That means:

- keep `agent-api` unchanged as the public voice ingress
- keep `tts-service` as the internal TTS boundary
- do **not** hard-code the implementation to one engine
- introduce a pluggable internal `TtsEngine` contract and a backend-owned voice
  registry

Recommended v1 backend policy:

- default to a **local engine**
- treat cloud providers as later optional adapters

Recommended v1 engine choice for the current assumptions:

- default v1 engine: **Piper-compatible**
- optional premium GPU profile: **XTTS v2**
- optional later evaluation path: **Kokoro** for English-first compact local
  deployments

Why Piper-compatible is the current default recommendation:

- Russian matters in the first real slice
- the voice slice is not the core differentiator of the product today
- GPU and especially VRAM should stay available for the core text/runtime path
- the goal of the first shipping slice is "reliable local speech" rather than
  premium voice quality

Why XTTS v2 still remains worth keeping as a premium profile:

- it offers a stronger multilingual quality ceiling
- it is a better fit if voice quality becomes product-relevant later
- it can be enabled selectively where GPU headroom exists

## Narrowed v1 decision

To keep the first real voice slice executable rather than over-generalized,
apply these explicit v1 constraints:

- exactly one TTS engine is configured per deployment
- there is no per-request engine routing
- there is no fallback across engines inside one request
- synthesis is buffered and non-streaming
- the first slice returns only `audio/wav`
- the voice registry is static configuration, not dynamic state
- voice cloning and speaker enrollment are out of scope
- concurrency must be explicitly bounded by config, with a conservative default
  of one synthesis job at a time
- the default deployment profile assumes a Piper-compatible local runtime
- an XTTS-backed GPU profile is allowed as an optional premium deployment mode

If the product later requires streaming synthesis, dynamic provider selection, or
voice cloning, that should be treated as a later slice rather than folded into
the first real TTS delivery.

## Resource assumptions for XTTS premium profile

The optional XTTS deployment profile should assume:

- one host with an available GPU
- one synthesis job in flight at a time by default
- explicit max input length limits to avoid unbounded synthesis latency
- bounded queueing or immediate rejection under pressure, rather than implicit
  parallel fan-out
- warm-up cost is acceptable as a deployment-time or first-request cost

If those assumptions do not hold in a target environment, switch that
environment to the Piper-compatible default profile instead of widening the XTTS
profile.

## Proposed internal shape

### Public contract

Keep `agent-api` public behavior stable:

- `POST /v1/audio/speech`
- request includes `model`, `input`, and optional `voice`
- the first real slice returns `audio/wav`
- other formats can be added later behind the same public endpoint if needed

### Internal service contract

`tts-service` owns:

- request validation for synthesis-specific rules
- voice lookup from public voice ID to engine-specific config
- engine invocation
- bounded concurrency and backpressure
- stable error normalization

`tts-service` should not expose:

- raw provider-specific voice IDs as the main public contract
- provider-specific response semantics directly to `agent-api`

### Engine contract

The internal engine boundary should look conceptually like:

- `synthesize(text, voice) -> wav bytes + metadata`
- the first real slice assumes one output format
- engine-specific model names stay behind the adapter
- engine-specific GPU/runtime initialization stays behind the adapter

### Voice registry

The voice registry should map:

- public voice ID
- engine type
- engine voice/model config
- output defaults
- optional language metadata

This keeps public voice identifiers stable even if the backend runtime changes.

For v1, the registry should live in static configuration rather than in a
database or mutable control-plane state.

## Non-goals for the first real TTS slice

- realtime bidirectional voice sessions
- dynamic voice cloning in the default path
- per-request provider routing
- fallback across multiple TTS engines inside one request
- persistent voice artifact storage

## Test contract for the first implementation slice

### `agent-api`

- `/v1/audio/speech` authenticates like other `/v1/*` routes
- unsupported voice IDs fail as validation or explicit voice errors
- voice-disabled deployments return `voice_not_enabled`
- successful responses preserve `audio/wav`

### `tts-service`

- `/speak` validates required fields
- voice registry resolves public voice IDs deterministically
- the configured engine can synthesize a real sample
- engine failures map into stable machine-readable errors
- concurrency limits are enforced deterministically

### Integration

- `agent-api -> tts-service` happy-path smoke test
- one real Piper-compatible backend smoke test in Docker for the default profile
- one XTTS smoke test later only if the premium GPU profile is activated
- readiness semantics remain text-path-first unless voice is enabled

## Rollout recommendation

1. Keep the public `/v1/audio/speech` contract stable.
2. Implement `tts-service` with a pluggable engine boundary.
3. Ship a Piper-compatible backend as the default local backend first.
4. Add observability and smoke coverage.
5. Add an XTTS premium GPU profile only if voice quality becomes worth the VRAM
   budget.
6. Only after that evaluate a cloud adapter.
7. Revisit streaming or additional output formats only after the buffered path is
   stable.

## Decision summary

The recommended v1 direction is:

- **not** "Piper forever"
- **not** "cloud first"
- **not** "pick the newest model and couple the service to it"

The recommended direction is:

- **stable `tts-service` contract**
- **pluggable engine boundary**
- **local-first default**
- **Piper-compatible runtime as the shipping default**
- **XTTS v2 as an optional premium GPU deployment profile**

## Discussion checkpoints

Before implementation starts, the team should explicitly answer:

- Is offline operation required by default even for GPU-capable environments?
- Do we need a CPU-only deployment profile in the first implementation wave?
- Is a cloud provider allowed as an optional adapter in later phases?
