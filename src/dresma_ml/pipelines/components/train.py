"""Vertex AI component to train an XGBoost learning-to-rank model."""

from kfp.dsl import Dataset, Model, Output, component


@component(
    base_image="python:3.10",
    packages_to_install=[
        "google-cloud-bigquery",
        "pandas",
        "xgboost",
        "db-dtypes",
        "pyarrow",
    ],
)
def train_xgboost_ranker(
    project_id: str,
    dataset_id: str,
    train_table: str,
    model_artifact: Output[Model],
    test_data_artifact: Output[Dataset],
) -> None:
    """Train ``rank:ndcg`` ranker on a materialized BigQuery table."""
    import json
    import os

    import pandas as pd
    import xgboost as xgb
    from google.cloud import bigquery

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

    client = bigquery.Client(project=project_id)
    df = client.query(f"SELECT * FROM `{train_table}`").to_dataframe()

    df = df.sort_values("served_at", ascending=True).reset_index(drop=True)
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()

    test_output_path = test_data_artifact.path
    if os.path.isdir(test_output_path):
        test_output_path = os.path.join(test_output_path, "data.parquet")
    test_df.to_parquet(test_output_path, index=False)

    train_df = train_df.sort_values("job_id").reset_index(drop=True)
    X_train = _assemble_features(train_df)
    y_train = train_df["relevance_label"].values
    qid_train, _ = pd.factorize(train_df["job_id"], sort=False)

    model = xgb.XGBRanker(
        objective="rank:ndcg",
        n_estimators=100,
        learning_rate=0.1,
    )
    model.fit(X_train, y_train, qid=qid_train)

    model_output_path = model_artifact.path
    if os.path.isdir(model_output_path):
        model_output_path = os.path.join(model_output_path, "model.json")
    model.save_model(model_output_path)
