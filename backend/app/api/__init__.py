from fastapi import APIRouter, Depends

from app.api.auth import router as auth_router
from app.api.career import router as career_router
from app.api.clusters import router as clusters_router
from app.api.conversations import router as conversations_router
from app.api.deps import get_current_user, require_csrf_header
from app.api.export import router as export_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.items import router as items_router
from app.api.jobs import router as jobs_router
from app.api.privacy import router as privacy_router
from app.api.projects import router as projects_router
from app.api.settings import router as settings_router

# CSRF header check applies to every route including auth (the frontend
# always sends it — defense-in-depth alongside SameSite=Strict). Session
# auth applies to every route *except* health (uptime monitoring can't
# authenticate) and auth itself (you can't have a session yet to prove).
api_router = APIRouter(dependencies=[Depends(require_csrf_header)])
api_router.include_router(health_router)
api_router.include_router(auth_router)

protected_router = APIRouter(dependencies=[Depends(get_current_user)])
protected_router.include_router(imports_router)
protected_router.include_router(conversations_router)
protected_router.include_router(jobs_router)
protected_router.include_router(items_router)
protected_router.include_router(clusters_router)
protected_router.include_router(projects_router)
protected_router.include_router(career_router)
protected_router.include_router(settings_router)
protected_router.include_router(export_router)
protected_router.include_router(privacy_router)
api_router.include_router(protected_router)
