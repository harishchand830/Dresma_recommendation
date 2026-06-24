CREATE TABLE reference_images (
  image_id              STRING(64)  NOT NULL,
  image_url             STRING(MAX) NOT NULL,
  platform              STRING(32),
  cluster_id            INT64,                 -- assigned by the offline clustering job (Section 4.2 / clusters table)
  foreground_embedding  ARRAY<FLOAT32>(vector_length=>1408),
  full_image_embedding  ARRAY<FLOAT32>(vector_length=>1408),
  likes                 INT64 NOT NULL DEFAULT (0),
  comments              INT64 NOT NULL DEFAULT (0),
  published_at          TIMESTAMP,
  ingested_at           TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (image_id);

-- Vector indexes for Channels 1 and 2
CREATE VECTOR INDEX idx_fg_embedding   ON reference_images(foreground_embedding)
  OPTIONS (distance_type = 'COSINE');
CREATE VECTOR INDEX idx_full_embedding ON reference_images(full_image_embedding)
  OPTIONS (distance_type = 'COSINE');

-- Secondary index for cluster-scoped reads
CREATE INDEX idx_ref_cluster ON reference_images(cluster_id);
