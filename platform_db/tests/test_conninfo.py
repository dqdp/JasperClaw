import pytest
from psycopg.conninfo import conninfo_to_dict


def test_load_database_conninfo_from_env_prefers_database_url() -> None:
    from platform_db.conninfo import load_database_conninfo_from_env

    conninfo = load_database_conninfo_from_env(
        env={
            "DATABASE_URL": " postgres://example.test/dbname ",
            "POSTGRES_HOST": "ignored-host",
            "POSTGRES_DB": "ignored-db",
            "POSTGRES_USER": "ignored-user",
            "POSTGRES_PASSWORD": "ignored-password",
        }
    )

    assert conninfo == "postgres://example.test/dbname"


def test_load_database_conninfo_from_env_builds_conninfo_with_reserved_chars() -> None:
    from platform_db.conninfo import load_database_conninfo_from_env

    conninfo = load_database_conninfo_from_env(
        env={
            "POSTGRES_HOST": "postgres.test",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "assistant",
            "POSTGRES_USER": "assistant:name",
            "POSTGRES_PASSWORD": "p@ss:/#word",
        }
    )

    parsed = conninfo_to_dict(conninfo)
    assert parsed["host"] == "postgres.test"
    assert parsed["port"] == "5432"
    assert parsed["dbname"] == "assistant"
    assert parsed["user"] == "assistant:name"
    assert parsed["password"] == "p@ss:/#word"


def test_load_database_conninfo_from_env_applies_defaults() -> None:
    from platform_db.conninfo import load_database_conninfo_from_env

    conninfo = load_database_conninfo_from_env(
        env={},
        default_host="postgres",
        default_port="5432",
        default_db="assistant",
        default_user="assistant",
        default_password="change-me",
    )

    parsed = conninfo_to_dict(conninfo)
    assert parsed["host"] == "postgres"
    assert parsed["port"] == "5432"
    assert parsed["dbname"] == "assistant"
    assert parsed["user"] == "assistant"
    assert parsed["password"] == "change-me"


def test_load_database_conninfo_from_env_rejects_incomplete_env() -> None:
    from platform_db.conninfo import load_database_conninfo_from_env

    with pytest.raises(RuntimeError, match="Database connection environment is incomplete"):
        load_database_conninfo_from_env(
            env={
                "POSTGRES_HOST": "postgres.test",
                "POSTGRES_DB": "assistant",
                "POSTGRES_USER": "assistant",
            }
        )
