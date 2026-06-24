# Frontend Heuristic Playground

This folder provides a lightweight frontend + API runner for staging heuristic testing.

## What It Does

- Loads request payload from scripts/staging/my_test.json
- Lets you edit payload fields and embeddings
- Lets you tune heuristic weights from UI
- Executes the real script:
  - python3 scripts/staging_heuristic_test.py --input scripts/staging/my_test.json --seed 42
- Shows uploaded image and recommended result cards
- Displays channels, scores, likes/comments, and exploration flags

## Run

From repository root:

```bash
uvicorn frontend.app:app --reload --port 8090
```

Open:

- http://127.0.0.1:8090

## Notes

- The UI defaults top_n to 40 so you can browse 30-40 recommended images.
- Output is written to frontend/staging_result_frontend.json.
- Script errors are returned back through the API response.
