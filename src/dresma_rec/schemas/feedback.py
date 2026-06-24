"""Pydantic schemas for POST /v1/feedback (RFC Section 14.3)."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedbackEventType(str, Enum):
    """Explicit feedback event type (RFC Section 14.3)."""

    FEEDBACK = "FEEDBACK"


class FeedbackMetadata(BaseModel):
    """Feedback payload metadata; ``rating`` is required per RFC Section 14.3."""

    model_config = ConfigDict(extra="allow")

    rating: int | str | bool


class FeedbackRequest(BaseModel):
    """Request body for POST /v1/feedback."""

    event_id: str
    job_id: str
    image_id: str
    event_type: Literal["FEEDBACK"] = "FEEDBACK"
    position: int | None = Field(default=None, ge=1)
    event_time: datetime
    metadata: FeedbackMetadata
