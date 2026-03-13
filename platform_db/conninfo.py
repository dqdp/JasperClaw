import os
from collections.abc import Mapping

from psycopg.conninfo import make_conninfo


def load_database_conninfo_from_env(
    *,
    env: Mapping[str, str] | None = None,
    default_host: str | None = None,
    default_port: str | None = "5432",
    default_db: str | None = None,
    default_user: str | None = None,
    default_password: str | None = None,
) -> str:
    source = os.environ if env is None else env

    database_url = _read_env(source, "DATABASE_URL")
    if database_url:
        return database_url

    host = _read_env(source, "POSTGRES_HOST", default_host)
    port = _read_env(source, "POSTGRES_PORT", default_port)
    db = _read_env(source, "POSTGRES_DB", default_db)
    user = _read_env(source, "POSTGRES_USER", default_user)
    password = _read_env(source, "POSTGRES_PASSWORD", default_password)
    if not all((host, port, db, user, password)):
        raise RuntimeError("Database connection environment is incomplete")

    return make_conninfo(
        host=host,
        port=port,
        dbname=db,
        user=user,
        password=password,
    )


def _read_env(
    env: Mapping[str, str],
    key: str,
    default: str | None = None,
) -> str:
    value = env.get(key)
    if value is None:
        value = default
    return (value or "").strip()
