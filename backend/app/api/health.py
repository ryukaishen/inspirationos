from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db import get_engine
from app.redis_client import get_redis_client
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


def check_db() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def check_redis() -> bool:
    try:
        return bool(get_redis_client().ping())
    except Exception:
        return False


@router.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    db_ok = check_db()
    redis_ok = check_redis()
    if not (db_ok and redis_ok):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if db_ok and redis_ok else "degraded",
        db="healthy" if db_ok else "unreachable",
        redis="healthy" if redis_ok else "unreachable",
    )
