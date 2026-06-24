"""Ordered feature contract for serve-time and training parity."""

from dresma_rec.ranking.constants import EXPECTED_FEATURES

_DISTANCE_FEATURES = frozenset({"fg_cosine_distance", "full_cosine_distance"})
_DISTANCE_DEFAULT = 1.0
_SCORE_DEFAULT = 0.0


def feature_default(feature_name: str) -> float:
    if feature_name in _DISTANCE_FEATURES:
        return _DISTANCE_DEFAULT
    return _SCORE_DEFAULT
