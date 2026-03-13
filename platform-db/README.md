This directory is the neutral operational home for shared Postgres schema changes.

Contents:
- `migrations/`: canonical forward-only SQL history
- `Dockerfile`: one-shot migration image used by compose/deploy

Use `python -m platform_db.cli migrate` inside the `platform-db` image to apply
pending schema changes before serving traffic.
