import asyncio

import structlog

from src.llm.generator import LLMGenerator
from src.llm.prompt import SYSTEM, BiasCandidate, build_user_message, parse_biases
from src.schemas.internal import CandidateChunk
from src.selection.base import StrategyMetadata
from src.selection.vector_only import VectorOnlyStrategy

log = structlog.get_logger()


class LLMUnionStrategy:
    """Union-boost selection: generative LLM + vector search run concurrently,
    combined by union-admit. Mirrors NLIUnionStrategy's concurrency pattern
    (asyncio.gather + run_in_executor for the CPU-bound model call).

    source/sources tagging and per-signal score threading into StrategyMetadata is
    Phase 5 (T013-T017) — this phase only needs a correct admitted set for ranking.
    """

    def __init__(
        self,
        generator: LLMGenerator,
        catalog: list[tuple[str, str, list[str]]],
        vector_strategy: VectorOnlyStrategy,
    ) -> None:
        self._generator = generator
        self._catalog = catalog
        self._valid_ids = {bid for bid, _, _ in catalog}
        self._vector_strategy = vector_strategy

    def _run_llm(self, story: str) -> list[BiasCandidate]:
        """Runs in a thread-pool executor — synchronous, CPU-bound. Never raises:
        an inference failure degrades to no LLM-sourced biases (FR-007), same
        tolerance as malformed model output."""
        try:
            user = build_user_message(story, self._catalog)
            raw = self._generator.generate(SYSTEM, user)
        except Exception as exc:
            log.warning("llm_generate_failed", error=str(exc))
            return []
        return parse_biases(raw, self._valid_ids)

    async def select(
        self, story: str, story_analysis=None
    ) -> tuple[dict[str, float], list[CandidateChunk], StrategyMetadata]:
        loop = asyncio.get_running_loop()

        # LLM call is synchronous CPU-bound work — dispatch via run_in_executor so it
        # doesn't block the event loop for other requests (nli_union.py:46 pattern).
        # Do NOT call generator.generate()/self._run_llm() directly in this async path.
        llm_candidates, (vector_scores, candidates, _) = await asyncio.gather(
            loop.run_in_executor(None, self._run_llm, story),
            self._vector_strategy.select(story, story_analysis),
        )

        log.info("llm_selection_done", admitted=len(llm_candidates))

        # Union-admit: LLM-named OR vector already admitted (vector_scores is
        # pre-filtered by similarity_threshold inside VectorOnlyStrategy.select).
        # Score: LLM confidence when present, else the vector score (research R5) —
        # the two signals are never blended onto one scale.
        scores: dict[str, float] = dict(vector_scores)
        for cand in llm_candidates:
            scores[cand.bias_id] = cand.confidence

        return scores, candidates, StrategyMetadata(selection_strategy="llm_union")
