"""Channel C2 — full-image embedding similarity (RFC Section 5.2)."""

import asyncio
import logging

from google.cloud.spanner_v1 import param_types
from google.cloud.spanner_v1.database import Database

from dresma_rec.retrieval.brand_embedding_lookup import fetch_brand_embedding
from dresma_rec.retrieval.channels.base import BaseRetrievalChannel
from dresma_rec.schemas.recommendations import RecommendationRequest

logger = logging.getLogger(__name__)

_C2_QUERY = """
SELECT
  image_id,
  image_url,
  cluster_id,
  COSINE_DISTANCE(full_image_embedding, @embedding) AS distance
FROM reference_images
ORDER BY distance ASC
LIMIT @limit
"""


class FullImageSimilarityChannel(BaseRetrievalChannel):
    """Spanner vector kNN on `reference_images.full_image_embedding`."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def retrieve(
        self,
        request: RecommendationRequest,
        limit: int,
        **kwargs,
    ) -> list[dict]:
        full_embedding = getattr(request.upload, "full_image_embedding", None)
        if not full_embedding:
            return []

        try:
            selected_embedding = full_embedding
            source_type = "upload_full"

            brand_name = (request.brand_name or "").strip()
            if brand_name:
                brand_embedding = await asyncio.to_thread(
                    fetch_brand_embedding,
                    self._database,
                    brand_name,
                )
                if brand_embedding:
                    selected_embedding = brand_embedding
                    source_type = "brand_embedding"

            return await asyncio.to_thread(
                self._retrieve_sync,
                selected_embedding,
                limit,
                source_type,
            )
        except Exception:
            logger.exception(
                "C2 full-image similarity retrieval failed for job_id=%s",
                request.job_id,
            )
            return []

    def _retrieve_sync(self, embedding: list[float], limit: int, source_type: str) -> list[dict]:
        with self._database.snapshot() as snapshot:
            results = snapshot.execute_sql(
                _C2_QUERY,
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
                    "full_cosine_distance": distance,
                    "full_similarity_source": source_type,
                    "source_channels": ["full_image"],
                }
                for image_id, image_url, cluster_id, distance in results
            ]
