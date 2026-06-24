-- =============================================================================
-- NOTE: The feature_snapshot column is natively stored as JSON. Data synchronized
-- from Spanner arrives as a stringified JSON and MUST be parsed using
-- PARSE_JSON(feature_snapshot) during the insert/merge, as implemented in
-- infra/bigquery/scheduled_queries/spanner_to_bq_events.sql.
-- =============================================================================
-- BigQuery native table: recommendation_events (training / analytics export)
-- =============================================================================
-- Task:        Phase 3 — Task 3.1
-- Source:      Spanner `recommendation_events` (+ session fields from
--              `recommendation_sessions` via scheduled federated sync)
-- RFC:         Section 7.7, 11.1
--
-- Before running:
--   1. Replace PROJECT_ID with your GCP project (e.g. dresma-prod).
--   2. Ensure dataset `dresma` exists:
--        CREATE SCHEMA IF NOT EXISTS `PROJECT_ID.dresma`
--        OPTIONS (location = 'US');
--   3. Apply via `bq query --use_legacy_sql=false < this_file.sql`
-- =============================================================================

CREATE TABLE IF NOT EXISTS `PROJECT_ID.dresma.recommendation_events` (
  job_id              STRING    NOT NULL
    OPTIONS (description = 'Recommendation session / upload identifier (RFC Section 8.4).'),
  image_id            STRING    NOT NULL
    OPTIONS (description = 'Served reference image identifier.'),
  position            INT64     NOT NULL
    OPTIONS (description = '1-based display rank at serve time.'),
  model_version       STRING
    OPTIONS (description = 'Ranker version from recommendation_sessions (e.g. none, xgb-rank-YYYY-MM-DD).'),
  ranking_mode        STRING
    OPTIONS (description = 'Ranking path: baseline_cosine, cold_start_heuristic, exploration, model.'),
  assigned_cluster_id INT64
    OPTIONS (description = 'Upload cluster assigned at serve time (from recommendation_sessions).'),
  feature_snapshot    JSON
    OPTIONS (description = 'Full serve-time feature vector / candidate metadata for train/serve parity.'),
  served_at           TIMESTAMP NOT NULL
    OPTIONS (description = 'UTC timestamp when the list was served.')
)
PARTITION BY DATE(served_at)
CLUSTER BY job_id, image_id
OPTIONS (
  description = 'Served recommendation lists exported from Spanner for XGBoost training joins (Phase 3).'
);
