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


def _source_rank(sources: list[str]) -> int:
    """Rank for the deterministic sort / top-K trim: most-corroborated first.
    Both signals (0) > vector-only (1) > llm-only (2). Vector-only outranks llm-only
    because vector is the precise, reliable backbone — when the top-K limit forces a
    choice, keep vector's confident hits and let the LLM's extra guesses fill the
    remaining slots. This does NOT cost blind-spot saves: in the novel-domain / hard
    cases the LLM exists for, vector is empty, so llm-only biases have no vector hits
    to compete with and are all admitted. (Ranking llm-only first instead silently
    dropped vector's correct hits on ordinary stories — caught by the confirmation
    harness run, positive recall 0.667 -> 0.500.)"""
    if len(sources) == 2:
        return 0
    if "vector" in sources:
        return 1
    return 2


def rank_and_trim(
    llm_map: dict[str, float], vector_scores: dict[str, float], top_k: int
) -> tuple[list[str], dict[str, list[str]]]:
    """Union-admit + deterministic total sort, trimmed to top_k. `source` is an ARRAY
    of the methods that found each bias — ["vector"], ["llm"], or ["vector", "llm"] —
    NOT a collapsed "both" string, so a consumer can see each contributing signal.
    Extracted as a standalone function so the local eval harness ranks identically to
    production. Returns (ordered bias_ids, bias_id -> source list)."""
    source: dict[str, list[str]] = {}
    for bid in vector_scores:
        source.setdefault(bid, []).append("vector")
    for bid in llm_map:
        source.setdefault(bid, []).append("llm")

    def _sort_key(bid: str) -> tuple:
        return (
            _source_rank(source[bid]),
            -llm_map.get(bid, -1.0),
            -vector_scores.get(bid, -1.0),
            bid,
        )

    ordered = sorted(source, key=_sort_key)[:top_k]
    return ordered, {bid: source[bid] for bid in ordered}


class LLMUnionStrategy:
    """Union selection: a generative LLM and vector search run CONCURRENTLY, each
    across the full 38-bias catalog, then their results are unioned. Neither filters
    the other's inputs — the LLM sees all bias_ids (not a vector-narrowed subset), so
    it can name a bias in a domain vector search is blind to (proven on space/deep-sea/
    archaeology stories where vector returned nothing). No neutral-gate: vector finding
    nothing means "not a domain vector covers," not "no bias" — the final neutral call
    belongs to the downstream assessment LLM (biassemble-core), not here. See ADR-003.
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
        tolerance as malformed model output. The LLM is shown ALL catalog ids.
        Returns (candidates, truncated, latency_ms)."""
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

        # LLM (CPU-bound, thread pool) and vector search run concurrently — neither
        # depends on the other's output now that narrowing is gone (nli_union.py:46
        # pattern). Do NOT call self._run_llm() directly in this async path.
        llm_result, vector_result = await asyncio.gather(
            loop.run_in_executor(None, self._run_llm, story),
            self._vector_strategy.select(story, story_analysis),
        )
        llm_candidates, truncated_story, llm_latency_ms = llm_result
        vector_scores, candidates, _ = vector_result

        # Union of the two independent searches. llm_map/vector_scores stay separate —
        # never blended onto one scale (research R5).
        llm_map: dict[str, float] = {cand.bias_id: cand.confidence for cand in llm_candidates}
        top_k_ids, sources = rank_and_trim(llm_map, vector_scores, settings.llm_union_top_k)

        scores: dict[str, float] = {
            bid: (llm_map[bid] if bid in llm_map else vector_scores[bid]) for bid in top_k_ids
        }

        from_both = sum(1 for s in sources.values() if len(s) == 2)
        from_llm = sum(1 for s in sources.values() if s == ["llm"])
        from_vector = sum(1 for s in sources.values() if s == ["vector"])
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
