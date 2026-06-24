#!/usr/bin/env python3
"""Rollback helper for model promotion (RFC Section 12.4, Task 3.14)."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rollback production by promoting the most recently archived model, "
            "or a specific model version."
        )
    )
    parser.add_argument(
        "--project_id",
        default=os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT"),
        help="GCP project ID.",
    )
    parser.add_argument("--instance", required=True, help="Spanner instance ID.")
    parser.add_argument("--database", required=True, help="Spanner database ID.")
    parser.add_argument(
        "--version",
        help="Explicit model_version to promote to PRODUCTION. "
        "If omitted, selects the latest ARCHIVED model by trained_at.",
    )
    return parser.parse_args()


def _find_rollback_version(database: spanner.Database) -> str | None:
    with database.snapshot() as snapshot:
        rows = list(
            snapshot.execute_sql(
                """
                SELECT model_version
                FROM model_metadata
                WHERE status = 'ARCHIVED'
                ORDER BY trained_at DESC
                LIMIT 1
                """
            )
        )
    if not rows:
        return None
    return rows[0][0]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    args = parse_args()
    if not args.project_id:
        logger.error("Missing GCP project. Set PROJECT_ID or pass --project_id.")
        return 1

    client = spanner.Client(project=args.project_id)
    database = client.instance(args.instance).database(args.database)

    target_version = args.version
    if not target_version:
        try:
            target_version = _find_rollback_version(database)
        except GoogleAPIError as exc:
            logger.error("Failed to look up rollback candidate: %s", exc)
            return 1

    if not target_version:
        logger.error("No ARCHIVED model found to roll back to.")
        return 1

    manage_models = os.path.join(os.path.dirname(__file__), "manage_models.py")
    command = [
        sys.executable,
        manage_models,
        "--project_id",
        args.project_id,
        "--instance",
        args.instance,
        "--database",
        args.database,
        "--version",
        target_version,
        "--status",
        "PRODUCTION",
    ]

    logger.info("Rolling back to model_version=%s", target_version)
    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
