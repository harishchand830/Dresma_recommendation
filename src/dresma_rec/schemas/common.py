"""Shared schema types and aliases."""

from typing import Annotated

from pydantic import Field

# 1408-dimensional embedding vector (RFC Sections 4.2, 7.1).
Embedding1408 = Annotated[list[float], Field(min_length=1408, max_length=1408)]
