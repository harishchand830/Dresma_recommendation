"""Integration tests for the recommendations and interaction APIs."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from dresma_rec.schemas.recommendations import RecommendationResult

from tests.conftest import MOCK_EMBEDDING

REQUESTED_TOP_N = 20


def test_end_to_end_user_journey(
    client,
    recommendation_events_capture: list[RecommendationResult],
) -> None:
    random.seed(0)

    recommendation_payload = {
        "job_id": "job-test-001",
        "upload": {
            "foreground_embedding": MOCK_EMBEDDING,
            "full_image_embedding": MOCK_EMBEDDING,
        },
        "top_n": REQUESTED_TOP_N,
    }

    recommendation_response = client.post(
        "/v1/recommendations",
        json=recommendation_payload,
    )
    assert recommendation_response.status_code == 200

    recommendation_body = recommendation_response.json()
    assert recommendation_body["job_id"] == recommendation_payload["job_id"]
    assert recommendation_body["ranking_mode"] == "cold_start_heuristic"
    assert recommendation_body["assigned_cluster_id"] == 412
    assert len(recommendation_body["results"]) == REQUESTED_TOP_N

    observed_channels: set[str] = set()
    for result in recommendation_body["results"]:
        assert "model_score" in result
        assert "source_channels" in result
        assert isinstance(result["source_channels"], list)
        observed_channels.update(result["source_channels"])
        assert "metadata" not in result
        assert "ranking_mode" not in result

    assert "foreground" in observed_channels
    assert "full_image" in observed_channels
    assert "trending" in observed_channels
    assert "popular" in observed_channels
    assert "freshness" in observed_channels

    assert len(recommendation_events_capture) == REQUESTED_TOP_N
    served_ranking_modes = [
        served.metadata.get("ranking_mode")
        for served in recommendation_events_capture
    ]
    assert "exploration" in served_ranking_modes
    assert served_ranking_modes.count("exploration") >= 1
    assert served_ranking_modes.count("cold_start_heuristic") >= 1

    exploration_items = [
        served
        for served in recommendation_events_capture
        if served.metadata.get("ranking_mode") == "exploration"
    ]
    assert exploration_items
    assert all(
        "freshness" in served.metadata.get("source_channels", [])
        for served in exploration_items
    )

    job_id = recommendation_body["job_id"]
    image_id = recommendation_body["results"][0]["image_id"]
    event_time = datetime.now(timezone.utc).isoformat()

    impression_payload = {
        "event_id": "evt-impression-001",
        "job_id": job_id,
        "image_id": image_id,
        "event_type": "IMPRESSION",
        "position": 1,
        "event_time": event_time,
    }
    impression_response = client.post("/v1/interaction", json=impression_payload)
    assert impression_response.status_code == 202
    assert impression_response.json() == {"status": "queued"}

    selection_payload = {
        "event_id": "evt-selection-001",
        "job_id": job_id,
        "image_id": image_id,
        "event_type": "SELECTION",
        "position": 1,
        "event_time": event_time,
    }
    selection_response = client.post("/v1/interaction", json=selection_payload)
    assert selection_response.status_code == 202
    assert selection_response.json() == {"status": "queued"}
