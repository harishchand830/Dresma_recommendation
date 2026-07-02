
from google.cloud import spanner
PROJECT_ID = "vertex-production-391117"
INSTANCE_ID = "spannertest1"
DATABASE_ID = "brand-db"


client = spanner.Client(project=PROJECT_ID)
database = client.instance(INSTANCE_ID).database(DATABASE_ID)

QUERY = """
SELECT
    r.id,
    b.brand_embedding
FROM brand_references r
JOIN brand_guides_prod b
    ON r.brand_id = b.id
WHERE b.brand_embedding IS NOT NULL
  AND (r.image_type IS NULL OR r.image_type != 'video')
"""

BATCH_SIZE = 500

with database.snapshot() as snapshot:
    rows = list(snapshot.execute_sql(QUERY))

print(f"Found {len(rows)} rows to update")

def update_batch(transaction, batch):
    transaction.update(
        table="brand_references",
        columns=[
            "id",
            "brand_embedding",
        ],
        values=batch,
    )

updated = 0

for i in range(0, len(rows), BATCH_SIZE):
    batch = rows[i:i + BATCH_SIZE]

    database.run_in_transaction(update_batch, batch)

    updated += len(batch)
    print(f"Updated {updated}/{len(rows)}")

print("Done")