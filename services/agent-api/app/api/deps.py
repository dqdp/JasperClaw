from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.clients.ollama import OllamaChatClient
from app.clients.search import WebSearchClient
from app.clients.spotify import SpotifyClient
from app.clients.stt import SttClient
from app.clients.tts import TtsClient
from app.core.config import Settings, get_settings
from app.migrations import MigrationRunner
from app.modules.chat.facade import ChatFacade
from app.modules.chat.formatters import ChatPromptFormatter
from app.modules.chat.memory import MemoryService
from app.repositories import ChatRepository, PostgresChatRepository
from app.services.chat import ChatService
from app.services.readiness import ReadinessService


@lru_cache
def get_ollama_client() -> OllamaChatClient:
    settings = get_settings()
    return OllamaChatClient(
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


@lru_cache
def get_migration_runner() -> MigrationRunner:
    settings = get_settings()
    return MigrationRunner(database_url=settings.database_url)


@lru_cache
def get_chat_repository() -> ChatRepository:
    settings = get_settings()
    return PostgresChatRepository(
        database_url=settings.database_url,
        default_public_profile=settings.default_public_profile,
    )


@lru_cache
def get_web_search_client() -> WebSearchClient | None:
    settings = get_settings()
    if not settings.search_base_url or not settings.search_api_key:
        return None
    return WebSearchClient(
        base_url=settings.search_base_url,
        api_key=settings.search_api_key,
        timeout_seconds=settings.web_search_timeout_seconds,
    )


@lru_cache
def get_spotify_client() -> SpotifyClient | None:
    settings = get_settings()
    if not settings.is_spotify_client_configured():
        return None
    return SpotifyClient(
        base_url=settings.spotify_base_url,
        access_token=settings.spotify_access_token,
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        redirect_uri=settings.spotify_redirect_uri,
        timeout_seconds=settings.spotify_timeout_seconds,
    )


@lru_cache
def get_stt_client() -> SttClient | None:
    settings = get_settings()
    if not settings.stt_base_url:
        return None
    return SttClient(
        base_url=settings.stt_base_url,
        timeout_seconds=settings.stt_timeout_seconds,
    )


@lru_cache
def get_tts_client() -> TtsClient | None:
    settings = get_settings()
    if not settings.tts_base_url:
        return None
    return TtsClient(
        base_url=settings.tts_base_url,
        timeout_seconds=settings.tts_timeout_seconds,
    )


def get_memory_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    ollama_client: Annotated[OllamaChatClient, Depends(get_ollama_client)],
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
) -> MemoryService:
    return MemoryService(
        settings=settings,
        ollama_client=ollama_client,
        repository=repository,
        prompt_formatter=ChatPromptFormatter(),
    )


def get_app_settings() -> Settings:
    return get_settings()


def get_chat_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    ollama_client: Annotated[OllamaChatClient, Depends(get_ollama_client)],
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    web_search_client: Annotated[
        WebSearchClient | None, Depends(get_web_search_client)
    ],
    spotify_client: Annotated[SpotifyClient | None, Depends(get_spotify_client)],
) -> ChatService:
    return ChatService(
        settings=settings,
        ollama_client=ollama_client,
        repository=repository,
        web_search_client=web_search_client,
        spotify_client=spotify_client,
    )


def get_chat_facade(
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatFacade:
    return ChatFacade(chat_service=chat_service)


def get_readiness_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    ollama_client: Annotated[OllamaChatClient, Depends(get_ollama_client)],
    migration_runner: Annotated[MigrationRunner, Depends(get_migration_runner)],
) -> ReadinessService:
    return ReadinessService(
        settings=settings,
        ollama_client=ollama_client,
        migration_runner=migration_runner,
    )
