import sys
from pathlib import Path

import psycopg

from app.core.errors import APIError


def _ensure_platform_db_import_path() -> None:
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / "platform_db").is_dir():
            ancestor_str = str(ancestor)
            if ancestor_str not in sys.path:
                sys.path.append(ancestor_str)
            return


_ensure_platform_db_import_path()

from platform_db.runner import MigrationRunner as _PlatformMigrationRunner
from platform_db.runner import MigrationStatus, default_migrations_dir


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
