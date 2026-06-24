"""Shared pytest fixtures and in-memory GCP mocks."""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("PROJECT_ID", "test-project")
os.environ.setdefault("SPANNER_INSTANCE_ID", "test-instance")
os.environ.setdefault("SPANNER_DATABASE_ID", "test-database")
os.environ.setdefault("PUBSUB_INTERACTION_TOPIC", "dresma-interaction-events")
os.environ.setdefault("ENVIRONMENT", "development")

from dresma_rec.auth.service_identity import verify_service_account
from dresma_rec.events.publisher import EventPublisher, get_event_publisher
from dresma_rec.main import app
from dresma_rec.ranking.heuristic import HeuristicRanker, get_heuristic_ranker
from dresma_rec.retrieval.channels import freshness, popular, trending
from dresma_rec.retrieval.cluster_assignment import ClusterAssigner, get_cluster_assigner
from dresma_rec.retrieval.orchestrator import RetrievalOrchestrator, get_retrieval_orchestrator
from dresma_rec.schemas.interaction import InteractionRequest
from dresma_rec.schemas.recommendations import RecommendationResult
from dresma_rec.storage.spanner.client import get_spanner_database
from dresma_rec.storage.spanner.events import get_events_repository
from dresma_rec.storage.spanner.sessions import SessionRepository, get_session_repository
from dresma_rec.storage.spanner.user_actions import (
    UserActionsRepository,
    get_user_actions_repository,
)

_MOCK_CLUSTER_ID = 412
_MOCK_BASE_URL = "https://example.com"

EMBEDDING_DIM = 1408
MOCK_EMBEDDING: list[float] = [0.01] * EMBEDDING_DIM

# C1/C2 vector rows: (image_id, image_url, cluster_id, distance)
_C1_ROWS: list[tuple[str, str, int, float]] = [
    (f"img-fg-{index:02d}", f"{_MOCK_BASE_URL}/img-fg-{index:02d}.jpg", _MOCK_CLUSTER_ID, 0.05 + (index * 0.01))
    for index in range(1, 16)
]

_C2_ROWS: list[tuple[str, str, int, float]] = [
    (f"img-full-{index:02d}", f"{_MOCK_BASE_URL}/img-full-{index:02d}.jpg", _MOCK_CLUSTER_ID, 0.08 + (index * 0.01))
    for index in range(1, 13)
] + [
    ("img-fg-01", f"{_MOCK_BASE_URL}/img-fg-01.jpg", _MOCK_CLUSTER_ID, 0.12),
    ("img-fg-02", f"{_MOCK_BASE_URL}/img-fg-02.jpg", _MOCK_CLUSTER_ID, 0.15),
]

# C3/C4/C5 signal rows: (image_id, image_url, cluster_id, score)
_C3_ROWS: list[tuple[str, str, int, float]] = [
    (f"img-trend-{index:02d}", f"{_MOCK_BASE_URL}/img-trend-{index:02d}.jpg", _MOCK_CLUSTER_ID, 0.55 + (index * 0.02))
    for index in range(1, 13)
] + [
    ("img-fg-03", f"{_MOCK_BASE_URL}/img-fg-03.jpg", _MOCK_CLUSTER_ID, 0.92),
    ("img-fg-04", f"{_MOCK_BASE_URL}/img-fg-04.jpg", _MOCK_CLUSTER_ID, 0.88),
]

_C4_ROWS: list[tuple[str, str, int, float]] = [
    (f"img-pop-{index:02d}", f"{_MOCK_BASE_URL}/img-pop-{index:02d}.jpg", _MOCK_CLUSTER_ID, 0.50 + (index * 0.02))
    for index in range(1, 11)
] + [
    ("img-fg-05", f"{_MOCK_BASE_URL}/img-fg-05.jpg", _MOCK_CLUSTER_ID, 0.85),
]

_C5_ROWS: list[tuple[str, str, int, float]] = [
    (f"img-fresh-{index:02d}", f"{_MOCK_BASE_URL}/img-fresh-{index:02d}.jpg", _MOCK_CLUSTER_ID, 0.70 + (index * 0.01))
    for index in range(1, 21)
]


