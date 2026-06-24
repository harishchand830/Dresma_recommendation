CREATE TABLE user_actions (
  shard_id     INT64     NOT NULL,   -- hash(job_id) % 64
  event_id     STRING(64) NOT NULL,
  job_id       STRING(64) NOT NULL,
  image_id     STRING(64),
  event_type   STRING(16) NOT NULL,  -- IMPRESSION|CLICK|SELECTION|GENERATION|DOWNLOAD
  position     INT64,
  event_time   TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
  metadata     JSON,
) PRIMARY KEY (shard_id, event_time, event_id);

CREATE INDEX idx_actions_job ON user_actions(job_id, image_id, event_type);
