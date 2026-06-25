from __future__ import annotations

import json
import os
import subprocess
import base64
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import spanner
from google.cloud.aiplatform_v1 import PredictionServiceClient
from google.cloud.spanner_v1 import param_types
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "staging"
INPUT_PATH = SCRIPTS_DIR / "my_test.json"
OUTPUT_PATH = REPO_ROOT / "frontend" / "staging_result_frontend.json"
VERTEX_AI_ENDPOINT = "multimodalembedding@001"

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


def _get_embeddings_from_image(
    project_id: str, location: str, image_bytes: bytes
) -> tuple[list[float], list[float]]:
    """
    Gets a 1408-dim embedding from the multimodal embedding model.

    NOTE: This model returns a single embedding for the whole image. We are using
    this single vector for BOTH `foreground_embedding` and `full_image_embedding`
    to satisfy the downstream script's input schema. This is a simplification
    and may affect the performance of retrieval channels that rely on the
    distinction between foreground and full image context.
    """
    # Bypassing the high-level aiplatform.Model wrapper to use the direct
    # ModelServiceClient. This avoids complex, unreliable initialization logic
    # within the uvicorn server environment and gives us direct control.

    # 1. Construct the regional API endpoint and the full model resource name.
    api_endpoint = f"{location}-aiplatform.googleapis.com"
    model_endpoint = (
        f"projects/{project_id}/locations/{location}/"
        f"publishers/google/models/{VERTEX_AI_ENDPOINT}"
    )

    # 2. Instantiate the client with the explicit endpoint.
    client_options = {"api_endpoint": api_endpoint}
    client = PredictionServiceClient(client_options=client_options)

    # 3. Prepare the request payload.
    encoded_content = base64.b64encode(image_bytes).decode("utf-8")
    instances = [{"image": {"bytesBase64Encoded": encoded_content}}]

    # 4. Call the predict method on the direct client.
    response = client.predict(endpoint=model_endpoint, instances=instances)

    # 5. Parse the response.
    if not response.predictions:
        raise HTTPException(status_code=500, detail="Vertex AI returned no predictions.")

    # The result is a list of protobuf Value objects. We need the first one.
    embedding_values = response.predictions[0].get("imageEmbedding")
    if not embedding_values:
        raise HTTPException(status_code=500, detail="Vertex AI prediction did not contain 'imageEmbedding'.")

    embedding_vector = [float(v) for v in embedding_values]

    if len(embedding_vector) != 1408:
        raise HTTPException(
            status_code=500,
            detail=f"Vertex AI returned an embedding of unexpected dimension: {len(embedding_vector)}",
        )

    # Use the same embedding for both foreground and full, as discussed.
    return embedding_vector, embedding_vector


@app.get("/")
def index() -> FileResponse:
    return FileResponse(REPO_ROOT / "frontend" / "static" / "index.html")


@app.post("/api/run-from-upload")
def run_heuristic_from_upload(
    # The frontend will send weights as form fields
    weight_fg: float = Form(...),
    weight_full: float = Form(...),
    weight_trend: float = Form(...),
    weight_popular: float = Form(...),
    weight_fresh: float = Form(...),
    seed: int = Form(42),
    image: UploadFile = File(...),
) -> dict[str, Any]:
    if not PROJECT_ID:
        raise HTTPException(status_code=500, detail="PROJECT_ID env var not set.")

    # 1. Get embeddings from Vertex AI using the uploaded image bytes
    # This will use the same GOOGLE_APPLICATION_CREDENTIALS as Spanner
    print(f"[DEBUG] Getting embeddings for uploaded image {image.filename}...")
    image_bytes = image.file.read()
    fg_embedding, full_embedding = _get_embeddings_from_image(
        project_id=PROJECT_ID,
        location="us-central1",  # Common location for this model
        image_bytes=image_bytes,
    )
    print("[DEBUG] Successfully received embeddings from Vertex AI.")

    # 2. Prepare the payload for the script
    payload = {
        "job_id": f"frontend-upload-{uuid.uuid4()}",
        "image_url": f"local-upload:{image.filename}",
        "foreground_embedding": fg_embedding,
        "full_image_embedding": full_embedding,
        "top_n": 40,  # As per frontend/README.md
        "output_file": str(OUTPUT_PATH),
    }
    INPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # 3. Run the heuristic script
    cmd = [
        "python3",
        "scripts/staging_heuristic_test.py",
        "--input",
        str(INPUT_PATH),
        "--seed",
        str(seed),
        "--weight-fg",
        str(weight_fg),
        "--weight-full",
        str(weight_full),
        "--weight-trend",
        str(weight_trend),
        "--weight-popular",
        str(weight_popular),
        "--weight-fresh",
        str(weight_fresh),
    ]

    print(f"[DEBUG] Running command: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )

    # 4. Process and return results
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
            },
        )

    if not OUTPUT_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Result JSON was not generated",
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
