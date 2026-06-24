#!/usr/bin/env python3
"""Promote, canary, archive, or stage models in Spanner ``model_metadata``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner
from google.cloud.spanner_v1 import param_types

logger = logging.getLogger(__name__)

_STATUS_CHOICES = ("STAGING", "CANARY", "PRODUCTION", "ARCHIVED")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update model_metadata status for promotion and rollback."
    )
    parser.add_argument(
        "--project_id",
        default=os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT"),
        help="GCP project ID (default: PROJECT_ID or GOOGLE_CLOUD_PROJECT env var).",
    )
    parser.add_argument("--instance", required=True, help="Spanner instance ID.")
    parser.add_argument("--database", required=True, help="Spanner database ID.")
    parser.add_argument(
        "--version",
        required=True,
        help="Target model_version (e.g. xgb-run123).",
    )
    parser.add_argument(
        "--status",
        required=True,
        choices=_STATUS_CHOICES,
        help="New status for the target model version.",
    )
    return parser.parse_args()


def _archive_existing(
    transaction: spanner.Transaction, status_to_archive: str
) -> None:
    transaction.execute_update(
        f"UPDATE model_metadata SET status = 'ARCHIVED' WHERE status = @status",
        params={"status": status_to_archive},
        param_types={"status": param_types.STRING},
    )


def _promote_model(
    database: spanner.Database, model_version: str, new_status: str
) -> int:
    def update_transaction(transaction: spanner.Transaction) -> int:
        if new_status == "CANARY":
            _archive_existing(transaction, "CANARY")
        elif new_status == "PRODUCTION":
            _archive_existing(transaction, "PRODUCTION")

        return transaction.execute_update(
            """
            UPDATE model_metadata
            SET status = @status
            WHERE model_version = @version
            """,
            params={"status": new_status, "version": model_version},
            param_types={
                "status": param_types.STRING,
                "version": param_types.STRING,
            },
        )

    return database.run_in_transaction(update_transaction)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    args = parse_args()
    if not args.project_id:
        logger.error(
            "Missing GCP project. Pass --project_id or set PROJECT_ID / "
            "GOOGLE_CLOUD_PROJECT."
        )
        return 1

    client = spanner.Client(project=args.project_id)
    database = client.instance(args.instance).database(args.database)

    try:
        rows_updated = _promote_model(database, args.version, args.status)
    except GoogleAPIError as exc:
        logger.error("Spanner update failed: %s", exc)
        return 1

    if rows_updated == 0:
        logger.error(
            "No model_metadata row updated for model_version=%s",
            args.version,
        )
        return 1

    logger.info(
        "Updated model_version=%s to status=%s (%s row(s) affected)",
        args.version,
        args.status,
        rows_updated,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
