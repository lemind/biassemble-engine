from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.schemas.internal import CandidateChunk


@dataclass
class StrategyMetadata:
    """Optional metadata returned by a strategy alongside scores and candidates.

    NLIUnionStrategy populates all fields. VectorOnlyStrategy leaves NLI fields None.
    Retriever copies these into RetrievalMetadata for logging and response.
    """
    selection_strategy: str
    hypotheses_version: str | None = None
    nli_latency_ms: float | None = None
    truncated_premise: bool | None = None
    nli_scores: dict[str, float] | None = None
    vector_scores: dict[str, float] | None = None
    combined_scores: dict[str, float] | None = None
    # llm_union fields (spec-004) — None for vector_only/nli_union.
    llm_scores: dict[str, float] | None = None
    sources: dict[str, str] | None = None  # bias_id -> "vector" | "llm" | "both"
    llm_latency_ms: float | None = None
    truncated_story: bool | None = None


@runtime_checkable
class SelectionStrategy(Protocol):
    async def select(
        self, story: str, story_analysis=None
    ) -> tuple[dict[str, float], list[CandidateChunk], StrategyMetadata]:
        """Return (admitted_scores, raw_candidates, strategy_metadata).

        Strategy owns the full retrieval pipeline. Candidates are returned so the
        caller can build full-document responses without a second DB round-trip.
        NLIUnionStrategy uses this signature to run NLI + vector concurrently via
        asyncio.gather before either result is available to the caller.
        """
        ...
