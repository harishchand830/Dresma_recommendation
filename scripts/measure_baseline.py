#!/usr/bin/env python3
"""Compute baseline proxy metrics from BigQuery `dresma.user_actions` (RFC Section 1.4)."""

from __future__ import annotations

import argparse
import logging
import sys

from google.api_core.exceptions import GoogleAPIError, NotFound
from google.cloud import bigquery

logger = logging.getLogger(__name__)

BASELINE_QUERY = """
WITH filtered_events AS (
  SELECT
    job_id,
    event_type,
    position
  FROM `{table_fqn}`
  WHERE event_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
),

sessions_with_impression AS (
  SELECT DISTINCT job_id
  FROM filtered_events
  WHERE event_type = 'IMPRESSION'
),

sessions_with_selection AS (
  SELECT DISTINCT job_id
  FROM filtered_events
  WHERE event_type = 'SELECTION'
),

session_selection_rank AS (
  SELECT
    job_id,
    MIN(position) AS best_selection_position
  FROM filtered_events
  WHERE event_type = 'SELECTION'
    AND position IS NOT NULL
  GROUP BY job_id
),

aggregates AS (
  SELECT
    (SELECT COUNT(*) FROM sessions_with_impression) AS total_sessions,
    (SELECT COUNT(*) FROM sessions_with_selection) AS sessions_with_selection,
    (
      SELECT COUNT(*)
      FROM session_selection_rank AS sr
      INNER JOIN sessions_with_impression AS si USING (job_id)
      WHERE sr.best_selection_position <= 3
    ) AS sessions_with_selection_at_3,
    (
      SELECT AVG(1.0 / sr.best_selection_position)
      FROM session_selection_rank AS sr
      INNER JOIN sessions_with_selection AS ss USING (job_id)
    ) AS mrr
)

SELECT
  total_sessions,
  sessions_with_selection,
  SAFE_DIVIDE(sessions_with_selection, total_sessions) AS selection_rate,
  SAFE_DIVIDE(sessions_with_selection_at_3, total_sessions) AS selection_at_3,
  mrr
FROM aggregates
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure baseline Selection@3, selection rate, and MRR from "
            "BigQuery user_actions."
        )
    )
    parser.add_argument(
        "--project_id",
        required=True,
        help="GCP project ID containing the dresma.user_actions table.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Trailing window in days for event_time filtering (default: 7).",
    )
    return parser.parse_args()


def build_query(project_id: str) -> str:
    table_fqn = f"{project_id}.dresma.user_actions"
    return BASELINE_QUERY.format(table_fqn=table_fqn)


def format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def format_mrr(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def print_results(project_id: str, days: int, row: bigquery.table.Row) -> None:
    table_fqn = f"{project_id}.dresma.user_actions"
    print()
    print("Dresma Baseline Metrics")
    print("=" * 40)
    print(f"Project:                 {project_id}")
    print(f"Table:                   {table_fqn}")
    print(f"Trailing window (days):  {days}")
    print("-" * 40)
    print(f"Total sessions:          {row.total_sessions}")
    print(f"Sessions w/ selection:   {row.sessions_with_selection}")
    print(f"Selection rate:          {format_rate(row.selection_rate)}")
    print(f"Selection@3:             {format_rate(row.selection_at_3)}")
    print(f"MRR:                     {format_mrr(row.mrr)}")
    print()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    args = parse_args()
    if args.days <= 0:
        logger.error("--days must be a positive integer.")
        return 1

    client = bigquery.Client(project=args.project_id)
    query = build_query(args.project_id)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", args.days),
        ]
    )

    try:
        result_rows = list(client.query(query, job_config=job_config).result())
    except NotFound as exc:
        logger.error(
            "BigQuery dataset or table not found for %s.dresma.user_actions: %s",
            args.project_id,
            exc,
        )
        return 1
    except GoogleAPIError as exc:
        logger.error("BigQuery query failed: %s", exc)
        return 1

    if not result_rows:
        logger.error("BigQuery query returned no rows.")
        return 1

    print_results(args.project_id, args.days, result_rows[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
