"""Abstract base class for retrieval channels."""

from abc import ABC, abstractmethod

from dresma_rec.schemas.recommendations import RecommendationRequest


class BaseRetrievalChannel(ABC):
    """Base interface for a single multi-channel retrieval source."""

    @abstractmethod
    async def retrieve(
        self,
        request: RecommendationRequest,
        limit: int,
        **kwargs,
    ) -> list[dict]:
        """Return candidate reference images from this channel."""
