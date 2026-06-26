"""Unit tests for the cold-start heuristic ranker."""

from __future__ import annotations

import random

import pytest

from dresma_rec.ranking.heuristic import HeuristicRanker, _exploration_slot_count


def _expected_model_score(
    fg_dist: float | None = None,
    full_dist: float | None = None,
    brand_dist: float | None = None,
    trend: float = 0.0,
    popular: float = 0.0,
    fresh: float = 0.0,
) -> float:
    fg_sim = 1.0 / (1.0 + fg_dist) if fg_dist is not None else 0.0
    full_sim = 1.0 / (1.0 + full_dist) if full_dist is not None else 0.0
    brand_sim = 1.0 / (1.0 + brand_dist) if brand_dist is not None else 0.0
    return (
        (0.4 * fg_sim)
        + (0.2 * full_sim)
        + (0.02 * brand_sim)
        + (0.2 * trend)
        + (0.1 * popular)
        + (0.1 * fresh)
    )


def test_heuristic_ranker_math() -> None:
    candidates = [
        {
            "image_id": "fg-only",
            "image_url": "https://example.com/fg-only.jpg",
            "source_channels": ["foreground"],
            "fg_cosine_distance": 0.1,
        },
        {
            "image_id": "multi-signal",
            "image_url": "https://example.com/multi.jpg",
            "source_channels": ["foreground", "full_image", "trending"],
            "fg_cosine_distance": 0.5,
            "full_cosine_distance": 0.2,
            "brand_cosine_distance": 0.3,
            "trend_score": 0.8,
        },
        {
            "image_id": "defaults-only",
            "image_url": "https://example.com/defaults.jpg",
            "source_channels": ["trending"],
        },
    ]

    ranker = HeuristicRanker(
        weight_fg=0.4,
        weight_full=0.2,
        weight_brand=0.02,
        weight_trend=0.2,
        weight_popular=0.1,
        weight_fresh=0.1,
    )
    ranked = ranker.rank(candidates, top_n=3)

    assert len(ranked) == 3

    scores = [candidate["model_score"] for candidate in ranked]
    assert scores == sorted(scores, reverse=True)

    ranked_by_id = {candidate["image_id"]: candidate for candidate in ranked}

    assert ranked_by_id["multi-signal"]["model_score"] == pytest.approx(
        _expected_model_score(fg_dist=0.5, full_dist=0.2, brand_dist=0.3, trend=0.8)
    )
    assert ranked_by_id["fg-only"]["model_score"] == pytest.approx(
        _expected_model_score(fg_dist=0.1)
    )

    default_candidate = ranked_by_id["defaults-only"]
    assert default_candidate["model_score"] == pytest.approx(
        _expected_model_score()
    )
    assert default_candidate["model_score"] == pytest.approx(0.0)

    for candidate in ranked:
        assert candidate["ranking_mode"] == "cold_start_heuristic"

    assert ranked[0]["image_id"] == "multi-signal"
    assert ranked[-1]["image_id"] == "defaults-only"



@pytest.mark.parametrize("top_n", [3, 10, 20])
def test_exploration_slot_count_within_rfc_band(top_n: int) -> None:
    slots = _exploration_slot_count(top_n, HeuristicRanker.EXPLORATION_RATE)

    if top_n < 10:
        assert slots == 0
        return

    assert slots >= 1
    ratio = slots / top_n
    assert 0.05 <= ratio <= 0.10


def _exploration_candidates(pool_size: int) -> list[dict]:
    return [
        {
            "image_id": f"img-{index:03d}",
            "image_url": f"https://example.com/img-{index:03d}.jpg",
            "source_channels": ["freshness"]
            if index >= pool_size // 2
            else ["foreground"],
            "fg_cosine_distance": index * 0.01,
            "freshness_score": 0.9 - (index * 0.001),
        }
        for index in range(pool_size)
    ]


@pytest.mark.parametrize("top_n", [3, 10, 20])
def test_rank_exploration_slots_match_band(top_n: int) -> None:
    random.seed(0)
    ranker = HeuristicRanker()
    ranked = ranker.rank(_exploration_candidates(60), top_n=top_n)

    assert len(ranked) == top_n

    exploration_count = sum(
        1 for candidate in ranked if candidate.get("ranking_mode") == "exploration"
    )
    expected_slots = _exploration_slot_count(top_n, HeuristicRanker.EXPLORATION_RATE)
    assert exploration_count == expected_slots

    if top_n >= 10:
        ratio = exploration_count / top_n
        assert 0.05 <= ratio <= 0.10
