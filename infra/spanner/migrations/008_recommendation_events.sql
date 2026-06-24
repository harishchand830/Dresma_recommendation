CREATE TABLE recommendation_events (
  job_id         STRING(64) NOT NULL,
  image_id       STRING(64) NOT NULL,
  position       INT64      NOT NULL,    -- displayed rank, 1-based
  model_score    FLOAT64,
  source_channels ARRAY<STRING(16)>,
  feature_snapshot JSON,                 -- features at serve time
  served_at      TIMESTAMP  NOT NULL OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (job_id, image_id);
