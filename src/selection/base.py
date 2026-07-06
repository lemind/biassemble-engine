from typing import Protocol, runtime_checkable

from src.schemas.internal import CandidateChunk


@runtime_checkable
class SelectionStrategy(Protocol):
    async def select(
        self, story: str, story_analysis=None
    ) -> tuple[dict[str, float], list[CandidateChunk]]:
        """Return (admitted_scores, raw_candidates).

        Strategy owns the full retrieval pipeline. Candidates are returned so the
        caller can build full-document responses without a second DB round-trip.
        NLIUnionStrategy uses this signature to run NLI + vector concurrently via
        asyncio.gather before either result is available to the caller.
        """
        ...
