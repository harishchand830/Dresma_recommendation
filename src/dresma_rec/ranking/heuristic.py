"""Cold-start heuristic ranker (RFC Section 20.2)."""

from __future__ import annotations

import logging
import math
import random
from functools import lru_cache
from typing import Final

logger = logging.getLogger(__name__)

_DEFAULT_WEIGHT_FG: Final[float] = 0
_DEFAULT_WEIGHT_FULL: Final[float] = 0
_DEFAULT_WEIGHT_TREND: Final[float] = 0
_DEFAULT_WEIGHT_POPULAR: Final[float] = 0
_DEFAULT_WEIGHT_FRESH: Final[float] = 1

_EXPLORATION_MIN_RATE = 0.05
_EXPLORATION_MAX_RATE = 0.10
_EXPLORATION_MIN_TOP_N = 10


def _exploration_slot_count(top_n: int, exploration_rate: float) -> int:
    """Return exploration slots within 5–10% of ``top_n``; skip when ``top_n`` < 10."""
    if top_n < _EXPLORATION_MIN_TOP_N:
        return 0

    min_slots = max(1, math.ceil(top_n * _EXPLORATION_MIN_RATE))
    max_slots = max(min_slots, math.floor(top_n * _EXPLORATION_MAX_RATE))
    target = int(top_n * exploration_rate)
    return min(max_slots, max(min_slots, target))


class HeuristicRanker:
    """Weighted blend ranker for pre-model / cold-start serving."""

    EXPLORATION_RATE = 0.10
    EXPLORATION_SOURCE_CHANNEL = "freshness"

    def __init__(
        self,
        *,
        weight_fg: float = _DEFAULT_WEIGHT_FG,
        weight_full: float = _DEFAULT_WEIGHT_FULL,
        weight_trend: float = _DEFAULT_WEIGHT_TREND,
        weight_popular: float = _DEFAULT_WEIGHT_POPULAR,
        weight_fresh: float = _DEFAULT_WEIGHT_FRESH,
    ) -> None:
        self.weight_fg = float(weight_fg)
        self.weight_full = float(weight_full)
        self.weight_trend = float(weight_trend)
        self.weight_popular = float(weight_popular)
        self.weight_fresh = float(weight_fresh)

    def rank(self, candidates: list[dict], top_n: int) -> list[dict]:
        if top_n <= 0:
            return []
        
        logger.debug(
            "Ranking with weights: fg=%s, full=%s, trend=%s, popular=%s, fresh=%s",
            self.weight_fg, self.weight_full, self.weight_trend,
            self.weight_popular, self.weight_fresh
        )

        for i, candidate in enumerate(candidates):
            fg_dist = _score_or_default(candidate, "fg_cosine_distance", 1.0)
            full_dist = _score_or_default(candidate, "full_cosine_distance", 1.0)
            trend = _score_or_default(candidate, "trend_score", 0.0)
            popular = _score_or_default(candidate, "engagement_score", 0.0)
            fresh = _score_or_default(candidate, "freshness_score", 0.0)

            fg_sim = 1.0 / (1.0 + fg_dist)
            full_sim = 1.0 / (1.0 + full_dist)

            candidate["model_score"] = (
                (self.weight_fg * fg_sim)
                + (self.weight_full * full_sim)
                + (self.weight_trend * trend)
                + (self.weight_popular * popular)
                + (self.weight_fresh * fresh)
            )
            candidate["ranking_mode"] = "cold_start_heuristic"
            
            if logger.isEnabledFor(logging.DEBUG) and i < 10:  # Log first 10
                logger.debug(
                    "Candidate %s: fg_sim=%.4f, full_sim=%.4f, trend=%.4f, popular=%.4f, fresh=%.4f => model_score=%.4f",
                    candidate.get('image_id'), fg_sim, full_sim, trend, popular, fresh,
                    candidate['model_score']
                )

        ranked = sorted(
            candidates,
            key=lambda candidate: candidate["model_score"],
            reverse=True,
        )

        if len(ranked) <= top_n:
            return ranked[:top_n]

        num_explor_slots = _exploration_slot_count(top_n, self.EXPLORATION_RATE)
        if num_explor_slots == 0:
            return ranked[:top_n]

        num_exploit_slots = top_n - num_explor_slots

        exploited = ranked[:num_exploit_slots]
        remaining_pool = ranked[num_exploit_slots:]

        exploration_pool = [
            candidate
            for candidate in remaining_pool
            if self.EXPLORATION_SOURCE_CHANNEL in candidate.get("source_channels", [])
        ]
        if not exploration_pool:
            exploration_pool = list(remaining_pool)

        sample_size = min(num_explor_slots, len(exploration_pool))
        if sample_size == 0:
            return ranked[:top_n]

        exploration_items = random.sample(exploration_pool, sample_size)
        for item in exploration_items:
            item["is_exploration"] = True
            item["ranking_mode"] = "exploration"

        selected_ids = {
            candidate["image_id"]
            for candidate in (*exploited, *exploration_items)
        }
        deficit = top_n - len(exploited) - len(exploration_items)
        if deficit > 0:
            backfill = [
                candidate
                for candidate in ranked
                if candidate["image_id"] not in selected_ids
            ][:deficit]
            exploited = [*exploited, *backfill]
            selected_ids.update(candidate["image_id"] for candidate in backfill)

        final_results = sorted(
            [*exploited, *exploration_items],
            key=lambda candidate: candidate["model_score"],
            reverse=True,
        )
        return final_results[:top_n]


def _score_or_default(candidate: dict, key: str, default: float) -> float:
    value = candidate.get(key, default)
    if value is None:
        return default
    return float(value)


@lru_cache
def get_heuristic_ranker() -> HeuristicRanker:
    """FastAPI dependency factory for :class:`HeuristicRanker`."""
    return HeuristicRanker()
