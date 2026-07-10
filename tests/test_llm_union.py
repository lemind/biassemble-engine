"""LLMUnionStrategy integration tests (T010). asyncio_mode=auto — no decorator needed.

Generator is stubbed (no real model load); vector strategy is stubbed so these tests
isolate the LLM-admission and union-combine paths.
"""
from unittest.mock import MagicMock

from src.selection.llm_union import LLMUnionStrategy

CATALOG = [
    ("confirmation_bias", "Confirmation Bias", ["reads only agreeing sources"]),
    ("sunk_cost_fallacy", "Sunk Cost Fallacy", ["keeps going because of past investment"]),
]


class _StubVectorStrategy:
    """No vector-admitted biases, empty candidates — isolates the LLM path."""

    async def select(self, story, story_analysis=None):
        return {}, [], None


class _VectorWithHit:
    async def select(self, story, story_analysis=None):
        return {"confirmation_bias": 0.6}, [], None


def _make_generator(response_json: str) -> MagicMock:
    gen = MagicMock()
    gen.generate.return_value = response_json
    return gen


async def test_llm_union_admits_known_bias():
    generator = _make_generator(
        '[{"bias_id": "sunk_cost_fallacy", "confidence": 0.9, "evidence": "quote"}]'
    )
    strategy = LLMUnionStrategy(generator, CATALOG, _StubVectorStrategy())

    scores, candidates, meta = await strategy.select("a story about sunk cost")

    assert scores == {"sunk_cost_fallacy": 0.9}
    assert meta.selection_strategy == "llm_union"
    generator.generate.assert_called_once()


async def test_llm_union_neutral_story_returns_empty():
    generator = _make_generator("[]")
    strategy = LLMUnionStrategy(generator, CATALOG, _StubVectorStrategy())

    scores, candidates, meta = await strategy.select("a neutral story about a train timetable")

    assert scores == {}


async def test_llm_union_generator_exception_degrades_to_empty_not_raise():
    generator = MagicMock()
    generator.generate.side_effect = RuntimeError("model exploded")
    strategy = LLMUnionStrategy(generator, CATALOG, _StubVectorStrategy())

    scores, candidates, meta = await strategy.select("any story")

    assert scores == {}


async def test_llm_union_combines_with_vector_scores():
    generator = _make_generator(
        '[{"bias_id": "sunk_cost_fallacy", "confidence": 0.8, "evidence": "e"}]'
    )
    strategy = LLMUnionStrategy(generator, CATALOG, _VectorWithHit())

    scores, candidates, meta = await strategy.select("story")

    assert scores == {"confirmation_bias": 0.6, "sunk_cost_fallacy": 0.8}


async def test_llm_union_non_catalog_bias_id_dropped():
    generator = _make_generator('[{"bias_id": "made_up_bias", "confidence": 0.9, "evidence": "e"}]')
    strategy = LLMUnionStrategy(generator, CATALOG, _StubVectorStrategy())

    scores, candidates, meta = await strategy.select("story")

    assert scores == {}
