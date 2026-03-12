# Agent API Migrations

Purpose:
This directory owns migration execution and the ordered SQL history for `agent-api` persistence.

Start here:
- `runner.py`: open first for migration application logic.

Index:
- `runner.py`: open when changing how pending migrations are discovered and applied.
- `sql/`: open when adding or reviewing concrete schema changes.
