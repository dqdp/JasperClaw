import argparse
import sys
from types import SimpleNamespace

import psycopg

from platform_db.conninfo import load_database_conninfo_from_env
from platform_db.runner import MigrationRunner, default_migrations_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platform-db")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply pending SQL migrations")
    return parser


def _load_settings() -> SimpleNamespace:
    return SimpleNamespace(
        database_url=load_database_conninfo_from_env()
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
