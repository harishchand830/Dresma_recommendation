"""Flatten candidate dicts into the ordered XGBoost feature matrix."""

from __future__ import annotations

import json

import numpy as np

from dresma_rec.features.definitions import EXPECTED_FEATURES, feature_default


def _parse_snapshot(snapshot: object) -> dict:
    if snapshot is None:
        return {}
    if isinstance(snapshot, str):
        if not snapshot.strip():
            return {}
        return json.loads(snapshot)
    if isinstance(snapshot, dict):
        return snapshot
    return {}


def _extract_feature(source: dict, feature_name: str) -> float:
    value = source.get(feature_name, feature_default(feature_name))
    if value is None:
        return feature_default(feature_name)
    return float(value)


class FeatureAssembler:
    """Strict contract between heuristic ranker, XGBoost ranker, and training."""

    def assemble_candidate(self, candidate: dict) -> list[float]:
        return [
            _extract_feature(candidate, feature_name)
            for feature_name in EXPECTED_FEATURES
        ]

    def assemble_matrix(self, candidates: list[dict]) -> np.ndarray:
        if not candidates:
            return np.empty((0, len(EXPECTED_FEATURES)), dtype=np.float32)
        rows = [self.assemble_candidate(candidate) for candidate in candidates]
        return np.array(rows, dtype=np.float32)

    def feature_snapshot(self, candidate: dict) -> dict:
        return {
            feature_name: _extract_feature(candidate, feature_name)
            for feature_name in EXPECTED_FEATURES
        }

    def from_dataframe_column(self, snapshot: object) -> list[float]:
        parsed = _parse_snapshot(snapshot)
        return [
            _extract_feature(parsed, feature_name)
            for feature_name in EXPECTED_FEATURES
        ]
