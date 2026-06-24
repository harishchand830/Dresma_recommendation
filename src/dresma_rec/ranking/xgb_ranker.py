"""XGBoost production ranker (RFC Section 20.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import xgboost as xgb

from dresma_rec.features.assembler import FeatureAssembler
from dresma_rec.ranking.constants import EXPECTED_FEATURES

if TYPE_CHECKING:
    from dresma_rec.ranking.model_manager import ModelManager


class XGBoostRanker:
    """Scores candidates with the active PRODUCTION XGBoost booster."""

    def __init__(self, model_manager: ModelManager) -> None:
        self.model_manager = model_manager
        self._assembler = FeatureAssembler()

    def rank(self, candidates: list[dict], top_n: int) -> list[dict]:
        if not self.model_manager.active_booster or not candidates:
            return candidates[:top_n]

        feature_matrix = self._assembler.assemble_matrix(candidates)
        dmatrix = xgb.DMatrix(feature_matrix, feature_names=EXPECTED_FEATURES)
        scores = self.model_manager.active_booster.predict(dmatrix)

        for candidate, score in zip(candidates, scores):
            candidate["model_score"] = float(score)
            candidate["ranking_mode"] = "xgboost"
            candidate["model_version"] = self.model_manager.active_version

        ranked = sorted(
            candidates,
            key=lambda candidate: candidate["model_score"],
            reverse=True,
        )
        return ranked[:top_n]
