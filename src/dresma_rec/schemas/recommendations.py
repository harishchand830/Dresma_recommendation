"""Pydantic schemas for POST /v1/recommendations (RFC Section 14.1)."""

from typing import Literal

from pydantic import BaseModel, Field

from dresma_rec.schemas.common import Embedding1408

RankingMode = Literal["model", "cold_start_heuristic", "baseline_cosine"]


class UploadContext(BaseModel):
    """Uploaded product embeddings and optional intent (RFC Section 14.1)."""

    foreground_embedding: Embedding1408
    full_image_embedding: Embedding1408
    intent: str | None = None


class RecommendationRequest(BaseModel):
    """Request body for POST /v1/recommendations."""

    job_id: str
    upload: UploadContext
    brand_name: str | None = None
    top_n: int = Field(default=20, gt=0)
    retrieval_overrides: dict[str, int] | None = None


class RecommendationResult(BaseModel):
    """Single ranked reference in the recommendation response."""

    image_id: str
    image_url: str
    position: int = Field(ge=1)
    model_score: float
    source_channels: list[str]
    metadata: dict = Field(default_factory=dict, exclude=True)


class RecommendationResponse(BaseModel):
    """Response body for POST /v1/recommendations."""

    job_id: str
    assigned_cluster_id: int
    model_version: str
    ranking_mode: RankingMode
    results: list[RecommendationResult]
