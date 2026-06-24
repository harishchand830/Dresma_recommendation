CREATE TABLE image_signals (
  image_id             STRING(64) NOT NULL,
  as_of_date           DATE       NOT NULL,
  cluster_id           INT64,
  engagement_score     FLOAT64,
  engagement_velocity  FLOAT64,
  trend_score          FLOAT64,
  freshness_score      FLOAT64,
  aesthetic_score      FLOAT64,
  updated_at           TIMESTAMP OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (image_id, as_of_date);

-- Channel 3 (trending), 4 (engagement), 5 (fresh): top-K within cluster for latest date
CREATE INDEX idx_sig_trending   ON image_signals(cluster_id, as_of_date, trend_score DESC);
CREATE INDEX idx_sig_engagement ON image_signals(cluster_id, as_of_date, engagement_score DESC);
CREATE INDEX idx_sig_fresh      ON image_signals(cluster_id, as_of_date, freshness_score DESC);
