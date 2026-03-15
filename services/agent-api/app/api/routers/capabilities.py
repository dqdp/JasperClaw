from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.modules.chat.capabilities import resolve_capability_discovery

router = APIRouter()


@router.get("/v1/capabilities/discovery")
def capability_discovery(
    settings: Annotated[Settings, Depends(get_app_settings)],
):
    snapshot = resolve_capability_discovery(settings)
    return JSONResponse(content=snapshot.as_dict())
