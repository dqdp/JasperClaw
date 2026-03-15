# Runbooks

Purpose:
This directory contains operator-facing procedures for bootstrap, backup,
restore, deployment, rollback, smoke checks, and Telegram operations.

Start here:
- `deploy.md`: open first for the normal rollout path.

Index:
- `bootstrap-ubuntu-24.04.md`: open when preparing a new production host.
- `backup.md`: open when creating a canonical Postgres backup artifact.
- `default-baseline-onboarding.md`: open when converting the planned default
  voice-first startup from `demo` or `unconfigured` capability states into a
  real single-household baseline.
- `deploy.md`: open when performing the standard deployment sequence.
- `memory-inspection.md`: open when tracing memory extraction, retrieval, or lifecycle behavior.
- `restore.md`: open when validating or performing a database restore.
- `rollback.md`: open when reverting a bad rollout.
- `smoke-tests.md`: open when validating the stack after deploy or during incident response.
- `spotify-auth-bootstrap.md`: open when defining how the default baseline
  connects to the real household Spotify account using the accepted
  refresh-capable auth model.
- `telegram.md`: open when operating Telegram ingress or alert delivery paths.
