"""Vertex AI component to upload a model artifact and register it in Spanner."""

from kfp.dsl import Input, Model, OutputPath, component


@component(
    base_image="python:3.10",
    packages_to_install=["google-cloud-storage", "google-cloud-spanner"],
)
def register_model(
    model_artifact: Input[Model],
    project_id: str,
    run_id: str,
    bucket_name: str,
    spanner_instance: str,
    spanner_database: str,
    gcs_uri: OutputPath(str),
) -> None:
    """Upload model JSON to GCS and insert a STAGING row in ``model_metadata``."""
    import json
    import os

    from google.cloud import spanner, storage

    _EXPECTED_FEATURES = [
        "fg_cosine_distance",
        "full_cosine_distance",
        "trend_score",
        "engagement_score",
        "freshness_score",
    ]

    model_input_path = model_artifact.path
    if os.path.isdir(model_input_path):
        model_input_path = os.path.join(model_input_path, "model.json")

    blob_name = f"xgboost/run_{run_id}/xgb-rank.json"
    storage_client = storage.Client(project=project_id)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(model_input_path)

    final_gcs_uri = f"gs://{bucket_name}/{blob_name}"
    model_version = f"xgb-{run_id}"

    spanner_client = spanner.Client(project=project_id)
    database = spanner_client.instance(spanner_instance).database(spanner_database)

    def insert_transaction(transaction: spanner.Transaction) -> None:
        transaction.insert(
            "model_metadata",
            columns=[
                "model_version",
                "artifact_uri",
                "feature_list",
                "status",
                "trained_at",
            ],
            values=[
                (
                    model_version,
                    final_gcs_uri,
                    json.dumps(_EXPECTED_FEATURES),
                    "STAGING",
                    spanner.COMMIT_TIMESTAMP,
                )
            ],
        )

    database.run_in_transaction(insert_transaction)

    with open(gcs_uri, "w", encoding="utf-8") as handle:
        handle.write(final_gcs_uri)

    print(final_gcs_uri)
