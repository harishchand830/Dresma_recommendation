#!/usr/bin/env python3
"""Migrate rows from brand_references into reference_images."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import TYPE_CHECKING, Any

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner

if TYPE_CHECKING:
    from google.cloud.spanner_v1.database import Database

logger = logging.getLogger(__name__)

READ_BATCH_SIZE = 200
WRITE_CHUNK_SIZE = 50

FETCH_QUERY = """
SELECT
  id,
  image_url,
  platform,
  bg_remove_url_embeddings,
  image_url_embeddings,
  likes,
  comments,
  created_at,
  updated_at
FROM brand_references
WHERE id > @last_id
ORDER BY id
LIMIT @limit
"""

REFERENCE_IMAGE_COLUMNS = [
    "image_id",
    "image_url",
    "platform",
    "foreground_embedding",
    "full_image_embedding",
    "likes",
    "comments",
    "published_at",
    "ingested_at",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy rows from brand_references into reference_images, mapping "
            "legacy embedding columns to the new schema."
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


def map_row(row: tuple[Any, ...]) -> tuple[Any, ...]:
    (
        image_id,
        image_url,
        platform,
        foreground_embedding,
        full_image_embedding,
        likes,
        comments,
        published_at,
        updated_at,
    ) = row

    ingested_at = updated_at if updated_at is not None else spanner.COMMIT_TIMESTAMP

    return (
        image_id,
        image_url,
        platform,
        foreground_embedding,
        full_image_embedding,
        0 if likes is None else likes,
        0 if comments is None else comments,
        published_at,
        ingested_at,
    )


def fetch_batch(
    database: Database,
    last_id: str,
    limit: int,
) -> list[tuple[Any, ...]]:
    with database.snapshot() as snapshot:
        results = snapshot.execute_sql(
            FETCH_QUERY,
            params={"last_id": last_id, "limit": limit},
            param_types={
                "last_id": spanner.param_types.STRING,
                "limit": spanner.param_types.INT64,
            },
        )
        return [map_row(row) for row in results]


def write_chunk(database: Database, rows: list[tuple[Any, ...]]) -> None:
    def _write(transaction, chunk_rows: list[tuple[Any, ...]]) -> None:
        transaction.insert_or_update(
            table="reference_images",
            columns=REFERENCE_IMAGE_COLUMNS,
            values=chunk_rows,
        )

    database.run_in_transaction(_write, rows)


def chunked(
    items: list[tuple[Any, ...]],
    size: int,
) -> list[list[tuple[Any, ...]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def migrate(database: Database) -> int:
    migrated = 0
    last_id = ""

    while True:
        batch = fetch_batch(database, last_id=last_id, limit=READ_BATCH_SIZE)
        if not batch:
            break

        for chunk in chunked(batch, WRITE_CHUNK_SIZE):
            write_chunk(database, chunk)
            migrated += len(chunk)
            logger.info("Migrated %d rows...", migrated)

        last_id = batch[-1][0]

    return migrated


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    args = parse_args()
    database = get_database(args.project_id, args.instance_id, args.database_id)

    try:
        total = migrate(database)
    except GoogleAPIError as exc:
        logger.error("Migration failed: %s", exc)
        return 1

    logger.info("Migration complete: %d rows migrated", total)
    print(f"Migrated {total} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
