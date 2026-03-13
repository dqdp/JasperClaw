from types import SimpleNamespace


def test_platform_cli_migrate_applies_pending_versions(monkeypatch, capsys) -> None:
    from platform_db.cli import main
    from platform_db.runner import MigrationStatus

    class _FakeRunner:
        def __init__(self, database_url: str, migrations_dir=None) -> None:
            _ = migrations_dir
            self.database_url = database_url
            self.ensure_current_calls = 0

        def status(self) -> MigrationStatus:
            return MigrationStatus(
                applied_versions=("0001_initial_schema",),
                pending_versions=("0002_conversation_updates",),
            )

        def ensure_current(self) -> None:
            self.ensure_current_calls += 1

    fake_runner = _FakeRunner("postgresql://assistant:test@postgres:5432/assistant")

    monkeypatch.setattr(
        "platform_db.cli._load_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://assistant:test@postgres:5432/assistant"
        ),
    )
    monkeypatch.setattr("platform_db.cli.MigrationRunner", lambda database_url, migrations_dir=None: fake_runner)

    assert main(["migrate"]) == 0
    assert fake_runner.ensure_current_calls == 1
    assert "Applied migrations: 0002_conversation_updates" in capsys.readouterr().out
