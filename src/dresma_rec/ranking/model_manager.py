"""Background model loader and hot-reload watcher for XGBoost rankers."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import TYPE_CHECKING

import xgboost as xgb
from google.cloud.spanner_v1 import param_types

from dresma_rec.ranking.constants import EXPECTED_FEATURES

if TYPE_CHECKING:
    from google.cloud import storage
    from google.cloud.spanner_v1.database import Database

logger = logging.getLogger(__name__)

_GRADUATION_SESSION_THRESHOLD = 100

_GRADUATED_CLUSTERS_SQL = """
SELECT vol.cluster_id
FROM (
  SELECT assigned_cluster_id AS cluster_id
  FROM recommendation_sessions
  WHERE assigned_cluster_id IS NOT NULL
  GROUP BY assigned_cluster_id
  HAVING COUNT(*) >= @min_sessions
) vol
INNER JOIN (
  SELECT DISTINCT cluster_id
  FROM cluster_trends
  WHERE cluster_trend IS NOT NULL
) ct ON ct.cluster_id = vol.cluster_id
"""


def _parse_gcs_uri(artifact_uri: str) -> tuple[str, str]:
    if not artifact_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {artifact_uri}")

    path = artifact_uri[5:]
    bucket_name, _, blob_name = path.partition("/")
    if not bucket_name or not blob_name:
        raise ValueError(f"Invalid GCS URI: {artifact_uri}")

    return bucket_name, blob_name


class ModelManager:
    """Loads the active PRODUCTION or CANARY model at startup and polls for hot reloads."""

    def __init__(self, database: Database, gcs_client: storage.Client) -> None:
        self._database = database
        self._gcs_client = gcs_client
        self.active_booster: xgb.Booster | None = None
        self.active_version: str = "none"
        self.active_status: str = "none"
        self.graduated_clusters: set[int] = set()

    async def _fetch_graduated_clusters(self) -> set[int]:
        def _fetch_sync() -> set[int]:
            with self._database.snapshot() as snapshot:
                results = snapshot.execute_sql(
                    _GRADUATED_CLUSTERS_SQL,
                    params={"min_sessions": _GRADUATION_SESSION_THRESHOLD},
                    param_types={"min_sessions": param_types.INT64},
                )
                return {int(cluster_id) for cluster_id, in results}

        try:
            return await asyncio.to_thread(_fetch_sync)
        except Exception:
            logger.warning(
                "Failed to fetch graduated clusters; defaulting to heuristic-only routing",
                exc_info=True,
            )
            return set()

    async def _fetch_production_metadata(self) -> dict[str, str] | None:
        def _fetch_sync() -> dict[str, str] | None:
            with self._database.snapshot() as snapshot:
                results = snapshot.execute_sql(
                    """
                    SELECT model_version, artifact_uri, status
                    FROM model_metadata
                    WHERE status IN ('PRODUCTION', 'CANARY')
                    ORDER BY trained_at DESC
                    LIMIT 1
                    """
                )
                for model_version, artifact_uri, status in results:
                    return {
                        "model_version": model_version,
                        "artifact_uri": artifact_uri,
                        "status": status,
                    }
            return None

        return await asyncio.to_thread(_fetch_sync)

    async def _download_and_load(self, artifact_uri: str) -> xgb.Booster:
        bucket_name, blob_name = _parse_gcs_uri(artifact_uri)

        def _download_and_load_sync() -> xgb.Booster:
            bucket = self._gcs_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_file:
                tmp_path = tmp_file.name

            try:
                blob.download_to_filename(tmp_path)
                booster = xgb.Booster()
                booster.load_model(tmp_path)
                model_features = booster.feature_names
                if model_features != EXPECTED_FEATURES:
                    raise ValueError(
                        f"Feature mismatch! Expected {EXPECTED_FEATURES}, "
                        f"got {model_features}"
                    )
                return booster
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        return await asyncio.to_thread(_download_and_load_sync)

    async def initialize(self) -> None:
        self.graduated_clusters = await self._fetch_graduated_clusters()
        logger.info(
            "Loaded graduated clusters",
            extra={"graduated_cluster_count": len(self.graduated_clusters)},
        )

        try:
            metadata = await self._fetch_production_metadata()
        except Exception:
            logger.exception(
                "Failed to fetch active model metadata; serving without ML ranker"
            )
            return

        if metadata is None:
            logger.warning(
                "No PRODUCTION or CANARY model found in model_metadata; "
                "serving without ML ranker"
            )
            return

        try:
            booster = await self._download_and_load(metadata["artifact_uri"])
        except Exception:
            logger.exception(
                "Failed to load active model on startup; serving without ML ranker"
            )
            return

        self.active_booster = booster
        self.active_version = metadata["model_version"]
        self.active_status = metadata["status"]
        logger.info(
            "Loaded active model",
            extra={
                "model_version": self.active_version,
                "status": self.active_status,
            },
        )

    async def poll_for_updates(self, poll_interval_sec: int = 60) -> None:
        while True:
            await asyncio.sleep(poll_interval_sec)

            self.graduated_clusters = await self._fetch_graduated_clusters()

            try:
                metadata = await self._fetch_production_metadata()
                if metadata is None:
                    continue

                new_version = metadata["model_version"]
                new_status = metadata["status"]
                if (
                    new_version == self.active_version
                    and new_status == self.active_status
                ):
                    continue

                if new_version != self.active_version:
                    new_booster = await self._download_and_load(metadata["artifact_uri"])
                    self.active_booster = new_booster
                    self.active_version = new_version

                self.active_status = new_status
                logger.info(
                    "Hot-reloaded model to version %s (status=%s)",
                    new_version,
                    new_status,
                )
            except Exception:
                logger.exception("Model hot-reload failed; keeping current model")
