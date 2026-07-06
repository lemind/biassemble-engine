import asyncio

import structlog

from src.config import settings
from src.schemas.internal import CandidateChunk
from src.selection.base import StrategyMetadata
from src.selection.vector_only import VectorOnlyStrategy

log = structlog.get_logger()


class NLIUnionStrategy:
    """Union-boost selection: NLI + vector search run concurrently, combined via three-gate OR.

    Combiner is wired in Phase 6 (T018-T021). Until then, NLI gate alone admits biases.
    """

    def __init__(self, nli_classifier, combiner, vector_strategy: VectorOnlyStrategy, hypotheses=None) -> None:
        self._nli_classifier = nli_classifier
        self._combiner = combiner
        self._vector_strategy = vector_strategy
        self._hypotheses: list[tuple[str, str]] | None = hypotheses

    async def select(
        self, story: str, story_analysis=None
    ) -> tuple[dict[str, float], list[CandidateChunk], StrategyMetadata]:
        if not self._hypotheses:
            raise NotImplementedError("Hypotheses not loaded — Phase 5 (T017)")

        loop = asyncio.get_running_loop()

        # NLI runs in thread pool (CPU-bound); vector search runs async — concurrent.
        nli_result, (vector_scores, candidates, _) = await asyncio.gather(
            loop.run_in_executor(None, self._nli_classifier.classify, story, self._hypotheses),
            self._vector_strategy.select(story, story_analysis),
        )

        log.info(
            "nli_classification_done",
            latency_ms=round(nli_result.latency_ms, 1),
            truncated=nli_result.truncated_premise,
        )

        # Combiner not yet wired (Phase 6) — admit on NLI gate alone.
        scores = {bid: s for bid, s in nli_result.scores.items() if s >= settings.nli_gate}

        return scores, candidates, StrategyMetadata(
            selection_strategy="nli_union",
            nli_latency_ms=nli_result.latency_ms,
            truncated_premise=nli_result.truncated_premise,
            nli_scores=nli_result.scores,
            vector_scores=vector_scores,
        )
