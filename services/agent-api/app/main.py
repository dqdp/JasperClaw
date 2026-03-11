from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from app.api.routes import router
from app.core.errors import APIError, api_error_handler, request_validation_error_handler

app = FastAPI(title="agent-api", version="0.1.0")
app.include_router(router)
app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(RequestValidationError, request_validation_error_handler)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex[:12]}"
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response
