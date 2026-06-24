"""Unit tests for batch signal computation helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone

from jobs.signal_computation.velocity_trend_freshness import (
    ReferenceRow,
    build_history_lookup,
    compute_velocity_trend_freshness,
)


def test_compute_velocity_trend_freshness_assigns_cluster_z_scores() -> None:
    now = datetime(2026, 6, 17, tzinfo=timezone.utc)
    references = [
        ReferenceRow("img-fast", 1, 100, 10, now),
        ReferenceRow("img-slow", 1, 10, 1, now),
    ]
    history_lookup = {
        "img-fast": 10.0,
        "img-slow": 9.0,
    }

    rows = compute_velocity_trend_freshness(
        references,
        history_lookup,
        date(2026, 6, 17),
    )

    by_id = {row["image_id"]: row for row in rows}
    assert by_id["img-fast"]["engagement_velocity"] > by_id["img-slow"]["engagement_velocity"]
    assert by_id["img-fast"]["trend_score"] > by_id["img-slow"]["trend_score"]
    assert 0.0 < by_id["img-fast"]["freshness_score"] <= 1.0


def test_build_history_lookup_filters_old_snapshots() -> None:
    window_start = datetime(2026, 6, 16, tzinfo=timezone.utc)
    rows = [
        ("img-1", datetime(2026, 6, 15, tzinfo=timezone.utc), 1.0),
        ("img-2", datetime(2026, 6, 16, 12, tzinfo=timezone.utc), 4.0),
    ]

    lookup = build_history_lookup(rows, window_start)

    assert lookup == {"img-2": 4.0}
