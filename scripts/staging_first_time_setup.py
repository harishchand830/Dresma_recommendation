#!/usr/bin/env python3
"""First-time staging bootstrap for heuristic recommendation testing.

Reads directly from ``brand_references`` (images only — videos excluded).

Engagement velocity / trend_score need a **baseline snapshot** and a **later**
brand_references state that differs from that snapshot. Running snapshot and
signal computation back-to-back in one command sets velocity and trend to 0.

Recommended two-day workflow (company laptop):

  # Day A — baseline snapshot (after recluster, or alone)
  python scripts/staging_first_time_setup.py --skip-backfill \\
    --skip-reclustering --snapshot-only

  # Day B — bump engagement, recompute signals (NO new snapshot)
  python scripts/staging_first_time_setup.py --skip-backfill \\
    --skip-reclustering --refresh-reference-images --recompute-signals

  # Heuristic test
  python scripts/staging_heuristic_test.py --input scripts/staging/my_test.json \\
    --retrieval-timeout 5.0

  # Day B — recompute only (reference already refreshed; skip --refresh-reference-images)
  python scripts/staging_first_time_setup.py --skip-backfill \\
    --skip-reclustering --recompute-signals

First-time full setup (recluster → snapshot → signals) still works
for populating tables; expect velocity/trend = 0 until Day B recompute.

Prerequisites:
  - brand_references populated with image records (image_type != 'video')
  - cluster_id column exists on brand_references (added by reclustering job)
  - .env has PROJECT_ID, SPANNER_INSTANCE_ID, SPANNER_DATABASE_ID

Auth: uses ADC from ``gcloud auth application-default login``.
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import subprocess
import sys
from datetime import date
from pathlib import Path

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from jobs.common.spanner_util import add_spanner_args, resolve_database

logger = logging.getLogger(__name__)

_SETUP_STEPS = (
    "backfill image_url_embeddings on brand_references (optional)",
    "recluster brand_references → clusters",
    "engagement snapshot → image_engagement_history",
    "signal computation → image_signals",
    "cluster trends → cluster_trends",
)


def _load_dotenv_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_spanner_args(parser)
    parser.add_argument(
        "--skip-backfill",
        action="store_true",
        help="Skip backfill_full_image_embedding on brand_references (recommended when embeddings exist).",
    )
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help=argparse.SUPPRESS,  # Deprecated: migration no longer needed (using brand_references directly).
    )
    parser.add_argument(
        "--skip-reclustering",
        action="store_true",
        help="Skip reclustering (use with --snapshot-only or --recompute-signals).",
    )
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help=(
            "Day A: write engagement baseline to image_engagement_history only. "
            "Do not run signal computation in the same invocation."
        ),
    )
    parser.add_argument(
        "--recompute-signals",
        action="store_true",
        help=(
            "Day B: run signal computation + cluster trends only. "
            "Does not take a new engagement snapshot."
        ),
    )
    parser.add_argument(
        "--start-from-engagement",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--refresh-reference-images",
        action="store_true",
        help=(
            "Bump likes/comments on brand_references before the pipeline. "
            "Implies --recompute-signals (never pairs with a new snapshot)."
        ),
    )
    parser.add_argument(
        "--num-clusters",
        type=int,
        default=32,
        help="K for reclustering job.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit images for reclustering (e.g. 30000).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned steps without executing.",
    )
    parser.add_argument(
        "--as_of_date",
        type=str,
        default=None,
        help="Partition date for signal + cluster-trends jobs (YYYY-MM-DD). Defaults to today.",
    )
    return parser.parse_args()


def _resolve_pipeline_mode(args: argparse.Namespace) -> str:
    """Return one of: full | snapshot_only | recompute_signals."""
    if args.refresh_reference_images:
        return "recompute_signals"
    if args.recompute_signals:
        return "recompute_signals"
    if args.snapshot_only:
        return "snapshot_only"
    if args.start_from_engagement:
        logger.warning(
            "--start-from-engagement is deprecated (snapshot+signals zeros velocity). "
            "Use --snapshot-only for Day A, then --recompute-signals for Day B."
        )
        return "snapshot_only"
    if args.skip_reclustering:
        return "recompute_signals"
    return "full"


def verify_adc(database: spanner.Database) -> bool:
    print("\n=== Step 0: Verify GCP auth (Application Default Credentials) ===\n")
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("  GOOGLE_APPLICATION_CREDENTIALS is set — using that key file.\n")
    else:
        print(
            "  No GOOGLE_APPLICATION_CREDENTIALS — using gcloud ADC.\n"
            "  Expected: gcloud auth application-default login\n"
        )
    try:
        with database.snapshot() as snapshot:
            snapshot.execute_sql("SELECT 1")
        print("  Spanner connection: OK\n")
        return True
    except GoogleAPIError as exc:
        print(f"  Spanner connection: FAILED\n  {exc}\n")
        return False


def _count(database: spanner.Database, query: str) -> int | None:
    try:
        with database.snapshot() as snapshot:
            rows = list(snapshot.execute_sql(query))
        return int(rows[0][0]) if rows else 0
    except GoogleAPIError:
        return None


def print_pre_state(database: spanner.Database) -> None:
    print("=== Current table state (before setup) ===\n")
    checks = {
        "brand_references": "SELECT COUNT(*) FROM brand_references",
        "brand_references (images only)": "SELECT COUNT(*) FROM brand_references WHERE image_type IS NULL OR image_type != 'video'",
        "clusters": "SELECT COUNT(*) FROM clusters",
        "image_engagement_history": "SELECT COUNT(*) FROM image_engagement_history",
        "image_signals": "SELECT COUNT(*) FROM image_signals",
        "cluster_trends": "SELECT COUNT(*) FROM cluster_trends",
    }
    for name, query in checks.items():
        count = _count(database, query)
        label = "TABLE MISSING — apply migrations 001-005 first" if count is None else count
        print(f"  {name:36} {label}")
    print()


def print_post_state(database: spanner.Database, mode: str) -> None:
    print("\n=== Table state (after setup) ===\n")
    checks = {
        "brand_references (images)": "SELECT COUNT(*) FROM brand_references WHERE image_type IS NULL OR image_type != 'video'",
        "brand_refs with fg embedding": (
            "SELECT COUNT(*) FROM brand_references WHERE bg_remove_url_embeddings IS NOT NULL AND (image_type IS NULL OR image_type != 'video')"
        ),
        "brand_refs with full embedding": (
            "SELECT COUNT(*) FROM brand_references WHERE image_url_embeddings IS NOT NULL AND (image_type IS NULL OR image_type != 'video')"
        ),
        "brand_refs clustered": (
            "SELECT COUNT(*) FROM brand_references WHERE cluster_id IS NOT NULL AND (image_type IS NULL OR image_type != 'video')"
        ),
        "clusters": "SELECT COUNT(*) FROM clusters",
        "image_engagement_history": "SELECT COUNT(*) FROM image_engagement_history",
        "image_signals": "SELECT COUNT(*) FROM image_signals",
        "cluster_trends": "SELECT COUNT(*) FROM cluster_trends",
    }
    for name, query in checks.items():
        count = _count(database, query)
        print(f"  {name:36} {count if count is not None else 'TABLE MISSING'}")

    if mode == "snapshot_only":
        print(
            "\n  Baseline snapshot written. Next (Day B, after engagement changes):\n"
            "    python scripts/staging_first_time_setup.py --skip-backfill \\\n"
            "      --skip-reclustering --refresh-reference-images --recompute-signals\n"
        )
    elif mode == "recompute_signals":
        print(
            "\n  Signals recomputed. Verify velocity/trend in Spanner, then run heuristic test:\n"
            "    python scripts/staging_heuristic_test.py --input scripts/staging/my_test.json \\\n"
            "      --retrieval-timeout 5.0\n"
            "\n  If velocity/trend are still 0, delete same-day duplicate snapshots:\n"
            "    DELETE FROM image_engagement_history WHERE DATE(snapshot_at) = CURRENT_DATE();\n"
            "    then re-run with --recompute-signals only.\n"
        )
    elif mode == "full":
        print(
            "\n  NOTE: velocity/trend may be 0 until Day B recompute (see script docstring).\n"
        )
    print()


def _run(cmd: list[str], dry_run: bool) -> None:
    print(f"\n  $ {' '.join(cmd)}")
    if dry_run:
        return
    result = subprocess.run(cmd, cwd=_REPO_ROOT, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")


def _timestamp_column(database: spanner.Database) -> str:
    """Return the timestamp column name used in brand_references for engagement refresh."""
    # brand_references uses 'updatedAt' as the engagement timestamp
    return "updatedAt"


def _refresh_brand_references(database: spanner.Database, dry_run: bool = False) -> None:
    timestamp_column = _timestamp_column(database)
    print(
        f"\n=== Refreshing brand_references engagement ({timestamp_column}) ===\n"
    )

    with database.snapshot() as snapshot:
        rows = list(snapshot.execute_sql(
            "SELECT id, likes, comments FROM brand_references "
            "WHERE image_type IS NULL OR image_type != 'video'"
        ))

    if not rows:
        print("  No brand_references image rows found; skipping refresh.")
        return

    updated_values: list[tuple[str, int, int, object]] = []
    for image_id, likes, comments in rows:
        likes = int(likes or 0)
        comments = int(comments or 0)
        rng = random.Random(f"{image_id}-{likes}-{comments}")

        if likes <= 0:
            new_likes = rng.randint(1, 8)
        else:
            new_likes = likes + max(1, min(50, int(likes * rng.uniform(0.05, 0.15))))

        if comments <= 0:
            new_comments = rng.randint(1, max(1, min(5, new_likes // 5)))
        else:
            new_comments = comments + max(1, min(15, int(comments * rng.uniform(0.10, 0.25))))

        if new_comments > new_likes:
            new_comments = min(new_likes, new_comments)
        if new_likes == likes and new_comments == comments:
            new_likes += 1
            new_comments = max(new_comments, 1)

        updated_values.append((image_id, new_likes, new_comments, spanner.COMMIT_TIMESTAMP))

    if dry_run:
        print(f"  Would update {len(updated_values)} rows.")
        return

    batch_size = 200

    def _write(transaction: spanner.Transaction, batch: list[tuple]) -> None:
        transaction.update(
            table="brand_references",
            columns=["id", "likes", "comments", timestamp_column],
            values=batch,
        )

    total = 0
    for offset in range(0, len(updated_values), batch_size):
        batch = updated_values[offset : offset + batch_size]
        database.run_in_transaction(_write, batch)
        total += len(batch)
        print(f"  Updated {total}/{len(updated_values)} rows...")
    print(f"  brand_references refresh complete: {total} rows.")


def _signal_date_args(as_of_date: str | None) -> list[str]:
    partition = as_of_date or date.today().isoformat()
    return ["--as_of_date", partition]


def run_setup(args: argparse.Namespace) -> None:
    mode = _resolve_pipeline_mode(args)
    spanner_flags = [
        "--project_id",
        args.project_id,
        "--instance",
        args.instance,
        "--database",
        args.database,
    ]
    migrate_flags = [
        "--project_id",
        args.project_id,
        "--instance_id",
        args.instance,
        "--database_id",
        args.database,
    ]
    signal_date_flags = _signal_date_args(args.as_of_date)

    reclustering_cmd = [
        sys.executable,
        "-m",
        "jobs.reclustering.main",
        *spanner_flags,
        "--num_clusters",
        str(args.num_clusters),
    ]
    if args.limit:
        reclustering_cmd.extend(["--limit", str(args.limit)])

    snapshot_cmd = [sys.executable, "-m", "jobs.engagement_snapshot.main", *spanner_flags]
    signals_cmd = [
        sys.executable,
        "-m",
        "jobs.signal_computation.main",
        *spanner_flags,
        *signal_date_flags,
    ]
    trends_cmd = [
        sys.executable,
        "-m",
        "jobs.cluster_trends.main",
        *spanner_flags,
        *signal_date_flags,
    ]

    steps: list[tuple[str, list[str]]] = []

    if mode == "full":
        if not args.skip_backfill:
            steps.append(
                (
                    _SETUP_STEPS[0],
                    [
                        sys.executable,
                        str(_REPO_ROOT / "scripts" / "backfill_full_image_embedding.py"),
                        *migrate_flags,
                    ],
                )
            )
        steps.extend(
            [
                (_SETUP_STEPS[1], reclustering_cmd),
                (_SETUP_STEPS[2], snapshot_cmd),
                (_SETUP_STEPS[3], signals_cmd),
                (_SETUP_STEPS[4], trends_cmd),
            ]
        )
    elif mode == "snapshot_only":
        if not args.skip_reclustering:
            steps.append((_SETUP_STEPS[1], reclustering_cmd))
        steps.append((_SETUP_STEPS[2], snapshot_cmd))
    elif mode == "recompute_signals":
        steps.extend(
            [
                (_SETUP_STEPS[3], signals_cmd),
                (_SETUP_STEPS[4], trends_cmd),
            ]
        )

    print(f"\n=== Running staging setup (mode={mode}) ===\n")
    if args.refresh_reference_images and mode == "recompute_signals":
        print(
            "  refresh-reference-images: skipping engagement snapshot so baseline "
            "history is not overwritten.\n"
        )
    if args.limit and not args.skip_reclustering and mode in ("full", "snapshot_only"):
        print(f"  Reclustering limited to {args.limit} images.\n")

    for index, (label, cmd) in enumerate(steps, start=1):
        print(f"--- Step {index}: {label} ---")
        _run(cmd, args.dry_run)
    print("\n  Setup pipeline finished.\n")


def main() -> int:
    _load_dotenv_file(_REPO_ROOT / ".env")
    args = parse_args()
    mode = _resolve_pipeline_mode(args)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    try:
        database = resolve_database(args)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    if not verify_adc(database):
        return 1

    print_pre_state(database)

    brand_count = _count(database, "SELECT COUNT(*) FROM brand_references WHERE image_type IS NULL OR image_type != 'video'")
    if brand_count is None:
        logger.error("brand_references table not found.")
        return 1
    if brand_count == 0:
        logger.error("brand_references has no image rows — ensure it is populated.")
        return 1
    print(f"  brand_references (images) has {brand_count} rows.\n")

    if args.skip_backfill:
        print(
            "  --skip-backfill: assuming brand_references.image_url_embeddings "
            "is populated (recommended).\n"
        )
    elif mode == "full":
        print(
            "  WARNING: backfill generates RANDOM full embeddings for NULL rows.\n"
            "  Prefer --skip-backfill if brand_references has image_url_embeddings.\n"
        )

    if args.refresh_reference_images:
        _refresh_brand_references(database, args.dry_run)

    try:
        run_setup(args)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    if not args.dry_run:
        print_post_state(database, mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
