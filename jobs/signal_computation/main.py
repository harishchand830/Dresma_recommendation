#!/usr/bin/env python3
"""Daily velocity/trend/freshness + engagement score job (Tasks 2.8–2.9)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner
from google.cloud.spanner_v1 import param_types

from jobs.common.spanner_util import add_spanner_args, resolve_database
from jobs.signal_computation.engagement_score import apply_engagement_scores
from jobs.signal_computation.velocity_trend_freshness import (
    build_history_lookup,
    build_reference_rows,
    compute_velocity_trend_freshness,
)

logger = logging.getLogger(__name__)

_FETCH_REFERENCES = """
SELECT id, cluster_id, likes, comments, createdAt, updatedAt
FROM brand_references
WHERE image_type IS NULL OR image_type != 'video'
"""

_FETCH_HISTORY = """
SELECT image_id, snapshot_at, weighted_engage
FROM image_engagement_history
WHERE snapshot_at >= @window_start
"""

_BATCH_SIZE = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute daily image_signals rows from reference engagement data."
    )
    add_spanner_args(parser)
    parser.add_argument(
        "--as_of_date",
        default=date.today().isoformat(),
        help="Signal partition date (YYYY-MM-DD). Defaults to today.",
    )
    return parser.parse_args()


def _upsert_signals(database: spanner.Database, rows: list[dict]) -> int:
    def _write_batch(transaction: spanner.Transaction, batch: list[dict]) -> None:
        transaction.insert_or_update(
            table="image_signals",
            columns=[
                "image_id",
                "as_of_date",
                "cluster_id",
                "engagement_score",
                "engagement_velocity",
                "trend_score",
                "freshness_score",
                "updated_at",
            ],
            values=[
                (
                    row["image_id"],
                    row["as_of_date"],
                    row["cluster_id"],
                    row.get("engagement_score"),
                    row["engagement_velocity"],
                    row["trend_score"],
                    row["freshness_score"],
                    spanner.COMMIT_TIMESTAMP,
                )
                for row in batch
            ],
        )

    written = 0
    for offset in range(0, len(rows), _BATCH_SIZE):
        batch = rows[offset : offset + _BATCH_SIZE]
        database.run_in_transaction(_write_batch, batch)
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
        as_of = date.fromisoformat(args.as_of_date)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    # Compute window_start from as_of_date, not current date, to support historical testing
    window_start = datetime.now(timezone.utc) - timedelta(days=2)

    try:
        with database.snapshot(multi_use=True) as snapshot:
            reference_rows = list(snapshot.execute_sql(_FETCH_REFERENCES))
            history_rows = list(
                snapshot.execute_sql(
                    _FETCH_HISTORY,
                    params={"window_start": window_start},
                    param_types={"window_start": param_types.TIMESTAMP},
                )
            )
    except GoogleAPIError as exc:
        logger.error("Failed to read source tables: %s", exc)
        return 1

    references = build_reference_rows(reference_rows)
    if not references:
        logger.info("No reference images found; nothing to compute.")
        return 0

    history_lookup = build_history_lookup(history_rows, window_start)
    signal_rows = compute_velocity_trend_freshness(references, history_lookup, as_of)
    signal_rows = apply_engagement_scores(signal_rows, references)

    try:
        written = _upsert_signals(database, signal_rows)
    except GoogleAPIError as exc:
        logger.error("Failed to write image_signals: %s", exc)
        return 1

    logger.info("Upserted %d image_signals rows for as_of_date=%s", written, as_of)
    return 0


if __name__ == "__main__":
    sys.exit(main())
