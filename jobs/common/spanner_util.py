"""Spanner connection helpers for batch jobs."""

from __future__ import annotations

import argparse
import os

from google.cloud import spanner
from google.cloud.spanner_v1.database import Database


def add_spanner_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project_id",
        default=os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT"),
        help="GCP project ID.",
    )
    parser.add_argument(
        "--instance",
        default=os.environ.get("SPANNER_INSTANCE_ID"),
        help="Spanner instance ID.",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("SPANNER_DATABASE_ID"),
        help="Spanner database ID.",
    )


def resolve_database(args: argparse.Namespace) -> Database:
    if not args.project_id:
        raise ValueError("Missing GCP project. Pass --project_id or set PROJECT_ID.")
    if not args.instance:
        raise ValueError("Missing Spanner instance. Pass --instance or set SPANNER_INSTANCE_ID.")
    if not args.database:
        raise ValueError("Missing Spanner database. Pass --database or set SPANNER_DATABASE_ID.")

    client = spanner.Client(project=args.project_id)
    return client.instance(args.instance).database(args.database)
