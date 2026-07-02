-- Migration 012: Add cluster_id to brand_references and create vector indexes.
--
-- brand_references replaces the reference_images table as the source-of-truth
-- for image candidates. The reclustering job writes cluster_id back here.
-- Vector indexes mirror the old idx_fg_embedding / idx_full_embedding on
-- reference_images, but point to the actual embedding columns in brand_references.

ALTER TABLE brand_references ADD COLUMN IF NOT EXISTS cluster_id INT64;

-- Vector index on bg_remove_url_embeddings (foreground / bg-removed embedding)
-- mirrors the old idx_fg_embedding on reference_images.
CREATE VECTOR INDEX IF NOT EXISTS idx_br_fg_embedding
  ON brand_references(bg_remove_url_embeddings)
  WHERE image_url_embeddings IS NOT NULL
    AND (image_type IS NULL OR image_type != 'video')
  OPTIONS (distance_type = 'COSINE');

-- Vector index on image_url_embeddings (full-image embedding)
-- mirrors the old idx_full_embedding on reference_images.
CREATE VECTOR INDEX IF NOT EXISTS idx_br_full_embedding
  ON brand_references(image_url_embeddings)
  WHERE image_url_embeddings IS NOT NULL
    AND (image_type IS NULL OR image_type != 'video')
  OPTIONS (distance_type = 'COSINE');

-- Standard index for cluster-scoped channel queries (C3/C4/C5).
CREATE INDEX IF NOT EXISTS idx_br_cluster ON brand_references(cluster_id);
