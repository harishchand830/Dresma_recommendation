"""Serve-time feature assembly for ranking (RFC Section 9)."""

from dresma_rec.features.assembler import FeatureAssembler
from dresma_rec.features.definitions import EXPECTED_FEATURES, feature_default

__all__ = ["EXPECTED_FEATURES", "FeatureAssembler", "feature_default"]