def _mock_execute_sql(
    sql: str,
    params: dict[str, Any] | None = None,
    param_types: dict[str, Any] | None = None,
) -> Iterator[tuple[Any, ...]]:
    limit = int((params or {}).get("limit", 50))
    normalized_sql = " ".join(sql.split())

    if "FROM clusters" in normalized_sql and "COSINE_DISTANCE" in normalized_sql:
        yield (_MOCK_CLUSTER_ID, 0.1)
        return

    if "FROM reference_images" in normalized_sql and "foreground_embedding" in normalized_sql:
        yield from _C1_ROWS[:limit]
        return

    if "FROM reference_images" in normalized_sql and "full_image_embedding" in normalized_sql:
        yield from _C2_ROWS[:limit]
        return

    if "image_signals" in normalized_sql and "trend_score" in normalized_sql:
        yield from _C3_ROWS[:limit]
        return

    if "image_signals" in normalized_sql and "engagement_score" in normalized_sql:
        yield from _C4_ROWS[:limit]
        return

    if "image_signals" in normalized_sql and "freshness_score" in normalized_sql:
        yield from _C5_ROWS[:limit]
        return

    if "recommendation_sessions" in normalized_sql:
        return iter(())

    return iter(())


class MockTransaction:
    def insert(self, *args: Any, **kwargs: Any) -> None:
        pass


class MockSnapshot:
    def __enter__(self) -> MockSnapshot:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute_sql(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        param_types: dict[str, Any] | None = None,
    ) -> Iterator[tuple[Any, ...]]:
        return _mock_execute_sql(sql, params=params, param_types=param_types)


class MockSpannerDatabase:
    """In-memory Spanner database stand-in for integration tests."""

    def snapshot(self) -> MockSnapshot:
        return MockSnapshot()

    def execute_sql(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        param_types: dict[str, Any] | None = None,
    ) -> Iterator[tuple[Any, ...]]:
        return _mock_execute_sql(sql, params=params, param_types=param_types)

    def run_in_transaction(self, callback: Any) -> None:
        callback(MockTransaction())


class MockEventPublisher:
    async def publish_interaction(self, event: InteractionRequest) -> None:
        pass


class MockSessionRepository:
    async def get_session_metadata(self, job_id: str) -> dict[str, Any]:
        return {}

    async def create_session(
        self,
        job_id: str,
        assigned_cluster_id: int,
        model_version: str,
        retrieval_config: dict[str, Any],
    ) -> None:
        pass


class MockEventsRepository:
    def __init__(self, captured_results: list[RecommendationResult]) -> None:
        self._captured_results = captured_results

    async def write_events(
        self, job_id: str, results: list[RecommendationResult]
    ) -> None:
        self._captured_results.extend(results)


class MockUserActionsRepository:
    async def write_action(self, event: InteractionRequest) -> None:
        pass


async def _mock_verify_service_account() -> dict[str, str]:
    return {"email": "test@example.com"}


@pytest.fixture
def recommendation_events_capture() -> list[RecommendationResult]:
    return []


@pytest.fixture
def client(
    recommendation_events_capture: list[RecommendationResult],
) -> Generator[TestClient, None, None]:
    trending._channel_cache.clear()
    popular._channel_cache.clear()
    freshness._channel_cache.clear()

    mock_database = MockSpannerDatabase()
    mock_publisher = MockEventPublisher()
    mock_cluster_assigner = ClusterAssigner(mock_database)
    mock_orchestrator = RetrievalOrchestrator(mock_database)
    mock_ranker = HeuristicRanker()
    mock_session_repo = MockSessionRepository()
    mock_events_repo = MockEventsRepository(recommendation_events_capture)
    mock_user_actions_repo = MockUserActionsRepository()

    app.dependency_overrides[get_spanner_database] = lambda: mock_database
    app.dependency_overrides[get_cluster_assigner] = lambda: mock_cluster_assigner
    app.dependency_overrides[get_retrieval_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_heuristic_ranker] = lambda: mock_ranker
    app.dependency_overrides[get_event_publisher] = lambda: mock_publisher
    app.dependency_overrides[get_session_repository] = lambda: mock_session_repo
    app.dependency_overrides[get_events_repository] = lambda: mock_events_repo
    app.dependency_overrides[get_user_actions_repository] = (
        lambda: mock_user_actions_repo
    )
    app.dependency_overrides[verify_service_account] = _mock_verify_service_account

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
