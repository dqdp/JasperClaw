from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_readiness_service
from app.services.readiness import ReadinessService

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


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
