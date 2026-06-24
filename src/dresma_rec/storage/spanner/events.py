"""Spanner repository for `recommendation_events` serve-time logging."""

import asyncio
import json
from functools import lru_cache

from google.cloud import spanner
from google.cloud.spanner_v1.database import Database

from dresma_rec.schemas.recommendations import RecommendationResult
from dresma_rec.storage.spanner.client import get_spanner_client


class RecommendationEventsRepository:
    """Writes one `recommendation_events` row per served candidate."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def write_events(
        self, job_id: str, results: list[RecommendationResult]
    ) -> None:
        """Batch-insert serve events for each ranked result."""
        if not results:
            return

        await asyncio.to_thread(self._write_events_sync, job_id, results)

    def _write_events_sync(
        self, job_id: str, results: list[RecommendationResult]
    ) -> None:
        rows = [
            (
                job_id,
                result.image_id,
                result.position,
                result.model_score,
                result.source_channels,
                json.dumps(result.metadata, default=str),
                spanner.COMMIT_TIMESTAMP,
            )
            for result in results
        ]

        def insert_transaction(transaction: spanner.Transaction) -> None:
            transaction.insert(
                "recommendation_events",
                columns=[
                    "job_id",
                    "image_id",
                    "position",
                    "model_score",
                    "source_channels",
                    "feature_snapshot",
                    "served_at",
                ],
                values=rows,
            )

        self._database.run_in_transaction(insert_transaction)


@lru_cache
def get_events_repository() -> RecommendationEventsRepository:
    """Return a cached :class:`RecommendationEventsRepository`."""
    return RecommendationEventsRepository(get_spanner_client().database)
