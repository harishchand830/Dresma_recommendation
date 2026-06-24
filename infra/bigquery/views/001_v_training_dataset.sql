-- =============================================================================
-- BigQuery view: v_training_dataset (graded relevance labels for XGBoost LTR)
-- =============================================================================
-- Task:        Phase 3 — Task 3.2
-- RFC:         Section 10.3 (graded labels), Section 11.1–11.2 (training data)
-- Depends on:  `PROJECT_ID.dresma.user_actions`
--              `PROJECT_ID.dresma.recommendation_events`
--
-- Before running:
--   1. Replace PROJECT_ID with your GCP project (e.g. dresma-prod).
--   2. Ensure upstream tables/views exist (Task 3.1):
--        `PROJECT_ID.dresma.recommendation_events`
--   3. Apply via `bq query --use_legacy_sql=false < this_file.sql`
--
-- Label semantics (strongest signal wins per job_id + image_id):
--   4 = explicit FEEDBACK (highest intent; thumbs-up / rating in metadata)
--   3 = SELECTION (user chose reference for generation)
--   1 = CLICK or HOVER (weak positive engagement)
--   0 = served item with no stronger interaction (impression-only or no actions)
--
-- Attribution window:
--   Excludes serves from the trailing 1 hour so late-arriving interaction
--   events are not mislabeled as negatives.
-- =============================================================================

CREATE OR REPLACE VIEW `PROJECT_ID.dresma.v_training_dataset` AS

WITH
-- -----------------------------------------------------------------------------
-- Step 1: Aggregate actions per (job_id, image_id).
-- Roll up user_actions to one row per served candidate with intent booleans.
-- -----------------------------------------------------------------------------
action_summary AS (
  SELECT
    job_id,
    image_id,
    COUNTIF(event_type = 'SELECTION') > 0 AS has_selection,
    COUNTIF(event_type = 'FEEDBACK') > 0 AS has_feedback,
    COUNTIF(event_type = 'CLICK') > 0 AS has_click,
    COUNTIF(event_type = 'HOVER') > 0 AS has_hover,
    -- Optional numeric rating from FEEDBACK metadata (e.g. thumbs up = 1).
    MAX(
      CASE
        WHEN event_type = 'FEEDBACK'
        THEN SAFE_CAST(JSON_VALUE(metadata, '$.rating') AS FLOAT64)
      END
    ) AS feedback_rating
  FROM `PROJECT_ID.dresma.user_actions`
  WHERE image_id IS NOT NULL
  GROUP BY job_id, image_id
),

-- -----------------------------------------------------------------------------
-- Step 2: Join served lists to action summary and assign graded relevance.
-- LEFT JOIN ensures candidates with no logged actions receive label 0.
-- -----------------------------------------------------------------------------
labeled_events AS (
  SELECT
    re.job_id,
    re.image_id,
    re.assigned_cluster_id,
    re.feature_snapshot,
    re.served_at,
    CASE
      WHEN COALESCE(a.has_feedback, FALSE) THEN 4
      WHEN COALESCE(a.has_selection, FALSE) THEN 3
      WHEN COALESCE(a.has_click, FALSE) OR COALESCE(a.has_hover, FALSE) THEN 1
      ELSE 0
    END AS relevance_label
  FROM `PROJECT_ID.dresma.recommendation_events` AS re
  LEFT JOIN action_summary AS a
    ON re.job_id = a.job_id
   AND re.image_id = a.image_id
  -- Step 3: Attribution window — drop very recent serves with incomplete labels.
  WHERE re.served_at <= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
)

-- Final projection for downstream build_dataset / feature flattening (Task 3.3+).
SELECT
  job_id,
  image_id,
  assigned_cluster_id,
  feature_snapshot,
  relevance_label,
  served_at
FROM labeled_events;
