# ADRs

Purpose:
This directory records accepted architecture decisions that constrain implementation and operations.

Start here:
- `0002-agent-api-control-plane.md`: open first when a change might bypass or weaken the canonical control plane.

Index:
- `0001-monorepo.md`: open when reasoning about repository layout and why services live together here.
- `0002-agent-api-control-plane.md`: open when deciding which component owns canonical ingress and orchestration.
- `0003-deploy-via-ssh.md`: open when changing deployment or host rollout mechanics.
- `0004-open-webui-non-canonical-ux-projection.md`: open when working on Open WebUI boundaries or UI-owned state.
- `0005-canonical-assistant-state-model.md`: open when separating transcript, execution audit, and derived memory.
- `0006-agent-api-single-public-surface-layered-internals.md`: open when shaping `agent-api` transport versus internals.
- `0007-tools-boundary-in-process-in-v1.md`: open when evaluating tool extraction or service sprawl.
- `0008-profile-routing-without-automatic-fallback.md`: open when changing model/profile routing or fallback behavior.
- `0009-auth-and-secret-boundaries-for-v1.md`: open when touching auth, trust boundaries, or secret ownership.
- `0010-voice-after-text-path-stability.md`: open when scoping voice work relative to text-path maturity.
- `0011-readiness-observability-and-error-semantics.md`: open when changing probes, telemetry, or failure mapping.
- `0012-capability-gated-agent-actions.md`: open when enabling actions, approvals, sandboxing, or audit requirements.
- `0013-layered-testing-and-linting-gates.md`: open when defining test layers, lint gates, or merge readiness.
- `0014-directory-readmes-and-agent-rules-separation.md`: open when adding or updating local index files or `AGENTS.md` usage.
- `0015-modular-slice-boundaries-and-ownership.md`: open when refactoring internal module seams, ownership boundaries, or migration authority.
- `0016-defer-tools-gateway-extraction-while-keeping-agent-api-as-control-plane.md`: open when deciding whether tool execution should remain in-process or move into a separate runtime service.
