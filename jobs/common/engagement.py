"""Engagement math shared across batch signal jobs (RFC Section 6)."""

from __future__ import annotations

import math
from datetime import datetime, timezone

COMMENT_WEIGHT = 3.0
FRESHNESS_HALF_LIFE_DAYS = 30.0
VELOCITY_WINDOW_DAYS = 1.0
TREND_CLAMP_MIN = -3.0
TREND_CLAMP_MAX = 6.0
EPSILON = 1e-6


def weighted_engagement(likes: int, comments: int) -> float:
    # Guard against unexpected negative values from the source data.
    safe_likes = max(0, likes)
    safe_comments = max(0, comments)
    return float(safe_likes) + (COMMENT_WEIGHT * float(safe_comments))


def freshness_score(anchor: datetime, now: datetime | None = None) -> float:
    reference = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    age_days = max((reference - anchor).total_seconds() / 86_400.0, 0.0)
    return math.exp(-age_days / FRESHNESS_HALF_LIFE_DAYS)


def engagement_velocity(
    current_engagement: float,
    previous_engagement: float | None,
    age_days: float,
) -> float:
    if previous_engagement is None:
        if age_days <= 0:
            return 0.0
        return current_engagement / age_days
    return (current_engagement - previous_engagement) / VELOCITY_WINDOW_DAYS


def engagement_score_normalized(
    engagement: float,
    cluster_p99: float,
) -> float:
    if cluster_p99 <= 0:
        return 0.0
    return math.log1p(engagement) / math.log1p(cluster_p99)


def trend_z_score(velocity: float, mean_velocity: float, std_velocity: float) -> float:
    z = (velocity - mean_velocity) / (std_velocity + EPSILON)
    return max(TREND_CLAMP_MIN, min(TREND_CLAMP_MAX, z))


def percentile_99(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(math.ceil(0.99 * len(ordered))) - 1)
    return ordered[max(index, 0)]
