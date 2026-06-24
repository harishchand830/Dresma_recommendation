"""Spanner repository for ``training_datasets`` registry rows."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from google.cloud import spanner
from google.cloud.spanner_v1.database import Database

from dresma_rec.storage.spanner.client import get_spanner_database


class TrainingDatasetsRepository:
    """Writes materialized training dataset metadata to Spanner."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def register_dataset(
        self,
        dataset_id: str,
        bq_table: str,
        date_range_start: date | None,
        date_range_end: date | None,
        num_groups: int,
        num_rows: int,
        positive_rate: float,
    ) -> None:
        def _insert(transaction: spanner.Transaction) -> None:
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
                        dataset_id,
                        bq_table,
                        date_range_start,
                        date_range_end,
                        num_groups,
                        num_rows,
                        positive_rate,
                        spanner.COMMIT_TIMESTAMP,
                    )
                ],
            )

        self._database.run_in_transaction(_insert)


@lru_cache
def get_training_datasets_repository() -> TrainingDatasetsRepository:
    return TrainingDatasetsRepository(get_spanner_database())
