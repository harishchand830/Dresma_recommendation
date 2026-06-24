"""Offline clustering helpers for the reclustering job (RFC Section 4.2b)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ClusterResult:
    cluster_id: int
    centroid: list[float]
    size: int
    member_image_ids: list[str]


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    return 1.0 - float(np.dot(_normalize(a), _normalize(b)))


def kmeans_cosine(
    embeddings: dict[str, list[float]],
    k: int,
    max_iterations: int = 20,
) -> list[ClusterResult]:
    if not embeddings:
        return []

    image_ids = list(embeddings.keys())
    vectors = np.array([embeddings[image_id] for image_id in image_ids], dtype=np.float64)
    effective_k = max(1, min(k, len(image_ids)))

    rng = np.random.default_rng(42)
    centroid_indices = rng.choice(len(vectors), size=effective_k, replace=False)
    centroids = vectors[centroid_indices].copy()

    assignments = np.zeros(len(vectors), dtype=np.int64)
    for _ in range(max_iterations):
        distances = np.array(
            [[_cosine_distance(vector, centroid) for centroid in centroids] for vector in vectors]
        )
        new_assignments = distances.argmin(axis=1)
        if np.array_equal(new_assignments, assignments):
            break
        assignments = new_assignments
        for cluster_index in range(effective_k):
            members = vectors[assignments == cluster_index]
            if len(members) == 0:
                centroids[cluster_index] = vectors[rng.integers(0, len(vectors))]
            else:
                centroids[cluster_index] = members.mean(axis=0)

    clusters: list[ClusterResult] = []
    for cluster_index in range(effective_k):
        member_ids = [
            image_ids[index]
            for index, assigned in enumerate(assignments)
            if assigned == cluster_index
        ]
        clusters.append(
            ClusterResult(
                cluster_id=cluster_index,
                centroid=centroids[cluster_index].astype(float).tolist(),
                size=len(member_ids),
                member_image_ids=member_ids,
            )
        )
    return clusters
