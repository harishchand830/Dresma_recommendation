"""Parallel multi-channel retrieval orchestrator (RFC Section 5.2)."""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from google.cloud.spanner_v1.database import Database

from dresma_rec.retrieval.channels import (
    ForegroundSimilarityChannel,
    FreshnessChannel,
    FullImageSimilarityChannel,
    PopularChannel,
    TrendingChannel,
)
from dresma_rec.schemas.recommendations import RecommendationRequest
from dresma_rec.storage.spanner.client import get_spanner_database

logger = logging.getLogger(__name__)

RETRIEVAL_DEADLINE_SEC = 0.15

_DEFAULT_CHANNEL_LIMITS: dict[str, int] = {
    "foreground": 100,
    "full_image": 50,
    "trending": 50,
    "popular": 50,
    "freshness": 50,
}

_CHANNEL_NAMES = ("foreground", "full_image", "trending", "popular", "freshness")


class RetrievalOrchestrator:
    """Fan out to all retrieval channels, merge, and deduplicate candidates."""

    def __init__(self, database: Database, deadline_sec: float | None = None) -> None:
        self._database = database
        self._deadline_sec = deadline_sec if deadline_sec is not None else RETRIEVAL_DEADLINE_SEC
        self.c1 = ForegroundSimilarityChannel(database)
        self.c2 = FullImageSimilarityChannel(database)
        self.c3 = TrendingChannel(database)
        self.c4 = PopularChannel(database)
        self.c5 = FreshnessChannel(database)

    async def get_candidates(
        self,
        request: RecommendationRequest,
        cluster_id: int,
    ) -> list[dict]:
        limits = {
            channel: self._limit_for_channel(request, channel)
            for channel in _CHANNEL_NAMES
        }

        channel_runs = [
            (
                "foreground",
                self.c1,
                asyncio.wait_for(
                    self.c1.retrieve(request, limits["foreground"]),
                    timeout=self._deadline_sec,
                ),
            ),
            (
                "full_image",
                self.c2,
                asyncio.wait_for(
                    self.c2.retrieve(request, limits["full_image"]),
                    timeout=self._deadline_sec,
                ),
            ),
            (
                "trending",
                self.c3,
                asyncio.wait_for(
                    self.c3.retrieve(
                        request,
                        limits["trending"],
                        cluster_id=cluster_id,
                    ),
                    timeout=self._deadline_sec,
                ),
            ),
            (
                "popular",
                self.c4,
                asyncio.wait_for(
                    self.c4.retrieve(
                        request,
                        limits["popular"],
                        cluster_id=cluster_id,
                    ),
                    timeout=self._deadline_sec,
                ),
            ),
            (
                "freshness",
                self.c5,
                asyncio.wait_for(
                    self.c5.retrieve(
                        request,
                        limits["freshness"],
                        cluster_id=cluster_id,
                    ),
                    timeout=self._deadline_sec,
                ),
            ),
        ]

        results = await asyncio.gather(
            *[run for _, _, run in channel_runs],
            return_exceptions=True,
        )

        candidates_by_id: dict[str, dict] = {}

        for (channel_name, channel, _), result in zip(
            channel_runs, results, strict=True
        ):
            if isinstance(result, asyncio.TimeoutError):
                logger.warning(
                    "Channel %s exceeded deadline of %dms and was gracefully dropped",
                    channel.__class__.__name__,
                    int(self._deadline_sec * 1000),
                    extra={
                        "job_id": request.job_id,
                        "channel": channel_name,
                    },
                )
                continue

            if isinstance(result, Exception):
                logger.error(
                    "Retrieval channel %s failed for job_id=%s: %s",
                    channel_name,
                    request.job_id,
                    result,
                )
                continue

            for candidate in result:
                image_id = candidate["image_id"]
                if image_id in candidates_by_id:
                    candidates_by_id[image_id] = _merge_candidates(
                        candidates_by_id[image_id],
                        candidate,
                    )
                else:
                    candidates_by_id[image_id] = dict(candidate)

        return list(candidates_by_id.values())

    def _limit_for_channel(
        self,
        request: RecommendationRequest,
        channel_key: str,
    ) -> int:
        overrides = request.retrieval_overrides or {}
        if channel_key in overrides:
            return overrides[channel_key]

        default_limit = _DEFAULT_CHANNEL_LIMITS[channel_key]
        pool_floor = max(50, request.top_n + 30)
        return max(default_limit, pool_floor)


def _merge_candidates(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)

    existing_channels = list(existing.get("source_channels", []))
    for channel in incoming.get("source_channels", []):
        if channel not in existing_channels:
            existing_channels.append(channel)
    merged["source_channels"] = existing_channels

    for key, value in incoming.items():
        if key == "source_channels":
            continue
        if key in ("image_id", "image_url", "cluster_id"):
            if merged.get(key) is None and value is not None:
                merged[key] = value
            continue
        merged[key] = value

    return merged


@lru_cache
def get_retrieval_orchestrator() -> RetrievalOrchestrator:
    """FastAPI dependency factory for :class:`RetrievalOrchestrator`."""
    return RetrievalOrchestrator(get_spanner_database())
