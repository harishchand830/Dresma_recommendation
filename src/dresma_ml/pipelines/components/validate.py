"""Vertex AI component to validate a trained XGBoost ranker before registration."""

from kfp.dsl import Input, Metrics, Model, component


@component(
    base_image="python:3.10",
    packages_to_install=["xgboost"],
)
def validate_xgboost_ranker(
    model_artifact: Input[Model],
    metrics: Input[Metrics],
) -> bool:
    """Hard gate: NDCG baseline and ordered feature-list contract."""
    import json
    import os

    import xgboost as xgb

    _EXPECTED_FEATURES = [
        "fg_cosine_distance",
        "full_cosine_distance",
        "trend_score",
        "engagement_score",
        "freshness_score",
    ]

    def _read_ndcg_3(metrics_input: Metrics) -> float:
        metadata = getattr(metrics_input, "metadata", None)
        if isinstance(metadata, dict) and "ndcg_3" in metadata:
            return float(metadata["ndcg_3"])

        metrics_path = metrics_input.path
        candidate_paths = [
            metrics_path,
            os.path.join(metrics_path, "metrics.json"),
        ]
        for path in candidate_paths:
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)

            if isinstance(payload, dict):
                if "ndcg_3" in payload:
                    return float(payload["ndcg_3"])
                for item in payload.get("metrics", []):
                    if item.get("name") == "ndcg_3":
                        value = item.get("numberValue", item.get("value"))
                        return float(value)

        raise ValueError("Could not read ndcg_3 from metrics artifact")

    ndcg_3 = _read_ndcg_3(metrics)
    if ndcg_3 <= 0.0:
        raise ValueError("Model failed NDCG baseline check.")

    model_input_path = model_artifact.path
    if os.path.isdir(model_input_path):
        model_input_path = os.path.join(model_input_path, "model.json")

    model = xgb.XGBRanker()
    model.load_model(model_input_path)
    feature_names = list(model.get_booster().feature_names or [])

    if feature_names != _EXPECTED_FEATURES:
        raise ValueError(
            f"Feature mismatch! Expected {_EXPECTED_FEATURES}, got {feature_names}"
        )

    return True
