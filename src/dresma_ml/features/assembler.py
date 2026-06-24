"""Flatten ``feature_snapshot`` JSON into the ordered XGBoost feature matrix."""

from __future__ import annotations

import json

import pandas as pd

_DISTANCE_FEATURES = frozenset({"fg_cosine_distance", "full_cosine_distance"})
_DISTANCE_DEFAULT = 1.0
_SCORE_DEFAULT = 0.0


def _feature_default(feature_name: str) -> float:
    if feature_name in _DISTANCE_FEATURES:
        return _DISTANCE_DEFAULT
    return _SCORE_DEFAULT


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


def _extract_feature(snapshot: dict, feature_name: str) -> float:
    value = snapshot.get(feature_name, _feature_default(feature_name))
    if value is None:
        return _feature_default(feature_name)
    return float(value)


class FeatureAssembler:
    """Strict contract between the heuristic ranker and the ML model."""

    EXPECTED_FEATURES = [
        "fg_cosine_distance",
        "full_cosine_distance",
        "trend_score",
        "engagement_score",
        "freshness_score",
    ]

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if "feature_snapshot" not in df.columns:
            raise ValueError("Input DataFrame must contain a 'feature_snapshot' column")

        rows = []
        for snapshot in df["feature_snapshot"]:
            parsed = _parse_snapshot(snapshot)
            rows.append(
                {
                    feature_name: _extract_feature(parsed, feature_name)
                    for feature_name in self.EXPECTED_FEATURES
                }
            )

        return pd.DataFrame(rows, columns=self.EXPECTED_FEATURES).astype("float32")
