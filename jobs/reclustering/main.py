#!/usr/bin/env python3
"""Periodic reclustering job skeleton (RFC Section 4.2b, Task 2.6)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from google.api_core.exceptions import GoogleAPIError
from google.cloud import spanner

from jobs.common.spanner_util import add_spanner_args, resolve_database
from jobs.reclustering.clustering import kmeans_cosine

logger = logging.getLogger(__name__)

_FETCH_EMBEDDINGS = """
SELECT image_id, foreground_embedding
FROM reference_images
WHERE foreground_embedding IS NOT NULL
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recluster reference images and refresh clusters table."
    )
    add_spanner_args(parser)
    parser.add_argument(
        "--cluster_version",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Version label for this clustering run.",
    )
    parser.add_argument(
        "--num_clusters",
        type=int,
        default=32,
        help="Target number of clusters.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of images to process for testing.",
    )
    return parser.parse_args()


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

    fetch_sql = _FETCH_EMBEDDINGS
    if args.limit:
        fetch_sql += f" LIMIT {args.limit}"
        logger.info("Limiting query to %d rows", args.limit)

    try:
        with database.snapshot() as snapshot:
            rows = list(snapshot.execute_sql(fetch_sql))
    except GoogleAPIError as exc:
        logger.error("Failed to read reference_images embeddings: %s", exc)
        return 1

    embeddings = {
        image_id: list(embedding)
        for image_id, embedding in rows
        if embedding is not None
    }
    if not embeddings:
        logger.info("No embeddings available for reclustering.")
        return 0

    clusters = kmeans_cosine(embeddings, k=args.num_clusters)
    cluster_version = args.cluster_version

    cluster_values = [
        (
            cluster.cluster_id,
            cluster_version,
            cluster.centroid,
            cluster.centroid,
            cluster.size,
            None,
            spanner.COMMIT_TIMESTAMP,
        )
        for cluster in clusters
    ]

    image_updates: list[tuple[str, int]] = []
    for cluster in clusters:
        for image_id in cluster.member_image_ids:
            image_updates.append((image_id, cluster.cluster_id))

    def _write_clusters(transaction: spanner.Transaction) -> None:
        """Writes the new cluster definitions to the clusters table."""
        transaction.insert_or_update(
            table="clusters",
            columns=[
                "cluster_id",
                "cluster_version",
                "centroid_fg",
                "centroid_full",
                "size",
                "label_hint",
                "created_at",
            ],
            values=cluster_values,
        )

    try:
        database.run_in_transaction(_write_clusters)
        logger.info("Wrote %d rows to clusters table.", len(cluster_values))
    except GoogleAPIError as exc:
        logger.error("Failed to write to clusters table: %s", exc)
        return 1

    # The previous implementation attempted to write all image updates in a single
    # transaction, which fails when the number of mutations exceeds Spanner's
    # limit (~80,000).
    #
    # The fix is to break the updates into multiple smaller transactions.
    # Each row update generates 2 mutations (table + index), so a batch of
    # 20,000 rows is ~40,000 mutations, safely under the limit.
    _UPDATE_BATCH_SIZE = 20000
    logger.info(
        "Updating cluster_id for %d images in batches of %d...",
        len(image_updates),
        _UPDATE_BATCH_SIZE,
    )

    for i in range(0, len(image_updates), _UPDATE_BATCH_SIZE):
        batch_to_write = image_updates[i : i + _UPDATE_BATCH_SIZE]

        def _write_image_update_batch(transaction: spanner.Transaction) -> None:
            """Writes a single batch of cluster_id updates to reference_images."""
            transaction.update(
                table="reference_images",
                columns=["image_id", "cluster_id"],
                values=batch_to_write,
            )

        try:
            database.run_in_transaction(_write_image_update_batch)
            logger.info(
                "  Successfully updated batch starting at offset %d (%d rows).",
                i,
                len(batch_to_write),
            )
        except GoogleAPIError as exc:
            logger.error(
                "Failed to write image update batch at offset %d: %s", i, exc
            )
            return 1

    logger.info(
        "Reclustering complete: version=%s clusters=%d images=%d",
        cluster_version,
        len(clusters),
        len(image_updates),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
