"""Channel C6 - brand embedding similarity against reference brand embeddings."""

from __future__ import annotations

import asyncio
import logging

from google.cloud.spanner_v1 import param_types
from google.cloud.spanner_v1.database import Database

from dresma_rec.retrieval.brand_embedding_lookup import fetch_brand_embedding
from dresma_rec.retrieval.channels.base import BaseRetrievalChannel
from dresma_rec.schemas.recommendations import RecommendationRequest

logger = logging.getLogger(__name__)

_C6_QUERY = """
SELECT
  id,
  image_url,
  cluster_id,
  COSINE_DISTANCE(bg_remove_url_embeddings, @embedding) AS distance
FROM brand_references
WHERE bg_remove_url_embeddings IS NOT NULL
  AND (image_type IS NULL OR image_type != 'video')
ORDER BY distance ASC
LIMIT @limit
"""


class BrandSimilarityChannel(BaseRetrievalChannel):
    """Brand-guided kNN retrieval over `reference_images.brand_embedding`."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def retrieve(
        self,
        request: RecommendationRequest,
        limit: int,
        **kwargs,
    ) -> list[dict]:
        brand_name = (request.brand_name or "").strip()
        if not brand_name:
            return []

        try:
            brand_embedding = await asyncio.to_thread(
                fetch_brand_embedding,
                self._database,
                brand_name,
            )
            if not brand_embedding:
                return []
            return await asyncio.to_thread(self._retrieve_sync, brand_embedding, limit)
        except Exception:
            logger.exception(
                "C6 brand similarity retrieval failed for job_id=%s brand_name=%s",
                request.job_id,
                brand_name,
            )
            return []

    def _retrieve_sync(self, embedding: list[float], limit: int) -> list[dict]:
        with self._database.snapshot() as snapshot:
            results = snapshot.execute_sql(
                _C6_QUERY,
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
                    "brand_cosine_distance": distance,
                    "source_channels": ["brand_similarity"],
                }
                for image_id, image_url, cluster_id, distance in results
            ]