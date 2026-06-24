from fastapi import APIRouter, Depends

from dresma_rec.api.v1 import feedback, health, interaction, recommendations
from dresma_rec.auth.service_identity import verify_service_account

api_router = APIRouter()
api_router.include_router(health.router, prefix="/v1/health", tags=["Health"])
api_router.include_router(
    interaction.router,
    prefix="/v1/interaction",
    tags=["Interaction"],
    dependencies=[Depends(verify_service_account)],
)
api_router.include_router(
    recommendations.router,
    prefix="/v1/recommendations",
    tags=["Recommendations"],
    dependencies=[Depends(verify_service_account)],
)
api_router.include_router(
    feedback.router,
    prefix="/v1/feedback",
    tags=["Feedback"],
    dependencies=[Depends(verify_service_account)],
)
