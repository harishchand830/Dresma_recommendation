-- Migration 012: Add brand_id + brand_embedding to reference_images and create vector index.
--
-- brand_id links to brand_guides_prod.id (same value as brand_guides_prod primary key).
-- brand_embedding is backfilled from brand_guides_prod.brand_embedding via brand_id.
-- The VECTOR INDEX enables fast COSINE_DISTANCE kNN for Channel C6.
--
-- If the columns already exist (added manually), skip the ALTER TABLE statements
-- and run only the CREATE VECTOR INDEX.

ALTER TABLE reference_images
  ADD COLUMN IF NOT EXISTS brand_id STRING(64);

ALTER TABLE reference_images
  ADD COLUMN IF NOT EXISTS brand_embedding ARRAY<FLOAT64>(vector_length=>1408);

-- If brand_embedding already exists without vector_length, run this instead:
-- ALTER TABLE reference_images
--   ALTER COLUMN brand_embedding ARRAY<FLOAT64>(vector_length=>1408);

CREATE VECTOR INDEX IF NOT EXISTS idx_brand_embedding
  ON reference_images(brand_embedding)
  WHERE brand_embedding IS NOT NULL
  OPTIONS (distance_type = 'COSINE');
