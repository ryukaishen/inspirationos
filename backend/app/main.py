import logging

from fastapi import FastAPI

from app.api import api_router
from app.config import get_config


def create_app() -> FastAPI:
    config = get_config()
    logging.basicConfig(level=config.log_level)
    application = FastAPI(title="InspirationOS API", version="0.1.0")
    application.include_router(api_router, prefix="/api")
    return application


app = create_app()
