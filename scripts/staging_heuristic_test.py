#!/usr/bin/env python3
"""Staging test runner for the heuristic recommendation path (Phase 2).

Runs the real pipeline against staging Spanner — no dummy mocks:
  1. Optional prerequisite checks / batch job setup
  2. Cluster assignment (nearest centroid)
  3. Five-channel retrieval (C1–C5)
  4. Heuristic ranker (cold_start_heuristic)

Skips: XGBoost routing, recommendation_sessions, recommendation_events,
user_actions, Pub/Sub, and training pipelines.

Usage:
  # First-time (empty tables) — run on company laptop:
  python scripts/staging_first_time_setup.py --skip-backfill

  # Then test with your upload:
  python scripts/staging_heuristic_test.py --input scripts/staging/my_test.json

  # Or combine setup + test in one command:
  python scripts/staging_heuristic_test.py --input scripts/staging/my_test.json --run-setup --skip-backfill
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner
from google.cloud.spanner_v1 import param_types

# Ensure repo root is on sys.path when invoked as a script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dresma_rec.ranking.heuristic import HeuristicRanker
from dresma_rec.retrieval.cluster_assignment import ClusterAssigner
from dresma_rec.retrieval.orchestrator import RetrievalOrchestrator
from dresma_rec.schemas.recommendations import RecommendationRequest, UploadContext
from jobs.common.spanner_util import add_spanner_args, resolve_database

logger = logging.getLogger(__name__)

_PREREQ_QUERIES: dict[str, str] = {
    "reference_images": "SELECT COUNT(*) FROM reference_images",
    "reference_images_with_fg": (
        "SELECT COUNT(*) FROM reference_images WHERE foreground_embedding IS NOT NULL"
    ),
    "reference_images_with_full": (
        "SELECT COUNT(*) FROM reference_images WHERE full_image_embedding IS NOT NULL"
    ),
    "clusters": "SELECT COUNT(*) FROM clusters",
    "reference_images_clustered": (
        "SELECT COUNT(*) FROM reference_images WHERE cluster_id IS NOT NULL"
    ),
    "image_engagement_history": "SELECT COUNT(*) FROM image_engagement_history",
    "image_signals": "SELECT COUNT(*) FROM image_signals",
    "cluster_trends": "SELECT COUNT(*) FROM cluster_trends",
    "brand_references": "SELECT COUNT(*) FROM brand_references",
}

_MIN_REFERENCE_IMAGES = 10


def _load_dotenv_file(path: Path) -> None:
    """Load KEY=VALUE pairs from .env without overriding existing env vars."""
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


def run_setup_commands(args: argparse.Namespace) -> None:
    print("\n=== Running staging setup pipeline ===\n")
    print("  Tip: for first-time empty tables, prefer scripts/staging_first_time_setup.py\n")
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
    commands: list[list[str]] = [
        [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "migrate_brand_references.py"),
            *migrate_flags,
        ],
    ]
    if not getattr(args, "skip_backfill", False):
        commands.append(
            [
                sys.executable,
                str(_REPO_ROOT / "scripts" / "backfill_full_image_embedding.py"),
                *migrate_flags,
            ]
        )
    num_clusters = str(getattr(args, "num_clusters", 32))
    commands.extend(
        [
            [
                sys.executable,
                "-m",
                "jobs.reclustering.main",
                *spanner_flags,
                "--num_clusters",
                num_clusters,
            ],
            [sys.executable, "-m", "jobs.engagement_snapshot.main", *spanner_flags],
            [sys.executable, "-m", "jobs.signal_computation.main", *spanner_flags],
            [sys.executable, "-m", "jobs.cluster_trends.main", *spanner_flags],
        ]
    )
    for cmd in commands:
        print(f"  $ {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=_REPO_ROOT, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Setup command failed (exit {result.returncode}): {' '.join(cmd)}")
    print("\n  Setup pipeline finished.\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run heuristic recommendation staging test against live Spanner."
    )
    add_spanner_args(parser)
    parser.add_argument(
        "--input",
        help="JSON file with job_id, image_url, embeddings, intent, created_at, top_n.",
    )
    parser.add_argument(
        "--check-prereqs",
        action="store_true",
        help="Only verify staging data prerequisites and exit.",
    )
    parser.add_argument(
        "--run-setup",
        action="store_true",
        help=(
            "Run migrate → recluster → engagement snapshot → "
            "signal computation → cluster trends before the test."
        ),
    )
    parser.add_argument(
        "--skip-backfill",
        action="store_true",
        help="Skip backfill_full_image_embedding during --run-setup (recommended).",
    )
    parser.add_argument(
        "--num-clusters",
        type=int,
        default=32,
        help="K for reclustering when using --run-setup.",
    )
    parser.add_argument(
        "--retrieval-timeout",
        type=float,
        default=5.0,
        help="Deadline in seconds for each retrieval channel (default: 5.0 for local test).",
    )
    parser.add_argument(
        "--insert-uploaded-product",
        action="store_true",
        help="Insert a row into uploaded_products (audit only; not used by ranker).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for ε-exploration slots (default: 42).",
    )
    parser.add_argument(
        "--weight-fg",
        type=float,
        help="Override foreground similarity weight.",
    )
    parser.add_argument(
        "--weight-full",
        type=float,
        help="Override full-image similarity weight.",
    )
    parser.add_argument(
        "--weight-trend",
        type=float,
        help="Override trend score weight.",
    )
    parser.add_argument(
        "--weight-popular",
        type=float,
        help="Override engagement score weight.",
    )
    parser.add_argument(
        "--weight-fresh",
        type=float,
        help="Override freshness score weight.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def load_test_input(path: str) -> dict[str, Any]:
    input_path = Path(path)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with input_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    required = ("job_id", "foreground_embedding", "full_image_embedding")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Input JSON missing required fields: {', '.join(missing)}")

    fg = payload["foreground_embedding"]
    full = payload["full_image_embedding"]
    if len(fg) != 1408:
        raise ValueError(f"foreground_embedding must be 1408-dim, got {len(fg)}")
    if len(full) != 1408:
        raise ValueError(f"full_image_embedding must be 1408-dim, got {len(full)}")

    return payload


def _count_query(database: spanner.Database, query: str) -> int | None:
    try:
        with database.snapshot() as snapshot:
            rows = list(snapshot.execute_sql(query))
        return int(rows[0][0]) if rows else 0
    except GoogleAPIError:
        return None


def check_prerequisites(database: spanner.Database) -> bool:
    print("\n=== Staging prerequisite check ===\n")
    counts: dict[str, int | None] = {}
    for name, query in _PREREQ_QUERIES.items():
        counts[name] = _count_query(database, query)
        value = "TABLE MISSING" if counts[name] is None else counts[name]
        print(f"  {name:32} {value}")

    ok = True
    ref_count = counts.get("reference_images") or 0
    if ref_count < _MIN_REFERENCE_IMAGES:
        print(
            f"\n  FAIL: reference_images has {ref_count} rows "
            f"(need >= {_MIN_REFERENCE_IMAGES}). "
            "Run migrate from brand_references first."
        )
        ok = False

    if (counts.get("clusters") or 0) == 0:
        print("\n  FAIL: clusters table is empty. Run: python -m jobs.reclustering.main")
        ok = False

    if (counts.get("image_signals") or 0) == 0:
        print(
            "\n  FAIL: image_signals is empty — C3/C4/C5 channels need signals.\n"
            "  Run: python scripts/staging_first_time_setup.py --skip-backfill"
        )
        ok = False

    if ok:
        print("\n  Prerequisites OK for heuristic test.\n")
    else:
        print("\n  Fix the failures above before running the test.\n")
    return ok


def insert_uploaded_product(
    database: spanner.Database,
    payload: dict[str, Any],
    assigned_cluster_id: int,
) -> None:
    created_at = payload.get("created_at")
    if created_at is None:
        created_at = spanner.COMMIT_TIMESTAMP
    elif isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

    def _write(transaction: spanner.Transaction) -> None:
        transaction.insert_or_update(
            table="uploaded_products",
            columns=[
                "job_id",
                "image_url",
                "foreground_embedding",
                "full_image_embedding",
                "assigned_cluster_id",
                "intent",
                "created_at",
            ],
            values=[
                (
                    payload["job_id"],
                    payload.get("image_url"),
                    payload["foreground_embedding"],
                    payload["full_image_embedding"],
                    assigned_cluster_id,
                    payload.get("intent"),
                    created_at,
                )
            ],
        )

    database.run_in_transaction(_write)


def _channel_summary(candidates: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        for channel in candidate.get("source_channels", []):
            counts[channel] = counts.get(channel, 0) + 1
    return counts


def _fetch_likes_comments(database: spanner.Database, image_ids: list[str]) -> dict[str, dict]:
    if not image_ids:
        return {}

    sql = (
        "SELECT image_id, likes, comments FROM reference_images "
        "WHERE image_id IN UNNEST(@image_ids)"
    )

    with database.snapshot() as snapshot:
        rows = list(
            snapshot.execute_sql(
                sql,
                params={"image_ids": image_ids},
                param_types={"image_ids": param_types.Array(param_types.STRING)},
            )
        )

    return {
        image_id: {
            "likes": int(likes or 0),
            "comments": int(comments or 0),
        }
        for image_id, likes, comments in rows
    }


def print_ranked_results(ranked: list[dict], cluster_id: int, pool_size: int) -> None:
    print("\n=== Heuristic ranking results ===\n")
    print(f"  assigned_cluster_id : {cluster_id}")
    print(f"  candidate_pool    : {pool_size}")
    print(f"  returned          : {len(ranked)}\n")
    print(
        f"{'#':>3}  {'image_id':<36}  {'score':>8}  "
        f"{'fg_dist':>8}  {'full_dist':>8}  {'trend':>6}  "
        f"{'engage':>6}  {'fresh':>6}  channels"
    )
    print("-" * 120)
    for position, row in enumerate(ranked, start=1):
        channels = ",".join(row.get("source_channels", []))
        mode = row.get("ranking_mode", "")
        explor = " *explor*" if row.get("is_exploration") else ""
        print(
            f"{position:3d}  {row['image_id']:<36}  "
            f"{row.get('model_score', 0):8.4f}  "
            f"{row.get('fg_cosine_distance', 1.0):8.4f}  "
            f"{row.get('full_cosine_distance', 1.0):8.4f}  "
            f"{row.get('trend_score', 0):6.3f}  "
            f"{row.get('engagement_score', 0):6.3f}  "
            f"{row.get('freshness_score', 0):6.3f}  {channels}{explor}"
        )
        if mode == "exploration":
            print(f"      ranking_mode=exploration")
    print()


async def run_heuristic_test(
    database: spanner.Database,
    payload: dict[str, Any],
    *,
    insert_upload: bool,
    seed: int,
    retrieval_timeout: float,
    weight_fg: float | None,
    weight_full: float | None,
    weight_trend: float | None,
    weight_popular: float | None,
    weight_fresh: float | None,
) -> None:
    random.seed(seed)

    request = RecommendationRequest(
        job_id=payload["job_id"],
        upload=UploadContext(
            foreground_embedding=payload["foreground_embedding"],
            full_image_embedding=payload["full_image_embedding"],
            intent=payload.get("intent"),
        ),
        top_n=int(payload.get("top_n", 20)),
        retrieval_overrides=payload.get("retrieval_overrides"),
    )

    assigner = ClusterAssigner(database)  # Uses default timeout for assignment
    orchestrator = RetrievalOrchestrator(database, deadline_sec=retrieval_timeout)
    ranker_kwargs: dict[str, float] = {}
    if weight_fg is not None:
        ranker_kwargs["weight_fg"] = weight_fg
    if weight_full is not None:
        ranker_kwargs["weight_full"] = weight_full
    if weight_trend is not None:
        ranker_kwargs["weight_trend"] = weight_trend
    if weight_popular is not None:
        ranker_kwargs["weight_popular"] = weight_popular
    if weight_fresh is not None:
        ranker_kwargs["weight_fresh"] = weight_fresh
    
    # DEBUG: Log weights passed to ranker
    print(f"\n[DEBUG] Weight overrides received:")
    print(f"  weight_fg={weight_fg}, weight_full={weight_full}, weight_trend={weight_trend}, weight_popular={weight_popular}, weight_fresh={weight_fresh}")
    print(f"[DEBUG] ranker_kwargs (passed to HeuristicRanker):")
    print(f"  {ranker_kwargs}")
    
    ranker = HeuristicRanker(**ranker_kwargs)
    
    print(f"[DEBUG] HeuristicRanker created with weights:")
    print(f"  weight_fg={ranker.weight_fg}")
    print(f"  weight_full={ranker.weight_full}")
    print(f"  weight_trend={ranker.weight_trend}")
    print(f"  weight_popular={ranker.weight_popular}")
    print(f"  weight_fresh={ranker.weight_fresh}")

    cluster_id = await assigner.assign_cluster(
        request.upload.foreground_embedding,
        "foreground",
    )
    print(f"\nCluster assigned: {cluster_id}")

    if insert_upload:
        insert_uploaded_product(database, payload, cluster_id)
        print(f"Inserted uploaded_products row for job_id={payload['job_id']}")

    candidates = await orchestrator.get_candidates(request, cluster_id=cluster_id)
    channel_counts = _channel_summary(candidates)
    print(f"Retrieved {len(candidates)} unique candidates")
    print(f"Channel coverage: {channel_counts}")
    
    # DEBUG: Show signals for first 5 candidates before ranking
    print(f"\n[DEBUG] Sample candidate signals (first 5):")
    for i, cand in enumerate(candidates[:5]):
        print(f"  Candidate {i}: image_id={cand.get('image_id')}, channels={cand.get('source_channels', [])}")
        print(f"    fg_dist={cand.get('fg_cosine_distance', 'N/A')}, full_dist={cand.get('full_cosine_distance', 'N/A')}")
        print(f"    trend={cand.get('trend_score', 'N/A')}, engage={cand.get('engagement_score', 'N/A')}, fresh={cand.get('freshness_score', 'N/A')}")

    ranked = ranker.rank(candidates, top_n=request.top_n)
    
    # DEBUG: Show ranked results with computed model_scores
    print(f"\n[DEBUG] Top 5 ranked results with model_scores:")
    for i, result in enumerate(ranked[:5]):
        print(f"  #{i+1}: image_id={result.get('image_id')}, model_score={result.get('model_score', 'N/A')}")
        print(f"    channels={result.get('source_channels', [])}, is_exploration={result.get('is_exploration', False)}")
    print_ranked_results(ranked, cluster_id, len(candidates))

    image_meta = _fetch_likes_comments(
        database,
        [row["image_id"] for row in ranked],
    )

    output_path = Path(payload.get("output_file", f"staging_result_{payload['job_id']}.json"))
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "job_id": payload["job_id"],
                "assigned_cluster_id": cluster_id,
                "candidate_pool_size": len(candidates),
                "channel_counts": channel_counts,
                "ranking_mode": "cold_start_heuristic",
                "weights": {
                    "weight_fg": ranker.weight_fg,
                    "weight_full": ranker.weight_full,
                    "weight_trend": ranker.weight_trend,
                    "weight_popular": ranker.weight_popular,
                    "weight_fresh": ranker.weight_fresh,
                },
                "results": [
                    {
                        "position": pos,
                        "image_id": row["image_id"],
                        "image_url": row.get("image_url"),
                        "likes": image_meta.get(row["image_id"], {}).get("likes"),
                        "comments": image_meta.get(row["image_id"], {}).get("comments"),
                        "model_score": row.get("model_score"),
                        "fg_cosine_distance": row.get("fg_cosine_distance"),
                        "full_cosine_distance": row.get("full_cosine_distance"),
                        "trend_score": row.get("trend_score"),
                        "engagement_score": row.get("engagement_score"),
                        "freshness_score": row.get("freshness_score"),
                        "source_channels": row.get("source_channels", []),
                        "ranking_mode": row.get("ranking_mode"),
                        "is_exploration": row.get("is_exploration", False),
                    }
                    for pos, row in enumerate(ranked, start=1)
                ],
            },
            handle,
            indent=2,
        )
    print(f"Full results written to: {output_path.resolve()}")


def main() -> int:
    _load_dotenv_file(_REPO_ROOT / ".env")
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    try:
        database = resolve_database(args)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    if not args.input and not args.check_prereqs and not args.run_setup:
        logger.error("Provide --input, or use --check-prereqs / --run-setup")
        return 1

    payload: dict[str, Any] | None = None
    if args.input:
        try:
            payload = load_test_input(args.input)
        except (ValueError, FileNotFoundError) as exc:
            logger.error("%s", exc)
            return 1

    if args.run_setup:
        try:
            run_setup_commands(args)
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 1

    if args.check_prereqs or args.run_setup:
        if not check_prerequisites(database):
            return 1
        if args.check_prereqs:
            return 0

    if payload is None:
        return 0

    try:
        asyncio.run(
            run_heuristic_test(
                database,
                payload,
                insert_upload=args.insert_uploaded_product,
                seed=args.seed,
                retrieval_timeout=args.retrieval_timeout,
                weight_fg=args.weight_fg,
                weight_full=args.weight_full,
                weight_trend=args.weight_trend,
                weight_popular=args.weight_popular,
                weight_fresh=args.weight_fresh,
            )
        )
    except GoogleAPIError as exc:
        logger.error("Spanner error during heuristic test: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
