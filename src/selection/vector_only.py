import asyncpg

from src.config import settings
from src.providers.base import EmbeddingProvider
from src.retrieval.query_builder import get_query_strategy
from src.retrieval.searcher import search_chunks
from src.schemas.internal import CandidateChunk
from src.selection.base import StrategyMetadata


class VectorOnlyStrategy:
    """Owns the full vector search pipeline.

    Uses settings.similarity_threshold (raw cosine) — not vec_gate, which is
    reserved for the combiner's normalized vector scores in Phase 6.
    """

    def __init__(self, provider: EmbeddingProvider, pool: asyncpg.Pool | None) -> None:
        self._provider = provider
        self._pool = pool

    async def select(
        self, story: str, story_analysis=None
    ) -> tuple[dict[str, float], list[CandidateChunk], StrategyMetadata]:
        """Embed story, run vector search, apply similarity_threshold. Returns (scores, candidates, meta)."""
        query_strategy = get_query_strategy(settings.query_strategy)
        query_text = query_strategy.build(story, story_analysis)
        embedding = self._provider.embed_query(query_text)
        candidates = await search_chunks(
            embedding, self._pool, settings.taxonomy_version, settings.search_top_k
        )
        scores: dict[str, float] = {}
        for chunk in candidates:
            if chunk.retrieval_score >= settings.similarity_threshold:
                bid = chunk.bias_id
                if bid not in scores or chunk.retrieval_score > scores[bid]:
                    scores[bid] = chunk.retrieval_score
        return scores, candidates, StrategyMetadata(selection_strategy="vector_only")
