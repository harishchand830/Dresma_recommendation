"""Pydantic schemas for POST /v1/interaction (RFC Section 14.2)."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class InteractionEventType(str, Enum):
    """User interaction event types (RFC Section 8.1)."""

    IMPRESSION = "IMPRESSION"
    CLICK = "CLICK"
    SELECTION = "SELECTION"
    GENERATION = "GENERATION"
    DOWNLOAD = "DOWNLOAD"
    FEEDBACK = "FEEDBACK"


class InteractionRequest(BaseModel):
    """Request body for POST /v1/interaction."""

    event_id: str
    job_id: str
    image_id: str
    event_type: InteractionEventType
    position: int = Field(ge=1)
    event_time: datetime
    metadata: dict[str, Any] | None = None
