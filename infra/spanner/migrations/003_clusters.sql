CREATE TABLE clusters (
  cluster_id        INT64 NOT NULL,
  cluster_version   STRING(32) NOT NULL,      -- which clustering run produced it
  centroid_fg       ARRAY<FLOAT32>(vector_length=>1408),   -- centroid in foreground-embedding space
  centroid_full     ARRAY<FLOAT32>(vector_length=>1408),   -- centroid in full-image-embedding space
  size              INT64,                    -- number of reference images in the cluster
  label_hint        STRING(128),              -- optional human label assigned later (NOT required)
  created_at        TIMESTAMP OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (cluster_id, cluster_version);

CREATE INDEX idx_clusters_version ON clusters(cluster_version);
