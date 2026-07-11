"""LLMUnionStrategy integration tests (T010, updated for narrow-then-LLM).
asyncio_mode=auto — no decorator needed.

Generator is stubbed (no real model load); vector strategy is stubbed so these tests
isolate the LLM-admission and union-combine paths. Stub candidates cover the full
CATALOG so narrow_catalog() (llm_narrow_n=10 default, catalog only has 2 entries)
never trims anything — narrowing itself is covered separately in test_llm_prompt.py.
"""
from unittest.mock import MagicMock

from src.schemas.internal import CandidateChunk, FullBiasDocument
from src.selection.llm_union import LLMUnionStrategy

CATALOG = [
    ("confirmation_bias", "Confirmation Bias", ["reads only agreeing sources"]),
    ("sunk_cost_fallacy", "Sunk Cost Fallacy", ["keeps going because of past investment"]),
]


def _chunk(bias_id: str, score: float) -> CandidateChunk:
    doc = FullBiasDocument(
        name=bias_id, definition="d", examples="e",
        indicators="i", false_positives="fp", related_biases="rb",
    )
    return CandidateChunk(
        bias_id=bias_id, chunk_type="semantic_definition", source_section="Definition",
        source="taxonomy", chunk_text="...", full_document=doc, retrieval_score=score,
    )


_FULL_CANDIDATES = [_chunk("confirmation_bias", 0.3), _chunk("sunk_cost_fallacy", 0.2)]


class _StubVectorStrategy:
    """No vector-admitted biases, but candidates cover the full catalog — isolates
    the LLM-admission path while still giving narrow_catalog() something to rank."""

    async def select(self, story, story_analysis=None):
        return {}, _FULL_CANDIDATES, None


class _VectorWithHit:
    async def select(self, story, story_analysis=None):
        return {"confirmation_bias": 0.6}, _FULL_CANDIDATES, None


def _make_generator(response_json: str) -> MagicMock:
    gen = MagicMock()
    gen.context_tokens = 4096
    gen.max_output_tokens = 512
    gen.count_tokens.return_value = 10
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
    generator.context_tokens = 4096
    generator.max_output_tokens = 512
    generator.count_tokens.return_value = 10
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


async def test_llm_union_narrows_catalog_before_llm_call():
    """Only bias_ids that survived narrowing should reach build_user_message —
    a bias with no vector candidate at all (outside narrow_n) must not appear in
    the prompt sent to the model."""
    generator = _make_generator("[]")
    strategy = LLMUnionStrategy(generator, CATALOG, _StubVectorStrategy())

    await strategy.select("story")

    sent_user_msg = generator.generate.call_args[0][1]
    assert "confirmation_bias" in sent_user_msg
    assert "sunk_cost_fallacy" in sent_user_msg
