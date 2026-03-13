This directory stores the canonical forward-only SQL migration history for the
shared Postgres schema.

Ownership notes:
- migration execution authority lives in `platform-db`
- table ownership remains explicit per service/slice
- `agent-api` keeps only a thin compatibility shim for readiness and legacy CLI

Open these files when:
- adding or reviewing concrete schema changes
- checking migration ordering
- verifying table-owner comments and shared-schema boundaries
