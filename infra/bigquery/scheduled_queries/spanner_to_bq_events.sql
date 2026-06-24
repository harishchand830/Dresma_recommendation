-- =============================================================================
-- Scheduled Query: Spanner → BigQuery recommendation_events sync
-- =============================================================================
-- Task:        Phase 3 — Task 3.1
-- Cadence:     Every 15 minutes (configure in BigQuery Scheduled Queries UI)
-- Connection:  BigQuery federated connection to Cloud Spanner
--              Replace PROJECT_ID and REGION before deploying.
--
-- Prerequisites:
--   1. Native table exists: `PROJECT_ID.dresma.recommendation_events`
--      (infra/bigquery/tables/002_recommendation_events.sql)
--   2. BigQuery connection `spanner-connection` created in REGION, pointing at
--      the Spanner instance/database that holds `recommendation_events`.
--   3. Connection service account has Spanner Database Reader on the source DB.
--
-- Overlap window:
--   Spanner SELECT uses served_at >= NOW() - 1 HOUR so a 15-minute schedule
--   re-processes recent rows safely; MERGE is insert-only on (job_id, image_id).
-- =============================================================================

MERGE `PROJECT_ID.dresma.recommendation_events` AS target
USING (
  SELECT
    job_id,
    image_id,
    position,
    model_version,
    ranking_mode,
    assigned_cluster_id,
    -- Spanner returns feature_snapshot as a string via EXTERNAL_QUERY;
    -- parse into native BigQuery JSON for training pipelines.
    PARSE_JSON(feature_snapshot) AS feature_snapshot,
    served_at
  FROM EXTERNAL_QUERY(
    'PROJECT_ID.REGION.spanner-connection',
    '''
    SELECT
      e.job_id,
      e.image_id,
      e.position,
      s.model_version,
      JSON_VALUE(e.feature_snapshot, ''$.ranking_mode'') AS ranking_mode,
      s.assigned_cluster_id,
      TO_JSON_STRING(e.feature_snapshot) AS feature_snapshot,
      e.served_at
    FROM recommendation_events AS e
    INNER JOIN recommendation_sessions AS s
      ON e.job_id = s.job_id
    WHERE e.served_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
    '''
  )
) AS source
ON target.job_id = source.job_id
 AND target.image_id = source.image_id
WHEN NOT MATCHED THEN
  INSERT (
    job_id,
    image_id,
    position,
    model_version,
    ranking_mode,
    assigned_cluster_id,
    feature_snapshot,
    served_at
  )
  VALUES (
    source.job_id,
    source.image_id,
    source.position,
    source.model_version,
    source.ranking_mode,
    source.assigned_cluster_id,
    source.feature_snapshot,
    source.served_at
  );
