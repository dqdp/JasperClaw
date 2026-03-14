# Runbooks

Purpose:
This directory contains operator-facing procedures for bootstrap, backup,
restore, deployment, rollback, smoke checks, and Telegram operations.

Start here:
- `deploy.md`: open first for the normal rollout path.

Index:
- `bootstrap-ubuntu-24.04.md`: open when preparing a new production host.
- `backup.md`: open when creating a canonical Postgres backup artifact.
- `deploy.md`: open when performing the standard deployment sequence.
- `memory-inspection.md`: open when tracing memory extraction, retrieval, or lifecycle behavior.
- `restore.md`: open when validating or performing a database restore.
- `rollback.md`: open when reverting a bad rollout.
- `smoke-tests.md`: open when validating the stack after deploy or during incident response.
- `telegram.md`: open when operating Telegram ingress or alert delivery paths.
