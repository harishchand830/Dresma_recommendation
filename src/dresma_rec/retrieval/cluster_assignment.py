"""Cluster assignment for uploaded images (RFC Section 5.3)."""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from google.cloud.spanner_v1 import param_types
from google.cloud.spanner_v1.database import Database

from dresma_rec.storage.spanner.client import get_spanner_database

logger = logging.getLogger(__name__)

_FOREGROUND_QUERY = """
SELECT
  cluster_id,
  COSINE_DISTANCE(centroid_fg, @embedding) AS distance
FROM clusters
ORDER BY distance ASC
LIMIT 1
"""

_FULL_IMAGE_QUERY = """
SELECT
  cluster_id,
  COSINE_DISTANCE(centroid_full, @embedding) AS distance
FROM clusters
ORDER BY distance ASC
LIMIT 1
"""


class ClusterAssigner:
    """Assign uploads to a cluster via nearest centroid in Spanner."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def assign_cluster(
        self,
        embedding: list[float],
        embedding_type: str = "foreground",
    ) -> int:
        if not embedding:
            logger.warning("Cluster assignment skipped: empty embedding")
            return 0

        try:
            return await asyncio.to_thread(
                self._assign_cluster_sync,
                embedding,
                embedding_type,
            )
        except Exception:
            logger.warning(
                "Cluster assignment failed for embedding_type=%s; "
                "falling back to cluster 0",
                embedding_type,
                exc_info=True,
            )
            return 0

    def _assign_cluster_sync(self, embedding: list[float], embedding_type: str) -> int:
        query = (
            _FULL_IMAGE_QUERY
            if embedding_type == "full_image"
            else _FOREGROUND_QUERY
        )

        with self._database.snapshot() as snapshot:
            results = list(
                snapshot.execute_sql(
                    query,
                    params={"embedding": embedding},
                    param_types={
                        "embedding": param_types.Array(param_types.FLOAT32),
                    },
                )
            )

        if not results:
            logger.warning(
                "Cluster assignment returned no rows (clusters table may be empty); "
                "falling back to cluster 0"
            )
            return 0

        cluster_id, _distance = results[0]
        return int(cluster_id)


@lru_cache
def get_cluster_assigner() -> ClusterAssigner:
    """FastAPI dependency factory for :class:`ClusterAssigner`."""
    return ClusterAssigner(get_spanner_database())
