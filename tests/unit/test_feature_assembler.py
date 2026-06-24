"""Unit tests for serve-time feature assembly."""

from __future__ import annotations

import pytest

from dresma_rec.features.assembler import FeatureAssembler
from dresma_rec.features.definitions import EXPECTED_FEATURES


def test_assemble_candidate_uses_defaults_for_missing_keys() -> None:
    assembler = FeatureAssembler()
    vector = assembler.assemble_candidate({"image_id": "img-1"})

    assert vector == [1.0, 1.0, 0.0, 0.0, 0.0]
    assert len(vector) == len(EXPECTED_FEATURES)


def test_assemble_matrix_preserves_order() -> None:
    assembler = FeatureAssembler()
    matrix = assembler.assemble_matrix(
        [
            {
                "fg_cosine_distance": 0.2,
                "full_cosine_distance": 0.4,
                "trend_score": 0.8,
                "engagement_score": 0.5,
                "freshness_score": 0.9,
            }
        ]
    )

    assert matrix.shape == (1, 5)
    assert matrix[0].tolist() == pytest.approx([0.2, 0.4, 0.8, 0.5, 0.9])


def test_feature_snapshot_round_trip() -> None:
    assembler = FeatureAssembler()
    candidate = {
        "fg_cosine_distance": 0.1,
        "trend_score": 0.7,
    }
    snapshot = assembler.feature_snapshot(candidate)

    assert assembler.from_dataframe_column(snapshot) == pytest.approx(
        assembler.assemble_candidate(candidate)
    )
