import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class Settings:
    ollama_base_url: str
    ollama_chat_model: str
    ollama_fast_chat_model: str
    ollama_timeout_seconds: float
    database_url: str
    model_owner: str = "local-assistant"

    @property
    def public_profiles(self) -> tuple[str, str]:
        return ("assistant-v1", "assistant-fast")


@lru_cache
def get_settings() -> Settings:
    ollama_chat_model = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:8b")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        postgres_host = os.getenv("POSTGRES_HOST", "postgres")
        postgres_port = os.getenv("POSTGRES_PORT", "5432")
        postgres_db = os.getenv("POSTGRES_DB", "assistant")
        postgres_user = os.getenv("POSTGRES_USER", "assistant")
        postgres_password = os.getenv("POSTGRES_PASSWORD", "change-me")
        database_url = (
            f"postgresql://{postgres_user}:{postgres_password}"
            f"@{postgres_host}:{postgres_port}/{postgres_db}"
        )
    return Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        ollama_chat_model=ollama_chat_model,
        ollama_fast_chat_model=os.getenv("OLLAMA_FAST_CHAT_MODEL", ollama_chat_model),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30")),
        database_url=database_url,
    )
