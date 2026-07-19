from fastapi import APIRouter

from app.api.clusters import router as clusters_router
from app.api.conversations import router as conversations_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.items import router as items_router
from app.api.jobs import router as jobs_router
from app.api.settings import router as settings_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(imports_router)
api_router.include_router(conversations_router)
api_router.include_router(jobs_router)
api_router.include_router(items_router)
api_router.include_router(clusters_router)
api_router.include_router(settings_router)
