from functools import lru_cache

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings, get_settings
from app.services.chat import ChatService


@lru_cache
def get_ollama_client() -> OllamaChatClient:
    settings = get_settings()
    return OllamaChatClient(
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


def get_chat_service() -> ChatService:
    return ChatService(settings=get_settings(), ollama_client=get_ollama_client())


def get_app_settings() -> Settings:
    return get_settings()
