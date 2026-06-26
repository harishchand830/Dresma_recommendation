"""Brand embedding lookup helpers for brand-guided retrieval channels."""

from __future__ import annotations

import logging

from google.cloud.spanner_v1 import param_types
from google.cloud.spanner_v1.database import Database

logger = logging.getLogger(__name__)

_BRAND_LOOKUP_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    # Confirmed schema: brand_guides_prod.name / brand_embedding
    ("brand_guides_prod", "name", "brand_embedding"),
    ("brand_guides_prod", "name", "embedding"),
    # Fallbacks for alternate spellings / legacy tables
    ("brand_guids_prod", "name", "brand_embedding"),
    ("brand_guids_prod", "name", "embedding"),
    ("brand_guides_prod", "brand_name", "brand_embedding"),
    ("brand_guids_prod", "brand_name", "brand_embedding"),
)


def fetch_brand_embedding(database: Database, brand_name: str | None) -> list[float] | None:
    if not brand_name or not brand_name.strip():
        return None

    normalized_brand = brand_name.strip()
    for table_name, name_column, embedding_column in _BRAND_LOOKUP_CANDIDATES:
        sql = f"""
SELECT {embedding_column}
FROM {table_name}
WHERE LOWER({name_column}) = LOWER(@brand_name)
  AND {embedding_column} IS NOT NULL
LIMIT 1
"""
        try:
            with database.snapshot() as snapshot:
                rows = list(
                    snapshot.execute_sql(
                        sql,
                        params={"brand_name": normalized_brand},
                        param_types={"brand_name": param_types.STRING},
                    )
                )
            if rows:
                embedding = rows[0][0]
                if embedding is not None:
                    return list(embedding)
        except Exception as exc:
            logger.debug(
                "Brand embedding lookup failed using %s.%s/%s: %s",
                table_name,
                name_column,
                embedding_column,
                exc,
            )

    return None