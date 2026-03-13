from psycopg.conninfo import conninfo_to_dict


def test_load_settings_preserves_reserved_characters_in_credentials(
    monkeypatch,
) -> None:
    from platform_db.cli import _load_settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "postgres.test")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "assistant")
    monkeypatch.setenv("POSTGRES_USER", "assistant:name")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:/#word")

    settings = _load_settings()
    conninfo = conninfo_to_dict(settings.database_url)

    assert conninfo["host"] == "postgres.test"
    assert conninfo["port"] == "5432"
    assert conninfo["dbname"] == "assistant"
    assert conninfo["user"] == "assistant:name"
    assert conninfo["password"] == "p@ss:/#word"
