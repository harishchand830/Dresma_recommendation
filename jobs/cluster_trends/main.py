#!/usr/bin/env python3
"""Daily cluster trend aggregation job (RFC Section 6.5, Task 2.10)."""

from __future__ import annotations

import argparse
import logging
import math
import sys
from datetime import date
from statistics import fmean

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner
from google.cloud.spanner_v1 import param_types

from jobs.common.spanner_util import add_spanner_args, resolve_database

logger = logging.getLogger(__name__)

_FETCH_SIGNALS = """
SELECT cluster_id, engagement_velocity, trend_score
FROM image_signals
WHERE as_of_date = @as_of_date
  AND cluster_id IS NOT NULL
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate per-cluster trend scores into cluster_trends."
    )
    add_spanner_args(parser)
    parser.add_argument(
        "--as_of_date",
        default=date.today().isoformat(),
        help="Signal partition date (YYYY-MM-DD). Defaults to today.",
    )
    return parser.parse_args()


def _cluster_trend_from_rows(rows: list[tuple[float, float]]) -> float:
    if not rows:
        return 0.0
    rows_by_velocity = sorted(rows, key=lambda item: item[0], reverse=True)
    top_count = max(1, math.ceil(len(rows_by_velocity) * 0.10))
    top_trends = [trend for _, trend in rows_by_velocity[:top_count]]
    return float(fmean(top_trends))


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

    try:
        with database.snapshot() as snapshot:
            signal_rows = list(
                snapshot.execute_sql(
                    _FETCH_SIGNALS,
                    params={"as_of_date": as_of},
                    param_types={"as_of_date": param_types.DATE},
                )
            )
    except GoogleAPIError as exc:
        logger.error("Failed to read image_signals: %s", exc)
        return 1

    grouped: dict[int, list[tuple[float, float]]] = {}
    for cluster_id, velocity, trend_score in signal_rows:
        grouped.setdefault(int(cluster_id), []).append(
            (float(velocity or 0.0), float(trend_score or 0.0))
        )

    if not grouped:
        logger.info("No image_signals rows for as_of_date=%s", as_of)
        return 0

    values = [
        (cluster_id, as_of, _cluster_trend_from_rows(cluster_rows))
        for cluster_id, cluster_rows in grouped.items()
    ]

    def _write(transaction: spanner.Transaction) -> None:
        transaction.insert_or_update(
            table="cluster_trends",
            columns=["cluster_id", "as_of_date", "cluster_trend"],
            values=values,
        )

    try:
        database.run_in_transaction(_write)
    except GoogleAPIError as exc:
        logger.error("Failed to write cluster_trends: %s", exc)
        return 1

    logger.info("Wrote %d cluster_trends rows for as_of_date=%s", len(values), as_of)
    return 0


if __name__ == "__main__":
    sys.exit(main())
