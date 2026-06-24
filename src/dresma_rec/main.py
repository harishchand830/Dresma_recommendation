import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from google.cloud import storage

from dresma_rec.api.router import api_router
from dresma_rec.config.settings import Settings, get_settings
from dresma_rec.observability.logging import setup_logging
from dresma_rec.observability.metrics import request_latency_middleware
from dresma_rec.ranking.model_manager import ModelManager
from dresma_rec.storage.spanner.client import get_spanner_client

setup_logging()

logger = logging.getLogger(__name__)

APP_DESCRIPTION = (
    "Standalone recommendation and reference-image ranking service for Dresma. "
    "Orchestrates multi-channel retrieval from Cloud Spanner and ranks candidates "
    "for downstream AI generation workflows."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.startup_time = time.time()

    logger.info(
        "Starting Dresma Recommendation Service",
        extra={
            "environment": settings.environment,
            "project_id": settings.project_id,
        },
    )

    gcs_client = storage.Client()
    model_manager = ModelManager(get_spanner_client().database, gcs_client)
    await model_manager.initialize()
    watcher_task = asyncio.create_task(model_manager.poll_for_updates())
    app.state.model_manager = model_manager

    yield

    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass

    logger.info("Shutting down Dresma Recommendation Service")


def create_app() -> FastAPI:
    application = FastAPI(
        title="Dresma Recommendation Service",
        description=APP_DESCRIPTION,
        lifespan=lifespan,
    )
    application.middleware("http")(request_latency_middleware)
    application.include_router(api_router)

    @application.get("/")
    async def root(request: Request) -> dict[str, Any]:
        settings: Settings = request.app.state.settings
        return {
            "message": "Welcome to the Dresma Recommendation Service",
            "environment": settings.environment,
        }

    return application


app = create_app()
