from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        error_type: str,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.code = code
        self.message = message


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id

    incoming = request.headers.get("X-Request-ID")
    if incoming:
        return incoming

    generated = f"req_{uuid4().hex[:12]}"
    request.state.request_id = generated
    return generated


def build_error_response(
    request: Request,
    *,
    status_code: int,
    error_type: str,
    code: str,
    message: str,
) -> JSONResponse:
    request_id = get_request_id(request)
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "type": error_type,
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return build_error_response(
        request,
        status_code=exc.status_code,
        error_type=exc.error_type,
        code=exc.code,
        message=exc.message,
    )


async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    _ = exc
    return build_error_response(
        request,
        status_code=422,
        error_type="validation_error",
        code="invalid_request",
        message="Invalid request",
    )
