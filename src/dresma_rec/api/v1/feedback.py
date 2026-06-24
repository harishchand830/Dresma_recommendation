import logging

from fastapi import APIRouter, BackgroundTasks, Depends, status

from dresma_rec.api.v1.interaction import InteractionQueuedResponse, enrich_and_publish
from dresma_rec.events.publisher import EventPublisher, get_event_publisher
from dresma_rec.schemas.feedback import FeedbackRequest
from dresma_rec.schemas.interaction import InteractionEventType, InteractionRequest
from dresma_rec.storage.spanner.sessions import SessionRepository, get_session_repository
from dresma_rec.storage.spanner.user_actions import (
    UserActionsRepository,
    get_user_actions_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def to_interaction_request(feedback: FeedbackRequest) -> InteractionRequest:
    """Map explicit feedback into the shared interaction ingestion shape."""
    return InteractionRequest(
        event_id=feedback.event_id,
        job_id=feedback.job_id,
        image_id=feedback.image_id,
        event_type=InteractionEventType.FEEDBACK,
        position=feedback.position or 1,
        event_time=feedback.event_time,
        metadata=feedback.metadata.model_dump(),
    )


@router.post(
    "/",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InteractionQueuedResponse,
)
async def create_feedback(
    request: FeedbackRequest,
    background_tasks: BackgroundTasks,
    repository: SessionRepository = Depends(get_session_repository),
    publisher: EventPublisher = Depends(get_event_publisher),
    user_actions_repo: UserActionsRepository = Depends(get_user_actions_repository),
) -> InteractionQueuedResponse:
    logger.info("Received feedback event: job_id=%s", request.job_id)
    interaction_event = to_interaction_request(request)
    background_tasks.add_task(
        enrich_and_publish,
        interaction_event,
        repository,
        publisher,
        user_actions_repo,
    )
    return InteractionQueuedResponse(status="queued")
