from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from app.api.routes import router
from app.core.errors import APIError, api_error_handler, request_validation_error_handler
from app.core.logging import configure_logging, log_event

configure_logging()
app = FastAPI(title="agent-api", version="0.1.0")
app.include_router(router)
app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(RequestValidationError, request_validation_error_handler)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex[:12]}"
    started = perf_counter()
    log_event(
        "request_started",
        request_id=request.state.request_id,
        method=request.method,
        path=request.url.path,
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    duration_ms = round((perf_counter() - started) * 1000, 2)
    event = "request_completed" if response.status_code < 400 else "request_failed"
    log_event(
        event,
        request_id=request.state.request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response
