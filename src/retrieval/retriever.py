import time
from uuid import uuid4

import asyncpg
import structlog

from src.config import settings
from src.observability import (
    EVT_COMPLETED,
    EVT_RERANKED,
    EVT_RETRIEVAL_STARTED,
    EVT_VECTOR_SEARCH,
    KEY_REQUEST_ID,
    TimingContext,
)
from src.providers.base import EmbeddingProvider
from src.retrieval.reranker import rerank
from src.schemas.internal import RetrievalMetadata, RetrievedBias
from src.schemas.request import RetrieveRequest
from src.selection.base import SelectionStrategy
from src.selection.vector_only import VectorOnlyStrategy

log = structlog.get_logger()


class IndexNotFoundError(Exception):
    """Raised when the vector index has no rows for the configured taxonomy_version."""


async def retrieve(
    request: RetrieveRequest,
    provider: EmbeddingProvider,
    pool: asyncpg.Pool | None,
    strategy: SelectionStrategy | None = None,
) -> tuple[list[RetrievedBias], RetrievalMetadata]:
    """Full retrieval pipeline: strategy.select() → rerank → metadata.

    Strategy owns embed + vector search (and NLI when nli_union). Defaults to
    VectorOnlyStrategy so callers without an app.state (e.g. eval scripts) still work.
    """
    request_id = request.request_id or str(uuid4())
    # clear_contextvars first — asyncio can reuse task contexts under some middleware,
    # causing a previous request's request_id to bleed into bind_contextvars.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**{KEY_REQUEST_ID: request_id})
    log.info(EVT_RETRIEVAL_STARTED)

    t_total = time.monotonic()

    if strategy is None:
        strategy = VectorOnlyStrategy(provider, pool)

    with TimingContext() as search_t:
        scores, candidates = await strategy.select(request.story, request.story_analysis)
    log.info(EVT_VECTOR_SEARCH, latency_ms=search_t.elapsed_ms, candidates=len(candidates))

    if not candidates:
        raise IndexNotFoundError(settings.taxonomy_version)

    admitted_ids = {bid for bid, s in scores.items() if s > 0.0}

    with TimingContext() as rerank_t:
        biases = rerank(candidates, settings.similarity_threshold, settings.return_top_k, admitted_ids=admitted_ids)
    log.info(EVT_RERANKED, latency_ms=rerank_t.elapsed_ms, returned=len(biases))

    total_ms = int((time.monotonic() - t_total) * 1000)
    log.info(EVT_COMPLETED, latency_ms=total_ms)

    bias_scores = [b.retrieval_score for b in biases]

    meta = RetrievalMetadata(
        retrieval_id=request_id,
        embedding_model=provider.model_name,
        taxonomy_version=settings.taxonomy_version,
        query_strategy=settings.query_strategy,
        query_length=len(request.story),
        embedding_latency_ms=0,
        search_latency_ms=search_t.elapsed_ms,
        rerank_latency_ms=rerank_t.elapsed_ms,
        total_latency_ms=total_ms,
        candidate_chunks=len(candidates),
        surviving_chunks=len(admitted_ids),
        returned_biases=len(biases),
        top_retrieval_score=max(bias_scores) if bias_scores else None,
        avg_retrieval_score=sum(bias_scores) / len(bias_scores) if bias_scores else None,
        threshold_used=settings.similarity_threshold,
    )

    return biases, meta
