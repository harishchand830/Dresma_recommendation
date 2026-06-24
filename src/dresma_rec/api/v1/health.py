import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    model_version: str
    model_loaded: bool
    uptime_s: int


@router.get("/", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    model_manager = request.app.state.model_manager
    uptime_s = int(time.time() - request.app.state.startup_time)
    return HealthResponse(
        status="ok",
        model_version=model_manager.active_version,
        model_loaded=model_manager.active_booster is not None,
        uptime_s=uptime_s,
    )
