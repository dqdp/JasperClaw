# Tools Gateway

Purpose:
This directory is future extraction scaffold for a possible standalone tools execution service.

Start here:
- `README.md`: open first to confirm that this path is not an active runtime service in the current architecture.

Index:
- `Dockerfile`: open only when auditing leftover scaffold build behavior.
- `pyproject.toml`: open only when auditing legacy placeholder test configuration.
- `requirements.txt`: open only when auditing legacy placeholder dependencies.
- `app/`: open only when checking what the leftover placeholder currently does.
- `tests/`: open only when auditing the placeholder health check.

Notes:
- This directory is not part of the accepted active v1 runtime architecture today.
- Current accepted control-plane rule: tool planning, policy, approvals, audit, and client-facing error mapping stay in `agent-api`.
- If a standalone tools runtime is introduced later, it must be an extraction of the internal tools execution boundary, not a second public control plane.
