CREATE TABLE image_engagement_history (
  image_id          STRING(64) NOT NULL,
  snapshot_at       TIMESTAMP  NOT NULL,
  likes             INT64,
  comments          INT64,
  weighted_engage   FLOAT64,
) PRIMARY KEY (image_id, snapshot_at);
