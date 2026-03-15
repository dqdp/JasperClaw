import os
from dataclasses import dataclass
from functools import lru_cache
from shared_infra.postgres_conninfo import load_database_conninfo_from_env


_PLACEHOLDER_SECRET_VALUES = frozenset({"", "change-me"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class Settings:
    ollama_base_url: str
    ollama_chat_model: str
    ollama_fast_chat_model: str
    ollama_timeout_seconds: float
    database_url: str
    internal_openai_api_key: str
    ollama_embed_model: str = ""
    memory_enabled: bool = False
    memory_top_k: int = 3
    memory_min_score: float = 0.35
    search_base_url: str = ""
    search_api_key: str = ""
    web_search_enabled: bool = False
    web_search_top_k: int = 3
    web_search_timeout_seconds: float = 5.0
    spotify_base_url: str = "https://api.spotify.com"
    spotify_access_token: str = ""
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = ""
    spotify_refresh_token: str = ""
    spotify_demo_enabled: bool = False
    spotify_timeout_seconds: float = 5.0
    spotify_search_top_k: int = 3
    spotify_playlist_top_k: int = 5
    spotify_station_top_k: int = 20
    telegram_bot_token: str = ""
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_timeout_seconds: float = 5.0
    household_config_path: str = ""
    demo_household_config_path: str = ""
    model_owner: str = "local-assistant"
    voice_enabled: bool = False
    stt_base_url: str = "http://stt-service:8080"
    stt_timeout_seconds: float = 60.0
    stt_max_file_bytes: int = 26214400
    tts_base_url: str = "http://tts-service:8080"
    tts_default_voice: str = "assistant-default"
    tts_timeout_seconds: float = 30.0

    @property
    def public_profiles(self) -> tuple[str, str]:
        return ("assistant-v1", "assistant-fast")

    @property
    def default_public_profile(self) -> str:
        return self.public_profiles[0]

    def is_spotify_client_configured(self) -> bool:
        return bool(
            self.spotify_access_token
            or (self.spotify_client_id and self.spotify_client_secret)
        )

    def is_spotify_real_configured(self) -> bool:
        # Discovery uses the stricter baseline contract: refresh-capable auth is
        # required for "real", even while the older execution scaffold still exists.
        return bool(
            self.spotify_client_id
            and self.spotify_client_secret
            and self.spotify_redirect_uri
            and self.spotify_refresh_token
        )

    def is_spotify_demo_configured(self) -> bool:
        return self.spotify_demo_enabled and not self.is_spotify_real_configured()

    def is_spotify_baseline_configured(self) -> bool:
        return self.is_spotify_real_configured() or self.is_spotify_demo_configured()


def _normalize_required_secret(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized.casefold() in _PLACEHOLDER_SECRET_VALUES:
        return ""
    return normalized


def is_configured_required_secret(value: str | None) -> bool:
    return bool(_normalize_required_secret(value))


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in _TRUE_VALUES


@lru_cache
def get_settings() -> Settings:
    ollama_chat_model = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:8b")
    database_url = load_database_conninfo_from_env(
        default_host="postgres",
        default_port="5432",
        default_db="assistant",
        default_user="assistant",
        default_password="change-me",
    )
    return Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        ollama_chat_model=ollama_chat_model,
        ollama_fast_chat_model=os.getenv("OLLAMA_FAST_CHAT_MODEL", ollama_chat_model),
        ollama_embed_model=os.getenv("OLLAMA_EMBED_MODEL", "").strip(),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30")),
        database_url=database_url,
        internal_openai_api_key=_normalize_required_secret(
            os.getenv("INTERNAL_OPENAI_API_KEY", "change-me")
        ),
        memory_enabled=_get_bool_env("MEMORY_ENABLED", default=False),
        memory_top_k=int(os.getenv("MEMORY_TOP_K", "3")),
        memory_min_score=float(os.getenv("MEMORY_MIN_SCORE", "0.35")),
        search_base_url=os.getenv("SEARCH_BASE_URL", "").strip(),
        search_api_key=(os.getenv("SEARCH_API_KEY", "") or "").strip(),
        web_search_enabled=_get_bool_env("WEB_SEARCH_ENABLED", default=False),
        web_search_top_k=int(os.getenv("WEB_SEARCH_TOP_K", "3")),
        web_search_timeout_seconds=float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "5")),
        spotify_base_url=(
            os.getenv("SPOTIFY_BASE_URL", "https://api.spotify.com").strip()
            or "https://api.spotify.com"
        ),
        spotify_access_token=(os.getenv("SPOTIFY_ACCESS_TOKEN", "") or "").strip(),
        spotify_client_id=(os.getenv("SPOTIFY_CLIENT_ID", "") or "").strip(),
        spotify_client_secret=(os.getenv("SPOTIFY_CLIENT_SECRET", "") or "").strip(),
        spotify_redirect_uri=(os.getenv("SPOTIFY_REDIRECT_URI", "") or "").strip(),
        spotify_refresh_token=(os.getenv("SPOTIFY_REFRESH_TOKEN", "") or "").strip(),
        spotify_demo_enabled=_get_bool_env("SPOTIFY_DEMO_ENABLED", default=False),
        spotify_timeout_seconds=float(os.getenv("SPOTIFY_TIMEOUT_SECONDS", "5")),
        spotify_search_top_k=int(os.getenv("SPOTIFY_SEARCH_TOP_K", "3")),
        spotify_playlist_top_k=int(os.getenv("SPOTIFY_PLAYLIST_TOP_K", "5")),
        spotify_station_top_k=int(os.getenv("SPOTIFY_STATION_TOP_K", "20")),
        telegram_bot_token=_normalize_required_secret(
            os.getenv("TELEGRAM_BOT_TOKEN", "")
        ),
        telegram_api_base_url=(
            os.getenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org").strip()
            or "https://api.telegram.org"
        ),
        telegram_timeout_seconds=float(os.getenv("TELEGRAM_TIMEOUT_SECONDS", "5")),
        household_config_path=(os.getenv("HOUSEHOLD_CONFIG_PATH", "") or "").strip(),
        demo_household_config_path=(
            os.getenv("DEMO_HOUSEHOLD_CONFIG_PATH", "") or ""
        ).strip(),
        voice_enabled=_get_bool_env("VOICE_ENABLED", default=False),
        stt_base_url=(
            os.getenv("STT_BASE_URL", "http://stt-service:8080").strip()
            or "http://stt-service:8080"
        ),
        stt_timeout_seconds=float(os.getenv("STT_TIMEOUT_SECONDS", "60")),
        stt_max_file_bytes=max(int(os.getenv("STT_MAX_FILE_BYTES", "26214400")), 1),
        tts_base_url=(
            os.getenv("TTS_BASE_URL", "http://tts-service:8080").strip()
            or "http://tts-service:8080"
        ),
        tts_default_voice=(
            os.getenv("TTS_DEFAULT_VOICE", "assistant-default").strip()
            or "assistant-default"
        ),
        tts_timeout_seconds=float(os.getenv("TTS_TIMEOUT_SECONDS", "30")),
    )
