import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class Settings:
    ollama_base_url: str
    ollama_chat_model: str
    ollama_fast_chat_model: str
    ollama_timeout_seconds: float
    model_owner: str = "local-assistant"

    @property
    def public_profiles(self) -> tuple[str, str]:
        return ("assistant-v1", "assistant-fast")


@lru_cache
def get_settings() -> Settings:
    ollama_chat_model = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:8b")
    return Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        ollama_chat_model=ollama_chat_model,
        ollama_fast_chat_model=os.getenv("OLLAMA_FAST_CHAT_MODEL", ollama_chat_model),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30")),
    )
