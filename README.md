# Dresma Recommendation Service

This repository contains the Dresma recommendation stack, including:

- FastAPI recommendation service code under `src/dresma_rec`
- Staging heuristic test runner and setup scripts under `scripts/`
- Batch jobs under `jobs/`
- Infra artifacts (Spanner, Pub/Sub, Cloud Run, monitoring) under `infra/`
- A local heuristic playground UI/API under `frontend/`

## 1. Prerequisites

- Python 3.10+
- `gcloud` CLI installed and authenticated
- Access to:
  - GCP project `your project id`
  - Secret Manager secret `your service account`
  - Spanner instance/database used by this project

## 2. Clone And Install

```bash
git clone 
cd dresma
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## 3. Configure Environment

Create or update `.env` at repo root:

```env
PROJECT_ID=
SPANNER_INSTANCE_ID=
SPANNER_DATABASE_ID=
ENVIRONMENT=development
RETRIEVAL_DEADLINE_SEC=0.15
EXPLORATION_RATE=0.10
```

## 4. Authentication For Local Runs (Recommended)

Use a real JSON file from Secret Manager for ADC (stable for Python apps/scripts),or if you have access from your drema account then procced with that:

go to the root directory 
activate the venv

validate the gcloud adc and set it up 



## 5. Run Staging Heuristic Test

run this command to see the results locally-
python3 scripts/staging_heuristic_test.py --input scripts/staging/my_test.json --seed 42




## 6. Run Local Frontend Playground



GOOGLE_APPLICATION_CREDENTIALS=path_of_root_dir/.tmp/spanner-sa.json \
uvicorn app:app --reload --port XXXX
```


## 7. Useful Checks

```bash
# Validate active gcloud account
gcloud config get-value account

# Verify project
gcloud config get-value project

# Verify Spanner access
gcloud spanner instances list --project=your_project_id
```

## 8. Common Issues

### `DefaultCredentialsError: File /dev/fd/* was not found`

Cause:

- Credentials were provided via process substitution (`<(...)`) and path became invalid.

Fix:

- Recreate `.tmp/spanner-sa.json` from Secret Manager and use absolute path in `GOOGLE_APPLICATION_CREDENTIALS`.

### `DefaultCredentialsError: Your default credentials were not found`

Cause:

- Python runtime has no valid ADC path.

Fix:

- Export `GOOGLE_APPLICATION_CREDENTIALS` to the `.tmp/spanner-sa.json` file for each run command.




