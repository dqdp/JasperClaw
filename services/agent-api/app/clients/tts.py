import httpx

from app.core.errors import APIError


class TtsClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def synthesize(self, *, text: str, voice: str) -> bytes:
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(
                    f"{self._base_url}/speak",
                    json={"input": text, "voice": voice},
                )
        except httpx.TimeoutException as exc:
            raise APIError(
                status_code=504,
                error_type="dependency_unavailable",
                code="dependency_timeout",
                message="Speech service timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="speech_service_unavailable",
                message="Speech service unavailable",
            ) from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError as exc:
                raise APIError(
                    status_code=502,
                    error_type="upstream_error",
                    code="dependency_bad_response",
                    message="Speech service returned invalid JSON",
                ) from exc

            error = payload.get("error") if isinstance(payload, dict) else None
            if (
                isinstance(error, dict)
                and isinstance(error.get("type"), str)
                and isinstance(error.get("code"), str)
                and isinstance(error.get("message"), str)
            ):
                raise APIError(
                    status_code=response.status_code,
                    error_type=error["type"],
                    code=error["code"],
                    message=error["message"],
                )

            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Speech service returned an unexpected payload",
            )

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("audio/wav") or not response.content:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Speech service returned an unexpected payload",
            )

        return response.content

    def check_ready(self) -> None:
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.get(f"{self._base_url}/readyz")
        except httpx.TimeoutException as exc:
            raise APIError(
                status_code=504,
                error_type="dependency_unavailable",
                code="dependency_timeout",
                message="Speech service timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="speech_service_unavailable",
                message="Speech service unavailable",
            ) from exc

        if response.status_code != 200:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="speech_service_unavailable",
                message="Speech service unavailable",
            )
