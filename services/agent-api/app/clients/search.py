from dataclasses import dataclass

import httpx

from app.core.errors import APIError


@dataclass(frozen=True, slots=True)
class WebSearchResultItem:
    title: str
    url: str
    snippet: str


class WebSearchClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_retries: int = 1,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(max_retries, 0)

    def search(self, *, query: str, limit: int) -> list[WebSearchResultItem]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        params = {"q": query, "limit": str(limit)}

        attempt = 0
        response = None
        while attempt <= self._max_retries:
            attempt += 1
            try:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.get(
                        f"{self._base_url}/search",
                        headers=headers,
                        params=params,
                    )
                    break
            except httpx.TimeoutException as exc:
                if attempt <= self._max_retries:
                    continue
                raise APIError(
                    status_code=504,
                    error_type="dependency_unavailable",
                    code="dependency_timeout",
                    message="Search provider timed out",
                ) from exc
            except httpx.RequestError as exc:
                if attempt <= self._max_retries:
                    continue
                raise APIError(
                    status_code=503,
                    error_type="dependency_unavailable",
                    code="provider_unavailable",
                    message="Search provider unavailable",
                ) from exc

        if response is None:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="provider_unavailable",
                message="Search provider unavailable",
            )

        if response.status_code >= 500:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Search provider returned an invalid response",
            )
        if response.status_code >= 400:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_protocol_error",
                message="Search provider rejected the request",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Search provider returned invalid JSON",
            ) from exc

        if not isinstance(data, dict):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Search provider returned an unexpected payload",
            )

        result_entries = data.get("results")
        if not isinstance(result_entries, list):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Search provider returned an unexpected payload",
            )

        results: list[WebSearchResultItem] = []
        for entry in result_entries:
            if not isinstance(entry, dict):
                raise APIError(
                    status_code=502,
                    error_type="upstream_error",
                    code="dependency_bad_response",
                    message="Search provider returned an unexpected payload",
                )
            title = entry.get("title")
            url = entry.get("url")
            snippet = entry.get("snippet")
            if not isinstance(title, str) or not isinstance(url, str) or not isinstance(
                snippet, str
            ):
                raise APIError(
                    status_code=502,
                    error_type="upstream_error",
                    code="dependency_bad_response",
                    message="Search provider returned an unexpected payload",
                )
            results.append(
                WebSearchResultItem(title=title, url=url, snippet=snippet)
            )

        return results
