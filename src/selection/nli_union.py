from src.schemas.internal import CandidateChunk
from src.selection.base import StrategyMetadata


class NLIUnionStrategy:
    """Union-boost selection: NLI + vector search run concurrently, combined via three-gate OR.

    Implemented in Phase 4 (T011–T013). Constructor accepts None for both args until
    NLIClassifier and combiner exist.
    """

    def __init__(self, nli_classifier, combiner) -> None:
        self._nli_classifier = nli_classifier
        self._combiner = combiner

    async def select(
        self, story: str, story_analysis=None
    ) -> tuple[dict[str, float], list[CandidateChunk], StrategyMetadata]:
        raise NotImplementedError("NLIUnionStrategy not yet implemented — Phase 4 (T011-T013)")
