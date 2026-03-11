from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.schemas.models import ModelCard, ModelListResponse

router = APIRouter()


@router.get("/v1/models")
def list_models(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelListResponse:
    profiles = [
        ModelCard(id=profile_id, owned_by=settings.model_owner)
        for profile_id in settings.public_profiles
    ]
    return ModelListResponse(data=profiles)
