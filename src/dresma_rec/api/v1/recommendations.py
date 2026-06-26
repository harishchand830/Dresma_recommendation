import logging
import random

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from dresma_rec.ranking.heuristic import HeuristicRanker, get_heuristic_ranker
from dresma_rec.ranking.xgb_ranker import XGBoostRanker
from dresma_rec.retrieval.cluster_assignment import ClusterAssigner, get_cluster_assigner
from dresma_rec.retrieval.orchestrator import (
    RetrievalOrchestrator,
    get_retrieval_orchestrator,
)
from dresma_rec.schemas.recommendations import (
    RecommendationRequest,
    RecommendationResponse,
    RecommendationResult,
)
from dresma_rec.storage.spanner.events import (
    RecommendationEventsRepository,
    get_events_repository,
)
from dresma_rec.storage.spanner.sessions import SessionRepository, get_session_repository

logger = logging.getLogger(__name__)

router = APIRouter()


async def persist_serving_logs(
    job_id: str,
    assigned_cluster_id: int,
    model_version: str,
    retrieval_config: dict,
    results: list[RecommendationResult],
    session_repo: SessionRepository,
    events_repo: RecommendationEventsRepository,
) -> None:
    try:
        await session_repo.create_session(
            job_id,
            assigned_cluster_id,
            model_version,
            retrieval_config,
        )
        await events_repo.write_events(job_id, results)
    except Exception:
        logger.exception(
            "Failed to persist recommendation serving logs for job_id=%s",
            job_id,
        )


def _to_recommendation_results(ranked: list[dict]) -> list[RecommendationResult]:
    return [
        RecommendationResult(
            image_id=candidate["image_id"],
            image_url=candidate["image_url"],
            position=position,
            model_score=candidate["model_score"],
            source_channels=candidate["source_channels"],
            metadata=candidate,
        )
        for position, candidate in enumerate(ranked, start=1)
    ]


def _channel_counts(results: list[RecommendationResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        for channel in result.source_channels:
            counts[channel] = counts.get(channel, 0) + 1
    return counts


def _response_ranking_mode(ranked: list[dict]) -> str:
    if ranked and ranked[0].get("ranking_mode") == "xgboost":
        return "model"
    return "cold_start_heuristic"


def _response_model_version(ranked: list[dict], model_manager) -> str:
    if ranked and ranked[0].get("ranking_mode") == "xgboost":
        return model_manager.active_version
    return "none"


@router.post("/", response_model=RecommendationResponse)
async def create_recommendations(
    request: RecommendationRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    assigner: ClusterAssigner = Depends(get_cluster_assigner),
    orchestrator: RetrievalOrchestrator = Depends(get_retrieval_orchestrator),
    heuristic_ranker: HeuristicRanker = Depends(get_heuristic_ranker),
    session_repo: SessionRepository = Depends(get_session_repository),
    events_repo: RecommendationEventsRepository = Depends(get_events_repository),
) -> RecommendationResponse:
    model_manager = http_request.app.state.model_manager

    cluster_id = await assigner.assign_cluster(
        request.upload.foreground_embedding,
        "foreground",
    )

    candidates = await orchestrator.get_candidates(request, cluster_id=cluster_id)

    use_ml = False
    if model_manager.active_booster and cluster_id in model_manager.graduated_clusters:
        if model_manager.active_status == "CANARY":
            use_ml = random.random() < 0.10
        elif model_manager.active_status == "PRODUCTION":
            use_ml = True

    if use_ml:
        xgb_ranker = XGBoostRanker(model_manager)
        try:
            ranked = xgb_ranker.rank(candidates, top_n=request.top_n)
        except Exception:
            logger.exception(
                "XGBoost ranker failed for job_id=%s; falling back to heuristic",
                request.job_id,
            )
            ranked = heuristic_ranker.rank(candidates, top_n=request.top_n)
    else:
        ranked = heuristic_ranker.rank(candidates, top_n=request.top_n)

    results = _to_recommendation_results(ranked)
    ranking_mode = _response_ranking_mode(ranked)
    model_version = _response_model_version(ranked, model_manager)

    response = RecommendationResponse(
        job_id=request.job_id,
        assigned_cluster_id=cluster_id,
        model_version=model_version,
        ranking_mode=ranking_mode,
        results=results,
    )

    background_tasks.add_task(
        persist_serving_logs,
        response.job_id,
        cluster_id,
        model_version,
        {"channels": ["C1", "C2", "C3", "C4", "C5", "C6"]},
        response.results,
        session_repo,
        events_repo,
    )

    logger.info(
        "Recommendations generated",
        extra={
            "job_id": request.job_id,
            "assigned_cluster_id": cluster_id,
            "candidate_pool_size": len(candidates),
            "channel_counts": _channel_counts(results),
            "ranking_mode": ranking_mode,
            "model_version": model_version,
            "use_ml": use_ml,
            "cluster_graduated": cluster_id in model_manager.graduated_clusters,
        },
    )

    return response
