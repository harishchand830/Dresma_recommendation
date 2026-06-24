"""Pub/Sub publisher for interaction events (RFC Section 8.2)."""

import asyncio
import logging
from functools import lru_cache

from google.cloud.pubsub_v1 import PublisherClient

from dresma_rec.config.settings import Settings, get_settings
from dresma_rec.schemas.interaction import InteractionRequest

logger = logging.getLogger(__name__)


class EventPublisher:
    """Publishes interaction events to the configured Pub/Sub topic."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._publisher = PublisherClient()
        self._topic_path = self._publisher.topic_path(
            settings.project_id,
            settings.pubsub_interaction_topic,
        )

    async def publish_interaction(self, event: InteractionRequest) -> None:
        """Serialize and publish an interaction event (fire-and-forget).

        Publishing failures are logged but never propagated to the caller.
        """
        try:
            payload = event.model_dump_json().encode("utf-8")
            await asyncio.to_thread(self._publish_bytes, payload)
        except Exception:
            logger.exception(
                "Failed to publish interaction event: event_id=%s job_id=%s event_type=%s",
                event.event_id,
                event.job_id,
                event.event_type.value,
            )

    def _publish_bytes(self, payload: bytes) -> None:
        future = self._publisher.publish(self._topic_path, payload)
        future.result()


@lru_cache
def get_event_publisher() -> EventPublisher:
    """Return a cached :class:`EventPublisher` built from application settings."""
    return EventPublisher(get_settings())
