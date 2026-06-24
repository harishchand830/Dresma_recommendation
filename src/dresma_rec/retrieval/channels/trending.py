"""Channel C3 — trending retrieval (RFC Section 5.2)."""

import asyncio
import datetime
import logging

from cachetools import TTLCache
from google.cloud.spanner_v1 import param_types
from google.cloud.spanner_v1.database import Database

from dresma_rec.retrieval.channels.base import BaseRetrievalChannel
from dresma_rec.schemas.recommendations import RecommendationRequest

logger = logging.getLogger(__name__)

_channel_cache = TTLCache(maxsize=500, ttl=300)

_C3_QUERY = """
SELECT
  r.image_id,
  r.image_url,
  r.cluster_id,
  s.trend_score
FROM image_signals AS s
JOIN reference_images AS r ON s.image_id = r.image_id
WHERE r.cluster_id = @cluster_id
  AND s.as_of_date = (
    SELECT MAX(as_of_date) FROM image_signals WHERE cluster_id = @cluster_id
  )
ORDER BY s.trend_score DESC
LIMIT @limit
"""


class TrendingChannel(BaseRetrievalChannel):
    """Top images by trend_score within an assigned cluster."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def retrieve(
        self,
        request: RecommendationRequest,
        limit: int,
        **kwargs,
    ) -> list[dict]:
        cluster_id = kwargs.get("cluster_id", 0)
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        cache_key = f"{cluster_id}_{today}_{limit}"

        if cache_key in _channel_cache:
            logger.debug("Cache hit for trending cluster %s", cluster_id)
            return _channel_cache[cache_key]

        try:
            results = await asyncio.to_thread(
                self._retrieve_sync,
                cluster_id,
                limit,
            )
            _channel_cache[cache_key] = results
            return results
        except Exception:
            logger.exception(
                "C3 trending retrieval failed for job_id=%s cluster_id=%s",
                request.job_id,
                cluster_id,
            )
            return []

    def _retrieve_sync(self, cluster_id: int, limit: int) -> list[dict]:
        with self._database.snapshot() as snapshot:
            results = snapshot.execute_sql(
                _C3_QUERY,
                params={"cluster_id": cluster_id, "limit": limit},
                param_types={
                    "cluster_id": param_types.INT64,
                    "limit": param_types.INT64,
                },
            )
            return [
                {
                    "image_id": image_id,
                    "image_url": image_url,
                    "cluster_id": row_cluster_id,
                    "trend_score": trend_score,
                    "source_channels": ["trending"],
                }
                for image_id, image_url, row_cluster_id, trend_score in results
            ]
