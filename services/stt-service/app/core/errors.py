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


def build_error_response(
    *,
    status_code: int,
    error_type: str,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "type": error_type,
                "code": code,
                "message": message,
            }
        },
    )


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    _ = request
    return build_error_response(
        status_code=exc.status_code,
        error_type=exc.error_type,
        code=exc.code,
        message=exc.message,
    )


async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    _ = (request, exc)
    return build_error_response(
        status_code=422,
        error_type="validation_error",
        code="invalid_request",
        message="Invalid request",
    )
