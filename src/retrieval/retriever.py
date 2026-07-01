import time
from uuid import uuid4

import asyncpg
import structlog

from src.config import settings
from src.observability import (
    EVT_COMPLETED,
    EVT_QUERY_EMBEDDED,
    EVT_RERANKED,
    EVT_RETRIEVAL_STARTED,
    EVT_VECTOR_SEARCH,
    KEY_REQUEST_ID,
    TimingContext,
)
from src.providers.base import EmbeddingProvider
from src.retrieval.query_builder import get_query_strategy
from src.retrieval.reranker import rerank
from src.retrieval.searcher import search_chunks
from src.schemas.internal import RetrievalMetadata, RetrievedBias
from src.schemas.request import RetrieveRequest

log = structlog.get_logger()


class IndexNotFoundError(Exception):
    """Raised when the vector index has no rows for the configured taxonomy_version."""


async def retrieve(
    request: RetrieveRequest,
    provider: EmbeddingProvider,
    pool: asyncpg.Pool,
) -> tuple[list[RetrievedBias], RetrievalMetadata]:
    """Full retrieval pipeline: build query → embed → vector search → rerank.

    Returns the ranked biases and metadata about every step of the pipeline.
    Raises IndexNotFoundError if no chunks are indexed for the active taxonomy_version.
    """
    request_id = request.request_id or str(uuid4())
    # clear_contextvars first — asyncio can reuse task contexts under some middleware,
    # causing a previous request's request_id to bleed into bind_contextvars.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**{KEY_REQUEST_ID: request_id})
    log.info(EVT_RETRIEVAL_STARTED)

    t_total = time.monotonic()

    strategy = get_query_strategy(settings.query_strategy)
    query_text = strategy.build(request.story, request.story_analysis)

    # NOTE: embed_query is synchronous (SentenceTransformer runs in-process).
    # asyncio.wait_for at the route level cannot interrupt it — the timeout only
    # kicks in at the next await point (search_chunks). If you swap in a remote
    # embedding provider, wrap embed_query in loop.run_in_executor() to make it
    # cancellable.
    with TimingContext() as embed_t:
        embedding = provider.embed_query(query_text)
    log.info(EVT_QUERY_EMBEDDED, latency_ms=embed_t.elapsed_ms, query_length=len(query_text))

    with TimingContext() as search_t:
        candidates = await search_chunks(
            embedding, pool, settings.taxonomy_version, settings.search_top_k
        )
    log.info(EVT_VECTOR_SEARCH, latency_ms=search_t.elapsed_ms, candidates=len(candidates))

    if not candidates:
        raise IndexNotFoundError(settings.taxonomy_version)

    with TimingContext() as rerank_t:
        biases = rerank(candidates, settings.similarity_threshold, settings.return_top_k)
    log.info(EVT_RERANKED, latency_ms=rerank_t.elapsed_ms, returned=len(biases))

    total_ms = int((time.monotonic() - t_total) * 1000)
    log.info(EVT_COMPLETED, latency_ms=total_ms)

    scores = [b.retrieval_score for b in biases]
    surviving = len([c for c in candidates if c.retrieval_score >= settings.similarity_threshold])

    meta = RetrievalMetadata(
        retrieval_id=request_id,
        embedding_model=provider.model_name,
        taxonomy_version=settings.taxonomy_version,
        query_strategy=settings.query_strategy,
        query_length=len(query_text),
        embedding_latency_ms=embed_t.elapsed_ms,
        search_latency_ms=search_t.elapsed_ms,
        rerank_latency_ms=rerank_t.elapsed_ms,
        total_latency_ms=total_ms,
        candidate_chunks=len(candidates),
        surviving_chunks=surviving,
        returned_biases=len(biases),
        top_retrieval_score=max(scores) if scores else None,
        avg_retrieval_score=sum(scores) / len(scores) if scores else None,
        threshold_used=settings.similarity_threshold,
    )

    return biases, meta
