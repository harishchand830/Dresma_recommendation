"""Vertex AI component to evaluate a trained XGBoost ranker."""

from kfp.dsl import Dataset, Input, Metrics, Model, Output, component


@component(
    base_image="python:3.10",
    packages_to_install=["pandas", "xgboost", "scikit-learn", "pyarrow"],
)
def evaluate_xgboost_ranker(
    model_artifact: Input[Model],
    test_data_artifact: Input[Dataset],
    metrics: Output[Metrics],
) -> None:
    """Compute NDCG@3, NDCG@10, and MRR on the held-out test split."""
    import json
    import os

    import numpy as np
    import pandas as pd
    import xgboost as xgb
    from sklearn.metrics import ndcg_score

    _EXPECTED_FEATURES = [
        "fg_cosine_distance",
        "full_cosine_distance",
        "trend_score",
        "engagement_score",
        "freshness_score",
    ]
    _DISTANCE_FEATURES = frozenset(
        {"fg_cosine_distance", "full_cosine_distance"}
    )

    def _feature_default(feature_name: str) -> float:
        if feature_name in _DISTANCE_FEATURES:
            return 1.0
        return 0.0

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

    def _assemble_features(df: pd.DataFrame) -> pd.DataFrame:
        if "feature_snapshot" not in df.columns:
            raise ValueError(
                "Input DataFrame must contain a 'feature_snapshot' column"
            )

        rows = []
        for snapshot in df["feature_snapshot"]:
            parsed = _parse_snapshot(snapshot)
            rows.append(
                {
                    feature_name: _extract_feature(parsed, feature_name)
                    for feature_name in _EXPECTED_FEATURES
                }
            )

        return pd.DataFrame(rows, columns=_EXPECTED_FEATURES).astype("float32")

    def _reciprocal_rank(labels: np.ndarray) -> float:
        for position, label in enumerate(labels, start=1):
            if label > 0:
                return 1.0 / position
        return 0.0

    test_input_path = test_data_artifact.path
    if os.path.isdir(test_input_path):
        test_input_path = os.path.join(test_input_path, "data.parquet")
    test_df = pd.read_parquet(test_input_path)

    test_df = test_df.sort_values("job_id").reset_index(drop=True)
    X_test = _assemble_features(test_df)

    model_input_path = model_artifact.path
    if os.path.isdir(model_input_path):
        model_input_path = os.path.join(model_input_path, "model.json")
    model = xgb.XGBRanker()
    model.load_model(model_input_path)

    test_df["predicted_score"] = model.predict(X_test)

    ndcg_3_scores: list[float] = []
    ndcg_10_scores: list[float] = []
    mrr_scores: list[float] = []

    for _, group in test_df.groupby("job_id", sort=False):
        ranked = group.sort_values("predicted_score", ascending=False)
        y_true = ranked["relevance_label"].to_numpy().reshape(1, -1)
        y_score = ranked["predicted_score"].to_numpy().reshape(1, -1)

        ndcg_3_scores.append(float(ndcg_score(y_true, y_score, k=3)))
        ndcg_10_scores.append(float(ndcg_score(y_true, y_score, k=10)))
        mrr_scores.append(_reciprocal_rank(ranked["relevance_label"].to_numpy()))

    avg_ndcg_3 = float(np.mean(ndcg_3_scores)) if ndcg_3_scores else 0.0
    avg_ndcg_10 = float(np.mean(ndcg_10_scores)) if ndcg_10_scores else 0.0
    avg_mrr = float(np.mean(mrr_scores)) if mrr_scores else 0.0

    metrics.log_metric("ndcg_3", avg_ndcg_3)
    metrics.log_metric("ndcg_10", avg_ndcg_10)
    metrics.log_metric("mrr", avg_mrr)
