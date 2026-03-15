import base64
from dataclasses import dataclass
from time import time
from urllib.parse import urlencode

import httpx

from app.core.errors import APIError


_DEFAULT_TOKEN_ENDPOINT = "/api/token"
_SPOTIFY_ACCOUNTS_BASE_URL = "https://accounts.spotify.com"
_SPOTIFY_STATION_MOOD_QUERIES = {
    "focus": "focus instrumental",
    "calm": "calm ambient",
    "energy": "energetic upbeat",
    "party": "party dance",
    "sleep": "sleep ambient",
}
_SPOTIFY_STATION_SEED_KINDS = frozenset({"genre", "artist", "track", "mood"})


@dataclass(frozen=True, slots=True)
class SpotifyTrackItem:
    name: str
    artists: str
    uri: str
    album: str | None
    external_url: str | None


@dataclass(frozen=True, slots=True)
class SpotifyPlaylistItem:
    name: str
    owner: str
    uri: str
    external_url: str | None


class SpotifyClient:
    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        refresh_token: str = "",
        timeout_seconds: float,
        max_retries: int = 1,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token.strip()
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._redirect_uri = redirect_uri.strip()
        self._refresh_token = refresh_token.strip()
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(max_retries, 0)
        self._cached_token = self._access_token
        self._token_expires_at: float = float("inf") if self._access_token else 0.0

    def search_tracks(self, *, query: str, limit: int) -> list[SpotifyTrackItem]:
        query_text = query.strip()
        if not query_text:
            raise APIError(
                status_code=400,
                error_type="validation_error",
                code="invalid_request",
                message="search query must be non-empty",
            )

        response = self._authenticated_request(
            "GET",
            f"{self._base_url}/v1/search",
            params={"q": query_text, "type": "track", "limit": str(limit)},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify search provider returned invalid JSON",
            ) from exc

        tracks = payload.get("tracks")
        if not isinstance(tracks, dict):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify search payload is missing tracks",
            )

        raw_items = tracks.get("items")
        if not isinstance(raw_items, list):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify search payload is missing track items",
            )

        results: list[SpotifyTrackItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise APIError(
                    status_code=502,
                    error_type="upstream_error",
                    code="dependency_bad_response",
                    message="Spotify search payload contains invalid track item",
                )
            results.append(self._normalize_search_item(raw_item))
        return results

    def list_playlists(self, *, limit: int) -> list[SpotifyPlaylistItem]:
        response = self._authenticated_request(
            "GET",
            f"{self._base_url}/v1/me/playlists",
            params={"limit": str(limit)},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify playlists provider returned invalid JSON",
            ) from exc

        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify playlists payload is missing items",
            )

        results: list[SpotifyPlaylistItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise APIError(
                    status_code=502,
                    error_type="upstream_error",
                    code="dependency_bad_response",
                    message="Spotify playlists payload contains invalid item",
                )
            results.append(self._normalize_playlist_item(raw_item))
        return results

    def play_playlist(self, *, playlist_uri: str, device_id: str | None = None) -> None:
        self._ensure_playback_target(device_id=device_id)
        payload = {"context_uri": playlist_uri}
        self._authenticated_request(
            "PUT",
            f"{self._base_url}/v1/me/player/play",
            json=payload,
            params=self._build_device_query(device_id),
        )

    def play_track(self, *, track_uri: str, device_id: str | None = None) -> None:
        self._play_track_uris(track_uris=[track_uri], device_id=device_id)

    def start_station(
        self,
        *,
        seed_kind: str,
        seed_value: str,
        limit: int,
        device_id: str | None = None,
    ) -> None:
        normalized_seed_kind = seed_kind.strip().casefold()
        normalized_seed_value = seed_value.strip()
        if normalized_seed_kind not in _SPOTIFY_STATION_SEED_KINDS:
            raise APIError(
                status_code=400,
                error_type="validation_error",
                code="invalid_request",
                message="spotify-start-station requires a supported seed_kind",
            )
        if not normalized_seed_value:
            raise APIError(
                status_code=400,
                error_type="validation_error",
                code="invalid_request",
                message="spotify-start-station requires a non-empty seed_value",
            )
        if limit < 1:
            raise APIError(
                status_code=400,
                error_type="validation_error",
                code="invalid_request",
                message="spotify-start-station requires a positive limit",
            )

        query = self._build_station_query(
            seed_kind=normalized_seed_kind,
            seed_value=normalized_seed_value,
        )
        tracks = self.search_tracks(query=query, limit=limit)
        track_uris = self._dedupe_track_uris(tracks)
        if not track_uris:
            raise APIError(
                status_code=400,
                error_type="validation_error",
                code="invalid_request",
                message="Requested Spotify station returned no playable tracks",
            )
        self._play_track_uris(track_uris=track_uris, device_id=device_id)

    def pause_playback(self, *, device_id: str | None = None) -> None:
        self._ensure_playback_target(device_id=device_id)
        self._authenticated_request(
            "PUT",
            f"{self._base_url}/v1/me/player/pause",
            params=self._build_device_query(device_id),
        )

    def next_track(self, *, device_id: str | None = None) -> None:
        self._ensure_playback_target(device_id=device_id)
        self._authenticated_request(
            "POST",
            f"{self._base_url}/v1/me/player/next",
            params=self._build_device_query(device_id),
        )

    def _resolve_token(self) -> str:
        if self._cached_token and time() < self._token_expires_at:
            return self._cached_token

        if self._refresh_token and self._client_id and self._client_secret:
            self._fetch_refresh_token()
            return self._cached_token

        if self._client_id and self._client_secret:
            self._fetch_client_credentials_token()
            return self._cached_token

        raise APIError(
            status_code=503,
            error_type="dependency_unavailable",
            code="tool_not_configured",
            message="Spotify credentials are not configured",
        )

    def _fetch_client_credentials_token(self) -> None:
        credentials = f"{self._client_id}:{self._client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = self._raw_request(
            "POST",
            f"{_SPOTIFY_ACCOUNTS_BASE_URL}{_DEFAULT_TOKEN_ENDPOINT}",
            headers=headers,
            data=urlencode({"grant_type": "client_credentials"}),
        )
        if response.status_code != 200:
            raise APIError(
                status_code=503 if response.status_code >= 500 else 502,
                error_type=(
                    "dependency_unavailable"
                    if response.status_code >= 500
                    else "upstream_error"
                ),
                code=self._map_status_to_code(response.status_code),
                message="Spotify token endpoint rejected credentials",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify token endpoint returned invalid JSON",
            ) from exc

        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify token endpoint returned invalid payload",
            )
        raw_expires = payload.get("expires_in", 3600)
        expires_in = (
            raw_expires if isinstance(raw_expires, int) and raw_expires > 0 else 3600
        )

        self._cached_token = token.strip()
        self._token_expires_at = time() + float(expires_in) - 60

    def _fetch_refresh_token(self) -> None:
        credentials = f"{self._client_id}:{self._client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = self._raw_request(
            "POST",
            f"{_SPOTIFY_ACCOUNTS_BASE_URL}{_DEFAULT_TOKEN_ENDPOINT}",
            headers=headers,
            data=urlencode(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                }
            ),
        )
        if response.status_code != 200:
            raise APIError(
                status_code=503 if response.status_code >= 500 else 502,
                error_type=(
                    "dependency_unavailable"
                    if response.status_code >= 500
                    else "upstream_error"
                ),
                code=self._map_status_to_code(response.status_code),
                message="Spotify token endpoint rejected refresh token",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify token endpoint returned invalid JSON",
            ) from exc

        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify token endpoint returned invalid payload",
            )
        raw_refresh_token = payload.get("refresh_token")
        if isinstance(raw_refresh_token, str) and raw_refresh_token.strip():
            self._refresh_token = raw_refresh_token.strip()
        raw_expires = payload.get("expires_in", 3600)
        expires_in = (
            raw_expires if isinstance(raw_expires, int) and raw_expires > 0 else 3600
        )

        self._cached_token = token.strip()
        self._token_expires_at = time() + float(expires_in) - 60

    def _normalize_search_item(self, raw_item: dict[str, object]) -> SpotifyTrackItem:
        name = raw_item.get("name")
        uri = raw_item.get("uri")
        if not isinstance(name, str) or not isinstance(uri, str):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify search payload returned invalid track fields",
            )

        artist_names: list[str] = []
        artists_payload = raw_item.get("artists")
        if not isinstance(artists_payload, list):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify search payload returned invalid artists",
            )
        for artist in artists_payload:
            if isinstance(artist, dict):
                artist_name = artist.get("name")
                if isinstance(artist_name, str):
                    artist_names.append(artist_name)
        if not artist_names:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify search payload returned no artists",
            )

        album: str | None = None
        album_payload = raw_item.get("album")
        if isinstance(album_payload, dict):
            album_name = album_payload.get("name")
            if isinstance(album_name, str):
                album = album_name

        external_url: str | None = None
        external_urls = raw_item.get("external_urls")
        if isinstance(external_urls, dict):
            spotify_url = external_urls.get("spotify")
            if isinstance(spotify_url, str):
                external_url = spotify_url

        return SpotifyTrackItem(
            name=name,
            artists=", ".join(artist_names),
            uri=uri,
            album=album,
            external_url=external_url,
        )

    def _normalize_playlist_item(
        self,
        raw_item: dict[str, object],
    ) -> SpotifyPlaylistItem:
        name = raw_item.get("name")
        uri = raw_item.get("uri")
        owner_payload = raw_item.get("owner")
        if not isinstance(name, str) or not name.strip():
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify playlists payload returned invalid playlist name",
            )
        if not isinstance(uri, str) or not uri.strip():
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify playlists payload returned invalid playlist URI",
            )
        if not isinstance(owner_payload, dict):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify playlists payload returned invalid playlist owner",
            )
        owner = owner_payload.get("display_name")
        if not isinstance(owner, str) or not owner.strip():
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify playlists payload returned invalid playlist owner",
            )

        external_url: str | None = None
        external_urls = raw_item.get("external_urls")
        if isinstance(external_urls, dict):
            spotify_url = external_urls.get("spotify")
            if isinstance(spotify_url, str):
                external_url = spotify_url

        return SpotifyPlaylistItem(
            name=name,
            owner=owner,
            uri=uri,
            external_url=external_url,
        )

    @staticmethod
    def _build_device_query(device_id: str | None) -> dict[str, str]:
        if not device_id:
            return {}
        return {"device_id": device_id.strip()} if device_id.strip() else {}

    def _play_track_uris(
        self,
        *,
        track_uris: list[str],
        device_id: str | None,
    ) -> None:
        self._ensure_playback_target(device_id=device_id)
        payload = {"uris": track_uris}
        self._authenticated_request(
            "PUT",
            f"{self._base_url}/v1/me/player/play",
            json=payload,
            params=self._build_device_query(device_id),
        )

    def _build_station_query(self, *, seed_kind: str, seed_value: str) -> str:
        if seed_kind == "mood":
            query = _SPOTIFY_STATION_MOOD_QUERIES.get(seed_value.casefold())
            if query is None:
                raise APIError(
                    status_code=400,
                    error_type="validation_error",
                    code="invalid_request",
                    message="spotify-start-station requires a supported mood seed",
                )
            return query
        return seed_value

    @staticmethod
    def _dedupe_track_uris(tracks: list[SpotifyTrackItem]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for track in tracks:
            uri = track.uri.strip()
            if not uri or uri in seen:
                continue
            seen.add(uri)
            unique.append(uri)
        return unique

    def _ensure_playback_target(self, *, device_id: str | None) -> None:
        if device_id and device_id.strip():
            return
        response = self._authenticated_request(
            "GET",
            f"{self._base_url}/v1/me/player/devices",
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify devices payload returned invalid JSON",
            ) from exc
        devices = payload.get("devices")
        if not isinstance(devices, list):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Spotify devices payload is missing devices",
            )
        has_active_device = any(
            isinstance(device, dict)
            and device.get("is_active") is True
            and device.get("is_restricted") is not True
            for device in devices
        )
        if has_active_device:
            return
        raise APIError(
            status_code=409,
            error_type="prerequisite_error",
            code="no_active_playback_device",
            message="Spotify playback requires an active playback device",
        )

    def _authenticated_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        kwargs["headers"] = dict(kwargs.pop("headers", {}))
        return self._perform_request(method=method, url=url, with_auth=True, **kwargs)

    def _raw_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        return self._perform_request(method=method, url=url, with_auth=False, **kwargs)

    def _perform_request(
        self,
        *,
        method: str,
        url: str,
        with_auth: bool,
        **kwargs,
    ) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers = dict(headers)
        attempt = 0
        response = None
        while attempt <= self._max_retries:
            attempt += 1
            try:
                if with_auth:
                    headers["Authorization"] = f"Bearer {self._resolve_token()}"
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        **kwargs,
                    )
                if response.status_code in (200, 201, 202, 204):
                    return response
                if with_auth and response.status_code in (401, 403):
                    if not (self._client_id and self._client_secret):
                        self._raise_for_status(response, url=url)
                    self._cached_token = ""
                    self._token_expires_at = 0.0
                    if attempt <= self._max_retries:
                        continue
                self._raise_for_status(response, url=url)
            except httpx.TimeoutException as exc:
                if attempt <= self._max_retries:
                    continue
                raise APIError(
                    status_code=504,
                    error_type="dependency_unavailable",
                    code="dependency_timeout",
                    message="Spotify provider timed out",
                ) from exc
            except httpx.RequestError as exc:
                if attempt <= self._max_retries:
                    continue
                raise APIError(
                    status_code=503,
                    error_type="dependency_unavailable",
                    code="provider_unavailable",
                    message="Spotify provider unavailable",
                ) from exc

        if response is None:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="provider_unavailable",
                message="Spotify provider unavailable",
            )
        return response

    def _raise_for_status(self, response: httpx.Response, *, url: str) -> None:
        status_code = response.status_code
        if status_code == 403 and "/v1/me/player" in url:
            raise APIError(
                status_code=409,
                error_type="prerequisite_error",
                code="premium_required",
                message="Spotify playback requires a Spotify Premium account",
            )
        if status_code >= 500:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="dependency_bad_response",
                message="Spotify provider returned an invalid response",
            )
        raise APIError(
            status_code=502,
            error_type="upstream_error",
            code=self._map_status_to_code(status_code),
            message="Spotify provider returned an invalid response",
        )

    @staticmethod
    def _map_status_to_code(status_code: int) -> str:
        if status_code in (400, 401, 403, 404):
            return "dependency_protocol_error"
        if status_code >= 500:
            return "dependency_bad_response"
        return "dependency_protocol_error"
