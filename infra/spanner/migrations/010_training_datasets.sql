CREATE TABLE training_datasets (
  dataset_id       STRING(64) NOT NULL,
  bq_table         STRING(MAX),
  date_range_start DATE,
  date_range_end   DATE,
  num_groups       INT64,
  num_rows         INT64,
  positive_rate    FLOAT64,
  created_at       TIMESTAMP OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (dataset_id);
