#!/usr/bin/env python3
"""Backfill missing image_url_embeddings vectors on brand_references."""

from __future__ import annotations

import argparse
import logging
import random
import sys
from typing import TYPE_CHECKING

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner

if TYPE_CHECKING:
    from google.cloud.spanner_v1.database import Database

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1408
BATCH_SIZE = 200

FETCH_NULL_QUERY = """
SELECT id
FROM brand_references
WHERE image_url_embeddings IS NULL
  AND (image_type IS NULL OR image_type != 'video')
ORDER BY id
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill brand_references.image_url_embeddings for rows where the "
            "column is NULL."
        )
    )
    parser.add_argument(
        "--project_id",
        required=True,
        help="GCP project ID containing the Spanner instance.",
    )
    parser.add_argument(
        "--instance_id",
        required=True,
        help="Cloud Spanner instance ID.",
    )
    parser.add_argument(
        "--database_id",
        required=True,
        help="Cloud Spanner database ID.",
    )
    return parser.parse_args()


def get_database(project_id: str, instance_id: str, database_id: str) -> Database:
    client = spanner.Client(project=project_id)
    instance = client.instance(instance_id)
    return instance.database(database_id)


def fetch_null_image_ids(database: Database) -> list[str]:
    with database.snapshot() as snapshot:
        results = snapshot.execute_sql(FETCH_NULL_QUERY)
        return [row[0] for row in results]


def generate_dummy_embedding(image_id: str) -> list[float]:
    """Return a mocked 1408-dimensional full-image embedding for one reference row."""
    # TODO: Replace with the real full-image embedding model API call.
    # Fetch image_url (and any required auth) for `image_id`, run the embedding
    # model on the full uncropped image, and return the 1408-d FLOAT32 vector.
    rng = random.Random(image_id)
    return [float(rng.uniform(-1.0, 1.0)) for _ in range(EMBEDDING_DIM)]


def update_batch(database: Database, image_ids: list[str]) -> None:
    rows = [
        (image_id, generate_dummy_embedding(image_id))
        for image_id in image_ids
    ]

    def _write(transaction, batch_rows: list[tuple[str, list[float]]]) -> None:
        transaction.update(
            table="brand_references",
            columns=["id", "image_url_embeddings"],
            values=batch_rows,
        )

    database.run_in_transaction(_write, rows)


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    args = parse_args()
    database = get_database(args.project_id, args.instance_id, args.database_id)

    try:
        image_ids = fetch_null_image_ids(database)
    except GoogleAPIError as exc:
        logger.error("Failed to fetch rows with NULL full_image_embedding: %s", exc)
        return 1

    total = len(image_ids)
    if total == 0:
        logger.info("No rows require backfill; full_image_embedding is populated.")
        print("Updated 0 / 0 rows")
        return 0

    logger.info("Found %d brand_references rows with NULL image_url_embeddings", total)

    updated = 0
    try:
        for batch in chunked(image_ids, BATCH_SIZE):
            update_batch(database, batch)
            updated += len(batch)
            print(f"Updated {updated} / {total} rows")
    except GoogleAPIError as exc:
        logger.error(
            "Backfill failed after updating %d / %d rows: %s",
            updated,
            total,
            exc,
        )
        return 1

    logger.info("Backfill complete: %d / %d rows updated", updated, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
