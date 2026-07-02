#!/usr/bin/env python3
"""Hourly engagement snapshot job (RFC Section 6.6, Task 2.7)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner

from jobs.common.engagement import weighted_engagement
from jobs.common.spanner_util import add_spanner_args, resolve_database

logger = logging.getLogger(__name__)

_FETCH_REFERENCE_IMAGES = """
SELECT id, likes, comments
FROM brand_references
WHERE image_type IS NULL OR image_type != 'video'
"""

_BATCH_SIZE = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Snapshot reference image engagement into image_engagement_history."
    )
    add_spanner_args(parser)
    return parser.parse_args()


def _write_snapshots(
    database: spanner.Database,
    snapshot_at: datetime,
    rows: list[tuple[str, datetime, int, int, float]],
) -> int:
    def _insert_batch(transaction: spanner.Transaction, batch: list[tuple]) -> None:
        transaction.insert(
            table="image_engagement_history",
            columns=[
                "image_id",
                "snapshot_at",
                "likes",
                "comments",
                "weighted_engage",
            ],
            values=batch,
        )

    written = 0
    for offset in range(0, len(rows), _BATCH_SIZE):
        batch = rows[offset : offset + _BATCH_SIZE]
        database.run_in_transaction(_insert_batch, batch)
        written += len(batch)
    return written


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    args = parse_args()
    try:
        database = resolve_database(args)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    snapshot_at = datetime.now(timezone.utc)

    try:
        with database.snapshot() as snapshot:
            reference_rows = list(snapshot.execute_sql(_FETCH_REFERENCE_IMAGES))
    except GoogleAPIError as exc:
        logger.error("Failed to read brand_references: %s", exc)
        return 1

    if not reference_rows:
        logger.info("No brand_references images found; nothing to snapshot.")
        return 0

    rows = [
        (
            image_id,
            snapshot_at,
            int(likes or 0),
            int(comments or 0),
            weighted_engagement(int(likes or 0), int(comments or 0)),
        )
        for image_id, likes, comments in reference_rows
    ]

    try:
        written = _write_snapshots(database, snapshot_at, rows)
    except GoogleAPIError as exc:
        logger.error("Failed to write image_engagement_history: %s", exc)
        return 1

    logger.info("Wrote %d engagement snapshots at %s", written, snapshot_at.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
