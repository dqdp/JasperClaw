from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse

from app.api.deps import get_readiness_service
from app.core.metrics import get_agent_metrics
from app.services.readiness import ReadinessService

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(
        get_agent_metrics().render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/readyz")
def readyz(
    readiness_service: Annotated[ReadinessService, Depends(get_readiness_service)],
):
    result = readiness_service.check()
    if result.is_ready:
        return {"status": "ready"}

    return JSONResponse(
        status_code=503,
        content={
            "status": "not_ready",
            "checks": result.checks,
        },
    )
