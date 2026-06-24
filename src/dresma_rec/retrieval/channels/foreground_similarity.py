"""Channel C1 — foreground embedding similarity (RFC Section 5.2)."""

import asyncio
import logging

from google.cloud.spanner_v1 import param_types
from google.cloud.spanner_v1.database import Database

from dresma_rec.retrieval.channels.base import BaseRetrievalChannel
from dresma_rec.schemas.recommendations import RecommendationRequest

logger = logging.getLogger(__name__)

_C1_QUERY = """
SELECT
  image_id,
  image_url,
  cluster_id,
  COSINE_DISTANCE(foreground_embedding, @embedding) AS distance
FROM reference_images
ORDER BY distance ASC
LIMIT @limit
"""


class ForegroundSimilarityChannel(BaseRetrievalChannel):
    """Spanner vector kNN on `reference_images.foreground_embedding`."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def retrieve(
        self,
        request: RecommendationRequest,
        limit: int,
        **kwargs,
    ) -> list[dict]:
        try:
            embedding = request.upload.foreground_embedding
            return await asyncio.to_thread(self._retrieve_sync, embedding, limit)
        except Exception:
            logger.exception(
                "C1 foreground similarity retrieval failed for job_id=%s",
                request.job_id,
            )
            return []

    def _retrieve_sync(self, embedding: list[float], limit: int) -> list[dict]:
        with self._database.snapshot() as snapshot:
            results = snapshot.execute_sql(
                _C1_QUERY,
                params={"embedding": embedding, "limit": limit},
                param_types={
                    "embedding": param_types.Array(param_types.FLOAT32),
                    "limit": param_types.INT64,
                },
            )
            return [
                {
                    "image_id": image_id,
                    "image_url": image_url,
                    "cluster_id": cluster_id,
                    "fg_cosine_distance": distance,
                    "source_channels": ["foreground"],
                }
                for image_id, image_url, cluster_id, distance in results
            ]
