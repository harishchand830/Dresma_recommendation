CREATE TABLE cluster_trends (
  cluster_id      INT64      NOT NULL,
  as_of_date      DATE       NOT NULL,
  cluster_trend   FLOAT64,
) PRIMARY KEY (cluster_id, as_of_date);
