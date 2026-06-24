CREATE TABLE uploaded_products (
  job_id                STRING(64) NOT NULL,
  image_url             STRING(MAX),
  foreground_embedding  ARRAY<FLOAT32>(vector_length=>1408),
  full_image_embedding  ARRAY<FLOAT32>(vector_length=>1408),
  assigned_cluster_id   INT64,          -- nearest cluster, assigned at request time (Section 5.3)
  intent                STRING(32),     -- optional user context
  created_at            TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (job_id);
