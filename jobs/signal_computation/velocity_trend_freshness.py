"""Velocity, trend, and freshness signal computation (RFC Section 6, Task 2.8)."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from jobs.common.engagement import (
    engagement_velocity,
    freshness_score,
    trend_z_score,
    weighted_engagement,
)


@dataclass(frozen=True)
class ReferenceRow:
    image_id: str
    cluster_id: int | None
    likes: int
    comments: int
    anchor: datetime


@dataclass(frozen=True)
class HistoryRow:
    image_id: str
    weighted_engage: float


def _anchor_timestamp(published_at: datetime | None, ingested_at: datetime | None) -> datetime:
    for candidate in (published_at, ingested_at):
        if candidate is not None:
            if candidate.tzinfo is None:
                return candidate.replace(tzinfo=timezone.utc)
            return candidate
    return datetime.now(timezone.utc)


def build_reference_rows(rows: list[tuple]) -> list[ReferenceRow]:
    references: list[ReferenceRow] = []
    for image_id, cluster_id, likes, comments, published_at, ingested_at in rows:
        references.append(
            ReferenceRow(
                image_id=image_id,
                cluster_id=int(cluster_id) if cluster_id is not None else None,
                likes=int(likes or 0),
                comments=int(comments or 0),
                anchor=_anchor_timestamp(published_at, ingested_at),
            )
        )
    return references


def build_history_lookup(rows: list[tuple], window_start: datetime) -> dict[str, float]:
    lookup: dict[str, float] = {}
    for image_id, snapshot_at, weighted_engage in rows:
        if snapshot_at is None:
            continue
        if snapshot_at.tzinfo is None:
            snapshot_at = snapshot_at.replace(tzinfo=timezone.utc)
        if snapshot_at < window_start:
            continue
        lookup[image_id] = float(weighted_engage or 0.0)
    return lookup


def compute_velocity_trend_freshness(
    references: list[ReferenceRow],
    history_lookup: dict[str, float],
    as_of: date,
) -> list[dict]:
    now = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc)
    velocities_by_cluster: dict[int | None, list[float]] = {}
    partial_rows: list[dict] = []

    for reference in references:
        current_engagement = weighted_engagement(reference.likes, reference.comments)
        previous_engagement = history_lookup.get(reference.image_id)
        age_days = max((now - reference.anchor).total_seconds() / 86_400.0, 1.0)
        velocity = engagement_velocity(current_engagement, previous_engagement, age_days)
        fresh = freshness_score(reference.anchor, now=now)

        partial_rows.append(
            {
                "image_id": reference.image_id,
                "cluster_id": reference.cluster_id,
                "engagement_velocity": velocity,
                "freshness_score": fresh,
            }
        )
        velocities_by_cluster.setdefault(reference.cluster_id, []).append(velocity)

    cluster_stats = {
        cluster_id: (
            statistics.fmean(velocities),
            statistics.pstdev(velocities) if len(velocities) > 1 else 0.0,
        )
        for cluster_id, velocities in velocities_by_cluster.items()
    }

    signal_rows: list[dict] = []
    for row in partial_rows:
        mean_velocity, std_velocity = cluster_stats.get(row["cluster_id"], (0.0, 0.0))
        signal_rows.append(
            {
                "image_id": row["image_id"],
                "as_of_date": as_of,
                "cluster_id": row["cluster_id"],
                "engagement_velocity": row["engagement_velocity"],
                "trend_score": trend_z_score(
                    row["engagement_velocity"],
                    mean_velocity,
                    std_velocity,
                ),
                "freshness_score": row["freshness_score"],
            }
        )
    return signal_rows
