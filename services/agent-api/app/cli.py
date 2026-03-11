import argparse

from app.core.config import get_settings
from app.migrations import MigrationRunner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-api")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply pending SQL migrations")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    runner = MigrationRunner(database_url=settings.database_url)

    if args.command == "migrate":
        status = runner.status()
        if status.is_current:
            print("Database schema already current")
            return 0

        runner.ensure_current()
        applied = ", ".join(status.pending_versions)
        print(f"Applied migrations: {applied}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
