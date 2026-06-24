"""Vertex AI component to materialize a dated BigQuery training table."""

from kfp.dsl import component


@component(
    base_image="python:3.10",
    packages_to_install=["google-cloud-bigquery", "google-cloud-spanner"],
)
def materialize_training_dataset(
    project_id: str,
    dataset_id: str,
    run_id: str,
    spanner_instance: str,
    spanner_database: str,
) -> str:
    """Materialize ``train_{run_id}`` and register it in Spanner ``training_datasets``."""
    from google.cloud import bigquery, spanner

    client = bigquery.Client(project=project_id)
    destination_table = f"{project_id}.{dataset_id}.train_{run_id}"
    source_table = f"{project_id}.{dataset_id}.v_training_dataset"

    query = (
        f"CREATE OR REPLACE TABLE `{destination_table}` AS "
        f"SELECT * FROM `{source_table}`"
    )
    query_job = client.query(query)
    query_job.result()

    stats_query = f"""
    SELECT
      MIN(DATE(served_at)) AS date_range_start,
      MAX(DATE(served_at)) AS date_range_end,
      COUNT(DISTINCT job_id) AS num_groups,
      COUNT(*) AS num_rows,
      SAFE_DIVIDE(COUNTIF(relevance_label > 0), COUNT(*)) AS positive_rate
    FROM `{destination_table}`
    """
    stats = list(client.query(stats_query).result())[0]

    spanner_client = spanner.Client(project=project_id)
    database = spanner_client.instance(spanner_instance).database(spanner_database)

    def _register(transaction: spanner.Transaction) -> None:
        transaction.insert_or_update(
            table="training_datasets",
            columns=[
                "dataset_id",
                "bq_table",
                "date_range_start",
                "date_range_end",
                "num_groups",
                "num_rows",
                "positive_rate",
                "created_at",
            ],
            values=[
                (
                    run_id,
                    destination_table,
                    stats.date_range_start,
                    stats.date_range_end,
                    int(stats.num_groups or 0),
                    int(stats.num_rows or 0),
                    float(stats.positive_rate or 0.0),
                    spanner.COMMIT_TIMESTAMP,
                )
            ],
        )

    database.run_in_transaction(_register)
    return destination_table
