from fastapi import APIRouter

from app.api.routers.audio import router as audio_router
from app.api.routers.capabilities import router as capabilities_router
from app.api.routers.chat import router as chat_router
from app.api.routers.health import router as health_router
from app.api.routers.models import router as models_router

router = APIRouter()
router.include_router(health_router)
router.include_router(models_router)
router.include_router(capabilities_router)
router.include_router(chat_router)
router.include_router(audio_router)
