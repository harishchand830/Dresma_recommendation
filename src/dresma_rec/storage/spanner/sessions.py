"""Spanner repository for recommendation session lookups and writes."""

import asyncio
import json
from functools import lru_cache

from google.cloud import spanner
from google.cloud.spanner_v1 import param_types
from google.cloud.spanner_v1.database import Database

from dresma_rec.storage.spanner.client import get_spanner_client


class SessionRepository:
    """Reads session metadata from `recommendation_sessions` for event enrichment."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_session_metadata(self, job_id: str) -> dict:
        """Return `model_version` and `assigned_cluster_id` for a job, or `{}` if missing."""
        return await asyncio.to_thread(self._get_session_metadata_sync, job_id)

    def _get_session_metadata_sync(self, job_id: str) -> dict:
        with self._database.snapshot() as snapshot:
            results = snapshot.execute_sql(
                """
                SELECT model_version, assigned_cluster_id
                FROM recommendation_sessions
                WHERE job_id = @job_id
                """,
                params={"job_id": job_id},
                param_types={"job_id": param_types.STRING},
            )
            for model_version, assigned_cluster_id in results:
                metadata: dict = {}
                if model_version is not None:
                    metadata["model_version"] = model_version
                if assigned_cluster_id is not None:
                    metadata["assigned_cluster_id"] = assigned_cluster_id
                return metadata

        return {}


    async def create_session(
        self,
        job_id: str,
        assigned_cluster_id: int,
        model_version: str,
        retrieval_config: dict,
    ) -> None:
        """Insert a row into `recommendation_sessions` for a served recommendation list."""
        await asyncio.to_thread(
            self._create_session_sync,
            job_id,
            assigned_cluster_id,
            model_version,
            retrieval_config,
        )

    def _create_session_sync(
        self,
        job_id: str,
        assigned_cluster_id: int,
        model_version: str,
        retrieval_config: dict,
    ) -> None:
        def insert_transaction(transaction: spanner.Transaction) -> None:
            transaction.insert(
                "recommendation_sessions",
                columns=[
                    "job_id",
                    "assigned_cluster_id",
                    "model_version",
                    "retrieval_config",
                    "served_at",
                ],
                values=[
                    (
                        job_id,
                        assigned_cluster_id,
                        model_version,
                        json.dumps(retrieval_config),
                        spanner.COMMIT_TIMESTAMP,
                    )
                ],
            )

        self._database.run_in_transaction(insert_transaction)


@lru_cache
def get_session_repository() -> SessionRepository:
    """Return a cached :class:`SessionRepository` built from application settings."""
    return SessionRepository(get_spanner_client().database)
