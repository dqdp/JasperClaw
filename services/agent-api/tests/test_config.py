from psycopg.conninfo import conninfo_to_dict

from app.api import deps
from app.core.config import get_settings


def test_get_settings_preserves_reserved_characters_in_postgres_credentials(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "postgres.test")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "assistant")
    monkeypatch.setenv("POSTGRES_USER", "assistant:name")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:/#word")
    get_settings.cache_clear()
    deps.get_chat_repository.cache_clear()
    deps.get_migration_runner.cache_clear()

    settings = get_settings()
    conninfo = conninfo_to_dict(settings.database_url)

    assert conninfo["host"] == "postgres.test"
    assert conninfo["port"] == "5432"
    assert conninfo["dbname"] == "assistant"
    assert conninfo["user"] == "assistant:name"
    assert conninfo["password"] == "p@ss:/#word"
