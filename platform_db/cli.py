import argparse
import os
import sys
from types import SimpleNamespace

import psycopg
from psycopg.conninfo import make_conninfo

from platform_db.runner import MigrationRunner, default_migrations_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platform-db")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply pending SQL migrations")
    return parser


def _load_settings() -> SimpleNamespace:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return SimpleNamespace(database_url=database_url)

    host = os.getenv("POSTGRES_HOST", "").strip()
    port = os.getenv("POSTGRES_PORT", "5432").strip()
    db = os.getenv("POSTGRES_DB", "").strip()
    user = os.getenv("POSTGRES_USER", "").strip()
    password = os.getenv("POSTGRES_PASSWORD", "").strip()
    if not all((host, db, user, password)):
        raise RuntimeError("Database connection environment is incomplete")
    return SimpleNamespace(
        database_url=make_conninfo(
            host=host,
            port=port,
            dbname=db,
            user=user,
            password=password,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        settings = _load_settings()
        runner = MigrationRunner(
            database_url=settings.database_url,
            migrations_dir=default_migrations_dir(),
        )
        if args.command == "migrate":
            status = runner.status()
            if status.is_current:
                print("Database schema already current")
                return 0
            runner.ensure_current()
            print(f"Applied migrations: {', '.join(status.pending_versions)}")
            return 0
    except (RuntimeError, psycopg.Error) as exc:
        print(f"Migration command failed: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
