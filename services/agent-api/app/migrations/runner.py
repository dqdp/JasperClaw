import psycopg

from app.core.errors import APIError
from shared_infra.migrations import (
    MigrationRunner as _PlatformMigrationRunner,
    MigrationStatus,
    default_migrations_dir as _default_migrations_dir,
)

default_migrations_dir = _default_migrations_dir


class MigrationRunner(_PlatformMigrationRunner):
    """Compatibility shim for service-local readiness and CLI wiring."""

    def ensure_current(self) -> None:
        try:
            super().ensure_current()
        except psycopg.Error as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="storage_unavailable",
                message="Persistent storage unavailable",
            ) from exc

    def status(self) -> MigrationStatus:
        try:
            return super().status()
        except psycopg.Error as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="storage_unavailable",
                message="Persistent storage unavailable",
            ) from exc
