import logging

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel

from dresma_rec.events.publisher import EventPublisher, get_event_publisher
from dresma_rec.schemas.interaction import InteractionRequest
from dresma_rec.storage.spanner.sessions import SessionRepository, get_session_repository
from dresma_rec.storage.spanner.user_actions import (
    UserActionsRepository,
    get_user_actions_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class InteractionQueuedResponse(BaseModel):
    """Response body for POST /v1/interaction (RFC Section 14.2)."""

    status: str = "queued"


async def enrich_and_publish(
    request: InteractionRequest,
    repository: SessionRepository,
    publisher: EventPublisher,
    user_actions_repo: UserActionsRepository,
) -> None:
    try:
        session_metadata = await repository.get_session_metadata(request.job_id)
        if session_metadata:
            if request.metadata is None:
                request.metadata = {}
            request.metadata.update(session_metadata)
    except Exception:
        logger.exception(
            "Session lookup failed for job_id=%s; publishing without enrichment",
            request.job_id,
        )

    try:
        await user_actions_repo.write_action(request)
    except Exception:
        logger.exception(
            "Failed to write user action to Spanner: event_id=%s job_id=%s",
            request.event_id,
            request.job_id,
        )

    await publisher.publish_interaction(request)


@router.post(
    "/",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InteractionQueuedResponse,
)
async def create_interaction(
    request: InteractionRequest,
    background_tasks: BackgroundTasks,
    repository: SessionRepository = Depends(get_session_repository),
    publisher: EventPublisher = Depends(get_event_publisher),
    user_actions_repo: UserActionsRepository = Depends(get_user_actions_repository),
) -> InteractionQueuedResponse:
    logger.info(
        "Received interaction event: event_type=%s job_id=%s",
        request.event_type.value,
        request.job_id,
    )
    background_tasks.add_task(
        enrich_and_publish, request, repository, publisher, user_actions_repo
    )
    return InteractionQueuedResponse(status="queued")
