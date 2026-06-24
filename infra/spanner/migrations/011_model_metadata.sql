CREATE TABLE model_metadata (
  model_version   STRING(64) NOT NULL,   -- e.g. xgb-rank-2026-06-13-01
  artifact_uri    STRING(MAX),           -- gs://dresma-models/...
  dataset_id      STRING(64),
  feature_list    JSON,                  -- ordered feature names (schema contract)
  hyperparams     JSON,
  ndcg_at_10      FLOAT64,
  map_score       FLOAT64,
  mrr             FLOAT64,
  status          STRING(16),            -- TRAINING|VALIDATED|CANARY|PRODUCTION|ROLLED_BACK
  trained_at      TIMESTAMP,
  promoted_at     TIMESTAMP,
) PRIMARY KEY (model_version);

CREATE INDEX idx_model_status ON model_metadata(status, promoted_at DESC);
