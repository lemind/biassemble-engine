import asyncio
import time

import structlog

from src.config import settings
from src.llm.generator import LLMGenerator
from src.llm.prompt import (
    SYSTEM,
    BiasCandidate,
    build_user_message,
    fit_story_to_budget,
    parse_biases,
)
from src.schemas.internal import CandidateChunk
from src.selection.base import StrategyMetadata
from src.selection.vector_only import VectorOnlyStrategy

log = structlog.get_logger()

# Deterministic total sort (research R5, data-model.md): source rank first (both
# beats llm beats vector-only — most corroborated evidence wins), then llm
# confidence desc, then vector score desc, then bias_id asc as the final
# tie-break so re-running the same story always yields the same admitted set
# (FR-011). Governs *which* bias_ids survive the top-K trim; final display
# order within that trimmed set still passes through reranker.py's existing
# (shared, out-of-scope-for-this-feature) single-key numeric sort.
_SOURCE_RANK = {"both": 0, "llm": 1, "vector": 2}


class LLMUnionStrategy:
    """Union-boost selection: generative LLM + vector search run concurrently,
    combined by union-admit. Mirrors NLIUnionStrategy's concurrency pattern
    (asyncio.gather + run_in_executor for the CPU-bound model call).
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

    def _run_llm(self, story: str) -> tuple[list[BiasCandidate], bool, float]:
        """Runs in a thread-pool executor — synchronous, CPU-bound. Never raises:
        an inference failure degrades to no LLM-sourced biases (FR-007), same
        tolerance as malformed model output. Returns (candidates, truncated, latency_ms)."""
        t0 = time.monotonic()
        try:
            fitted_story, truncated = fit_story_to_budget(self._generator, story, self._catalog)
            user = build_user_message(fitted_story, self._catalog)
            raw = self._generator.generate(SYSTEM, user)
        except Exception as exc:
            log.warning("llm_generate_failed", error=str(exc))
            return [], False, (time.monotonic() - t0) * 1000
        if settings.llm_log_raw:
            log.debug("llm_raw_output", raw=raw)
        return parse_biases(raw, self._valid_ids), truncated, (time.monotonic() - t0) * 1000

    async def select(
        self, story: str, story_analysis=None
    ) -> tuple[dict[str, float], list[CandidateChunk], StrategyMetadata]:
        loop = asyncio.get_running_loop()

        # LLM call is synchronous CPU-bound work — dispatch via run_in_executor so it
        # doesn't block the event loop for other requests (nli_union.py:46 pattern).
        # Do NOT call generator.generate()/self._run_llm() directly in this async path.
        llm_result, vector_result = await asyncio.gather(
            loop.run_in_executor(None, self._run_llm, story),
            self._vector_strategy.select(story, story_analysis),
        )
        llm_candidates, truncated_story, llm_latency_ms = llm_result
        vector_scores, candidates, _ = vector_result

        # Union-admit: LLM-named OR vector already admitted (vector_scores is
        # pre-filtered by similarity_threshold inside VectorOnlyStrategy.select).
        # llm_map/vector_scores are kept separate throughout — never blended onto
        # one scale (research R5).
        llm_map: dict[str, float] = {cand.bias_id: cand.confidence for cand in llm_candidates}
        source: dict[str, str] = {}
        for bid in vector_scores:
            source[bid] = "vector"
        for bid in llm_map:
            source[bid] = "both" if bid in source else "llm"

        def _sort_key(bid: str) -> tuple:
            return (
                _SOURCE_RANK[source[bid]],
                -llm_map.get(bid, -1.0),
                -vector_scores.get(bid, -1.0),
                bid,
            )

        top_k_ids = sorted(source, key=_sort_key)[: settings.return_top_k]

        scores: dict[str, float] = {
            bid: (llm_map[bid] if bid in llm_map else vector_scores[bid]) for bid in top_k_ids
        }
        sources = {bid: source[bid] for bid in top_k_ids}

        from_llm = sum(1 for s in sources.values() if s == "llm")
        from_vector = sum(1 for s in sources.values() if s == "vector")
        from_both = sum(1 for s in sources.values() if s == "both")
        log.info(
            "llm_selection_done",
            admitted=len(top_k_ids),
            from_llm=from_llm,
            from_vector=from_vector,
            from_both=from_both,
            llm_latency_ms=round(llm_latency_ms, 1),
        )
        for bid in top_k_ids:
            log.info(
                "bias_admitted",
                bias_id=bid,
                source=sources[bid],
                llm_score=llm_map.get(bid),
                vec_score=vector_scores.get(bid),
            )

        return scores, candidates, StrategyMetadata(
            selection_strategy="llm_union",
            llm_scores=llm_map,
            vector_scores=vector_scores,
            sources=sources,
            llm_latency_ms=llm_latency_ms,
            truncated_story=truncated_story,
        )
