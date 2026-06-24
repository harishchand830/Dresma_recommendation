
from google.cloud import spanner
from datetime import datetime, timezone

PROJECT_ID = "vertex-production-391117"
INSTANCE_ID = "spannertest1"
DATABASE_ID = "brand-db"


BATCH_SIZE = 1000

client = spanner.Client(project=PROJECT_ID)
instance = client.instance(INSTANCE_ID)
database = instance.database(DATABASE_ID)

QUERY = """
SELECT image_id, as_of_date
FROM image_signals
WHERE as_of_date = DATE '2026-06-22'
"""

with database.snapshot() as snapshot:
    rows = list(snapshot.execute_sql(QUERY))

print(f"Found {len(rows)} rows to delete")

for i in range(0, len(rows), BATCH_SIZE):
    batch_rows = rows[i:i + BATCH_SIZE]

    with database.batch() as batch:
        batch.delete(
            table="image_signals",
            keyset=spanner.KeySet(
                keys=[
                    (image_id, as_of_date)
                    for image_id, as_of_date in batch_rows
                ]
            ),
        )

    print(
        f"Deleted {min(i + BATCH_SIZE, len(rows))}"
        f"/{len(rows)}"
    )

print("Done")