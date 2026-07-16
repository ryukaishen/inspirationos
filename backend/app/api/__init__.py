from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.jobs import router as jobs_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(imports_router)
api_router.include_router(jobs_router)
