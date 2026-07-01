import pytest

from src.retrieval.query_builder import (
    QUERY_STRATEGY_REGISTRY,
    QueryStrategy,
    RepeatedStoryStrategy,
    get_query_strategy,
)
from src.schemas.request import StoryAnalysis

STORY = "Marcus bought NovaTech at $142 and refuses to sell even though it has fallen to $40."


def test_query_strategy_is_abstract():
    with pytest.raises(TypeError):
        QueryStrategy()  # type: ignore[abstract]


def test_story_appears_twice():
    result = RepeatedStoryStrategy().build(STORY)
    assert result.count("Marcus") == 2


def test_analysis_themes_appended():
    analysis = StoryAnalysis(themes=["loss aversion", "anchoring"])
    result = RepeatedStoryStrategy().build(STORY, analysis)
    assert "Themes:" in result
    assert "loss aversion" in result


def test_analysis_beliefs_appended():
    analysis = StoryAnalysis(beliefs=["the stock will recover"])
    result = RepeatedStoryStrategy().build(STORY, analysis)
    assert "Beliefs:" in result
    assert "the stock will recover" in result


def test_analysis_claims_appended():
    analysis = StoryAnalysis(claims=["holding is rational"])
    result = RepeatedStoryStrategy().build(STORY, analysis)
    assert "Claims:" in result


def test_works_without_analysis():
    result = RepeatedStoryStrategy().build(STORY, None)
    assert result != ""
    assert "Themes:" not in result


def test_empty_analysis_fields_not_appended():
    analysis = StoryAnalysis(themes=[], beliefs=[], claims=[])
    result = RepeatedStoryStrategy().build(STORY, analysis)
    assert "Themes:" not in result
    assert "Beliefs:" not in result
    assert "Claims:" not in result


def test_story_truncated_to_100_words():
    long_story = " ".join(f"word{i}" for i in range(200))
    result = RepeatedStoryStrategy().build(long_story)
    assert "word99" in result
    assert "word100" not in result


def test_get_query_strategy_returns_correct_instance():
    assert isinstance(get_query_strategy("repeated_story"), RepeatedStoryStrategy)


def test_get_query_strategy_unknown_raises():
    with pytest.raises(ValueError, match="Unknown query strategy"):
        get_query_strategy("nonexistent")


def test_registry_contains_repeated_story():
    assert "repeated_story" in QUERY_STRATEGY_REGISTRY
