"""Unit tests for offline clustering helpers."""

from __future__ import annotations

from jobs.reclustering.clustering import kmeans_cosine


def test_kmeans_cosine_assigns_every_image() -> None:
    embeddings = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.99, 0.01, 0.0],
        "c": [0.0, 1.0, 0.0],
        "d": [0.0, 0.99, 0.01],
    }

    clusters = kmeans_cosine(embeddings, k=2)

    assigned = {
        image_id
        for cluster in clusters
        for image_id in cluster.member_image_ids
    }
    assert assigned == set(embeddings)
    assert len(clusters) == 2
    assert all(cluster.size > 0 for cluster in clusters)
