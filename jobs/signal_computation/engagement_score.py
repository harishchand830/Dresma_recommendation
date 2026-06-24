"""Engagement score normalization (RFC Section 6.2, Task 2.9)."""

from __future__ import annotations

from collections import defaultdict

from jobs.common.engagement import engagement_score_normalized, percentile_99, weighted_engagement


def apply_engagement_scores(
    signal_rows: list[dict],
    references: list,
) -> list[dict]:
    engagement_by_image = {
        reference.image_id: weighted_engagement(reference.likes, reference.comments)
        for reference in references
    }
    cluster_engagements: dict[int | None, list[float]] = defaultdict(list)

    for reference in references:
        cluster_engagements[reference.cluster_id].append(
            engagement_by_image[reference.image_id]
        )

    cluster_p99 = {
        cluster_id: percentile_99(values)
        for cluster_id, values in cluster_engagements.items()
    }

    for row in signal_rows:
        image_id = row["image_id"]
        cluster_id = row["cluster_id"]
        engagement = engagement_by_image.get(image_id, 0.0)
        row["engagement_score"] = engagement_score_normalized(
            engagement,
            cluster_p99.get(cluster_id, 0.0),
        )
    return signal_rows
