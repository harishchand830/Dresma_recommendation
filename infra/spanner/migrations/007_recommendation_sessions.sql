CREATE TABLE recommendation_sessions (
  job_id            STRING(64) NOT NULL,
  assigned_cluster_id INT64,                  -- cluster the upload was assigned to
  model_version     STRING(64),               -- which ranker scored this
  retrieval_config  JSON,                     -- channel sizes used
  served_at         TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (job_id);
