import time
from uuid import uuid4

import asyncpg
import structlog

from src.config import settings
from src.db.queries import FETCH_BY_BIAS_IDS
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
from src.retrieval.searcher import _row_to_candidate
from src.schemas.internal import CandidateChunk, RetrievalMetadata, RetrievedBias
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
        scores, candidates, strategy_meta = await strategy.select(request.story, request.story_analysis)
    log.info(EVT_VECTOR_SEARCH, latency_ms=search_t.elapsed_ms, candidates=len(candidates))

    if not candidates:
        raise IndexNotFoundError(settings.taxonomy_version)

    admitted_ids = set(scores.keys())

    # NLI-admitted biases with no vector chunk won't survive the reranker's candidate
    # filter. Fetch one definition chunk per missing bias so they can be hydrated.
    candidate_bias_ids = {c.bias_id for c in candidates}
    missing_ids = admitted_ids - candidate_bias_ids
    if missing_ids and pool is not None:
        async with pool.acquire() as conn:
            rows = await conn.fetch(FETCH_BY_BIAS_IDS, settings.taxonomy_version, list(missing_ids))
        if rows:
            hydrated: list[CandidateChunk] = []
            for r in rows:
                c = _row_to_candidate(r)
                hydrated.append(CandidateChunk(
                    bias_id=c.bias_id,
                    chunk_type=c.chunk_type,
                    source_section=c.source_section,
                    source=c.source,
                    chunk_text=c.chunk_text,
                    full_document=c.full_document,
                    retrieval_score=scores.get(c.bias_id, 0.0),
                ))
            candidates = list(candidates) + hydrated
            log.info("nli_only_admits_hydrated", count=len(rows), bias_ids=sorted(missing_ids))

    with TimingContext() as rerank_t:
        biases = rerank(candidates, settings.similarity_threshold, settings.return_top_k, admitted_ids=admitted_ids, score_override=scores or None)
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
        selection_strategy=strategy_meta.selection_strategy,
        hypotheses_version=strategy_meta.hypotheses_version,
        nli_latency_ms=strategy_meta.nli_latency_ms,
        truncated_premise=strategy_meta.truncated_premise,
        nli_scores=strategy_meta.nli_scores,
        vector_scores=strategy_meta.vector_scores,
        combined_scores=strategy_meta.combined_scores,
        llm_scores=strategy_meta.llm_scores,
        sources=strategy_meta.sources,
        llm_latency_ms=strategy_meta.llm_latency_ms,
        truncated_story=strategy_meta.truncated_story,
    )

    return biases, meta
