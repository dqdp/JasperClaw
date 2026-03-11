from fastapi import Request

from app.core.config import Settings
from app.core.errors import APIError


def enforce_internal_openai_auth(request: Request, settings: Settings) -> None:
    if not request.url.path.startswith("/v1/"):
        return

    if not settings.internal_openai_api_key:
        raise APIError(
            status_code=503,
            error_type="internal_error",
            code="auth_not_configured",
            message="Internal API authentication is not configured",
        )

    authorization = request.headers.get("Authorization")
    if not authorization:
        raise APIError(
            status_code=401,
            error_type="authentication_error",
            code="missing_api_key",
            message="Missing bearer token",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise APIError(
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
            message="Invalid bearer token",
        )

    if token != settings.internal_openai_api_key:
        raise APIError(
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
            message="Invalid bearer token",
        )
