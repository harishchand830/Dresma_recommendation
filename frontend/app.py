from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import spanner
from google.cloud.spanner_v1 import param_types
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "staging"
INPUT_PATH = SCRIPTS_DIR / "my_test.json"
OUTPUT_PATH = REPO_ROOT / "frontend" / "staging_result_frontend.json"

# Load .env for project and Spanner settings.
def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

_load_dotenv(REPO_ROOT / ".env")

PROJECT_ID: str | None = os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
SPANNER_INSTANCE: str | None = os.environ.get("SPANNER_INSTANCE_ID") or os.environ.get("INSTANCE")
SPANNER_DATABASE: str | None = os.environ.get("SPANNER_DATABASE_ID") or os.environ.get("DATABASE")


class HeuristicWeights(BaseModel):
    weight_fg: float = Field(default=0.7)
    weight_full: float = Field(default=0.05)
    weight_trend: float = Field(default=0.1)
    weight_popular: float = Field(default=0.1)
    weight_fresh: float = Field(default=0.05)


class RunRequest(BaseModel):
    payload: dict[str, Any]
    seed: int = 42
    weights: HeuristicWeights = Field(default_factory=HeuristicWeights)


app = FastAPI(title="Dresma Staging Heuristic Frontend")
app.mount("/static", StaticFiles(directory=REPO_ROOT / "frontend" / "static"), name="static")


def _get_spanner_database() -> spanner.Database:
    if not PROJECT_ID or not SPANNER_INSTANCE or not SPANNER_DATABASE:
        raise HTTPException(
            status_code=500,
            detail=(
                "Missing Spanner env vars. Set PROJECT_ID, SPANNER_INSTANCE_ID, and "
                "SPANNER_DATABASE_ID in .env"
            ),
        )
    try:
        client = spanner.Client(project=PROJECT_ID)
    except DefaultCredentialsError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Application Default Credentials are missing. Start uvicorn with "
                "GOOGLE_APPLICATION_CREDENTIALS pointing to a valid service-account "
                "JSON file (for example, one fetched from Secret Manager)."
            ),
        ) from exc
    instance = client.instance(SPANNER_INSTANCE)
    return instance.database(SPANNER_DATABASE)


def _fetch_embeddings_by_image_url(image_url: str) -> tuple[list[float], list[float]]:
    database = _get_spanner_database()
    sql = (
        "SELECT foreground_embedding, full_image_embedding "
        "FROM reference_images "
        "WHERE image_url = @image_url "
        "AND foreground_embedding IS NOT NULL "
        "AND full_image_embedding IS NOT NULL "
        "ORDER BY ingested_at DESC "
        "LIMIT 1"
    )

    try:
        with database.snapshot() as snapshot:
            rows = list(
                snapshot.execute_sql(
                    sql,
                    params={"image_url": image_url},
                    param_types={"image_url": param_types.STRING},
                )
            )
    except GoogleAPIError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Failed to access Spanner with current ADC credentials. "
                "If using service-account impersonation, ensure your user has "
                "roles/iam.serviceAccountTokenCreator on the target service account. "
                f"Underlying error: {exc}"
            ),
        ) from exc

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No reference_images row with embeddings found for image_url: {image_url}",
        )

    fg, full = rows[0]
    return [float(x) for x in fg], [float(x) for x in full]


@app.get("/api/reference-image-options")
def reference_image_options(limit: int = 200) -> dict[str, Any]:
    database = _get_spanner_database()
    sql = (
        "SELECT image_url "
        "FROM reference_images "
        "WHERE image_url IS NOT NULL "
        "AND foreground_embedding IS NOT NULL "
        "AND full_image_embedding IS NOT NULL "
        "LIMIT @limit"
    )

    try:
        with database.snapshot() as snapshot:
            rows = list(
                snapshot.execute_sql(
                    sql,
                    params={"limit": int(limit)},
                    param_types={"limit": param_types.INT64},
                )
            )
    except GoogleAPIError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Failed to load URL options from Spanner due to credentials/permissions. "
                "If using service-account impersonation, grant your user "
                "roles/iam.serviceAccountTokenCreator on the service account. "
                f"Underlying error: {exc}"
            ),
        ) from exc

    options = sorted({row[0] for row in rows if row and row[0]})
    return {"options": options}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(REPO_ROOT / "frontend" / "static" / "index.html")


@app.get("/api/sample-input")
def sample_input() -> dict[str, Any]:
    if not INPUT_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Sample input not found at {INPUT_PATH}",
        )
    return json.loads(INPUT_PATH.read_text(encoding="utf-8"))


@app.post("/api/run")
def run_heuristic(request: RunRequest) -> dict[str, Any]:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(request.payload)
    image_url = str(payload.get("image_url", "")).strip()
    if not image_url:
        raise HTTPException(status_code=400, detail="image_url is required.")

    fg_embedding, full_embedding = _fetch_embeddings_by_image_url(image_url)
    payload["foreground_embedding"] = fg_embedding
    payload["full_image_embedding"] = full_embedding
    payload.setdefault("output_file", str(OUTPUT_PATH))

    INPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    cmd = [
        "python3",
        "scripts/staging_heuristic_test.py",
        "--input",
        str(INPUT_PATH),
        "--seed",
        str(request.seed),
        "--weight-fg",
        str(request.weights.weight_fg),
        "--weight-full",
        str(request.weights.weight_full),
        "--weight-trend",
        str(request.weights.weight_trend),
        "--weight-popular",
        str(request.weights.weight_popular),
        "--weight-fresh",
        str(request.weights.weight_fresh),
    ]

    # DEBUG: Log the command being executed
    print(f"[DEBUG] Running command with weights:")
    print(f"  weight_fg={request.weights.weight_fg}")
    print(f"  weight_full={request.weights.weight_full}")
    print(f"  weight_trend={request.weights.weight_trend}")
    print(f"  weight_popular={request.weights.weight_popular}")
    print(f"  weight_fresh={request.weights.weight_fresh}")
    print(f"[DEBUG] Full command: {' '.join(cmd)}")

    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    
    # DEBUG: Log subprocess output
    print(f"[DEBUG] Subprocess stdout:\n{proc.stdout}")
    if proc.stderr:
        print(f"[DEBUG] Subprocess stderr:\n{proc.stderr}")

    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Heuristic script failed",
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "command": " ".join(cmd),
            },
        )

    if not OUTPUT_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Result JSON was not generated",
                "expected_output_file": str(OUTPUT_PATH),
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            },
        )

    results = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    return {
        "command": " ".join(cmd),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "results": results,
    }
