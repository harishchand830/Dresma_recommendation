"""Spanner repository for real-time `user_actions` event writes."""

import asyncio
import hashlib
import json
from functools import lru_cache

from google.cloud import spanner
from google.cloud.spanner_v1.database import Database

from dresma_rec.schemas.interaction import InteractionRequest
from dresma_rec.storage.spanner.client import get_spanner_client

_SHARD_COUNT = 64


class UserActionsRepository:
    """Writes interaction events to the sharded `user_actions` table."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def write_action(self, event: InteractionRequest) -> None:
        """Insert an interaction event row keyed by `(shard_id, event_time, event_id)`."""
        await asyncio.to_thread(self._write_action_sync, event)

    def _write_action_sync(self, event: InteractionRequest) -> None:
        shard_id = int(hashlib.md5(event.job_id.encode()).hexdigest(), 16) % _SHARD_COUNT
        metadata_value = (
            json.dumps(event.metadata) if event.metadata is not None else None
        )

        def insert_transaction(transaction: spanner.Transaction) -> None:
            transaction.insert(
                "user_actions",
                columns=[
                    "shard_id",
                    "event_id",
                    "job_id",
                    "image_id",
                    "event_type",
                    "position",
                    "event_time",
                    "metadata",
                ],
                values=[
                    (
                        shard_id,
                        event.event_id,
                        event.job_id,
                        event.image_id,
                        event.event_type.value,
                        event.position,
                        spanner.COMMIT_TIMESTAMP,
                        metadata_value,
                    )
                ],
            )

        self._database.run_in_transaction(insert_transaction)


@lru_cache
def get_user_actions_repository() -> UserActionsRepository:
    """Return a cached :class:`UserActionsRepository` built from application settings."""
    return UserActionsRepository(get_spanner_client().database)
