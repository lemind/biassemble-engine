from abc import ABC, abstractmethod

from src.schemas.request import StoryAnalysis

# Word limit for the story before repeating. Two repetitions ≈ 200 words ≈ 250 tokens,
# which fits all-MiniLM-L6-v2's 256-token window when story_analysis is None. Analysis
# fields are appended after the repetitions and may push past the limit on long stories —
# the model silently truncates, so themes/beliefs/claims lose signal in those cases.
_WORD_LIMIT = 100


class QueryStrategy(ABC):
    """Base class for query construction strategies.

    A strategy takes a story and optional analysis and produces a single
    string that gets embedded and compared against bias chunks in the DB.
    """

    @abstractmethod
    def build(self, story: str, analysis: StoryAnalysis | None = None) -> str: ...


class RepeatedStoryStrategy(QueryStrategy):
    """Truncate story to 100 words, repeat it twice, append analysis fields.

    Repeating improves recall: a short story matched against a 384-dim vector
    benefits from redundancy. Analysis fields add signal for themes/beliefs/claims
    that the raw story may not surface clearly.
    """

    def build(self, story: str, analysis: StoryAnalysis | None = None) -> str:
        truncated = " ".join(story.split()[:_WORD_LIMIT])
        parts = [truncated, truncated]

        if analysis:
            if analysis.themes:
                parts.append(f"Themes: {', '.join(analysis.themes)}")
            if analysis.beliefs:
                parts.append(f"Beliefs: {', '.join(analysis.beliefs)}")
            if analysis.claims:
                parts.append(f"Claims: {', '.join(analysis.claims)}")

        return "\n\n".join(parts)


# Registry maps settings.query_strategy values to strategy classes.
QUERY_STRATEGY_REGISTRY: dict[str, type[QueryStrategy]] = {
    "repeated_story": RepeatedStoryStrategy,
}


def get_query_strategy(name: str) -> QueryStrategy:
    """Resolve a strategy name from config to a QueryStrategy instance."""
    cls = QUERY_STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown query strategy {name!r}. "
            f"Available: {list(QUERY_STRATEGY_REGISTRY)}"
        )
    return cls()
