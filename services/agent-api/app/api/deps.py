from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings, get_settings
from app.repositories import ChatRepository, PostgresChatRepository
from app.services.chat import ChatService


@lru_cache
def get_ollama_client() -> OllamaChatClient:
    settings = get_settings()
    return OllamaChatClient(
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


@lru_cache
def get_chat_repository() -> ChatRepository:
    settings = get_settings()
    return PostgresChatRepository(database_url=settings.database_url)


def get_app_settings() -> Settings:
    return get_settings()


def get_chat_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    ollama_client: Annotated[OllamaChatClient, Depends(get_ollama_client)],
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
) -> ChatService:
    return ChatService(
        settings=settings,
        ollama_client=ollama_client,
        repository=repository,
    )
