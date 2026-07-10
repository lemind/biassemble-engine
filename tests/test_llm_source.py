"""T018: per-bias source attribution (vector/llm/both), response ↔ metadata consistency.

Stub vector strategy returns candidate chunks for all three biases (so no DB
hydration path is exercised — that's retriever.py's job, out of scope here) but
only admits two of them via `scores`, isolating the three source categories:
confirmation_bias (vector-admitted + LLM-named) → both
anchoring_bias    (vector-admitted only)        → vector
sunk_cost_fallacy (LLM-named only)              → llm
"""
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.api.app import app
from src.config import settings
from src.schemas.internal import CandidateChunk, FullBiasDocument
from src.selection.llm_union import LLMUnionStrategy

STORY_PAYLOAD = {"story": "Marcus refuses to sell NovaTech despite mounting losses."}
HEADERS = {"Authorization": f"Bearer {settings.rag_api_key}"}

CATALOG = [
    ("confirmation_bias", "Confirmation Bias", ["i"]),
    ("sunk_cost_fallacy", "Sunk Cost Fallacy", ["i"]),
    ("anchoring_bias", "Anchoring Bias", ["i"]),
]


def _chunk(bias_id: str, name: str, score: float) -> CandidateChunk:
    doc = FullBiasDocument(
        name=name, definition="d", examples="e",
        indicators="i", false_positives="fp", related_biases="rb",
    )
    return CandidateChunk(
        bias_id=bias_id, chunk_type="semantic_definition", source_section="Definition",
        source="taxonomy", chunk_text="...", full_document=doc, retrieval_score=score,
    )


class _StubVectorStrategy:
    async def select(self, story, story_analysis=None):
        candidates = [
            _chunk("confirmation_bias", "Confirmation Bias", 0.8),
            _chunk("anchoring_bias", "Anchoring Bias", 0.55),
            _chunk("sunk_cost_fallacy", "Sunk Cost Fallacy", 0.1),
        ]
        scores = {"confirmation_bias": 0.8, "anchoring_bias": 0.55}
        return scores, candidates, None


def _make_generator() -> MagicMock:
    generator = MagicMock()
    generator.context_tokens = 4096
    generator.max_output_tokens = 512
    generator.count_tokens.return_value = 10
    generator.generate.return_value = (
        '[{"bias_id": "sunk_cost_fallacy", "confidence": 0.9, "evidence": "e"},'
        ' {"bias_id": "confirmation_bias", "confidence": 0.7, "evidence": "e"}]'
    )
    return generator


def _make_client(monkeypatch):
    strategy = LLMUnionStrategy(_make_generator(), CATALOG, _StubVectorStrategy())

    @asynccontextmanager
    async def fake_lifespan(a):
        provider = MagicMock()
        provider.model_name = "all-MiniLM-L6-v2"
        a.state.provider = provider
        a.state.pool = MagicMock()
        a.state.roster = []
        a.state.selection_strategy = strategy
        yield

    monkeypatch.setattr(app.router, "lifespan_context", fake_lifespan)
    return TestClient(app).__enter__()


def test_source_tags_correct_for_vector_llm_and_both(monkeypatch):
    client = _make_client(monkeypatch)
    resp = client.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    client.__exit__(None, None, None)

    assert resp.status_code == 200
    data = resp.json()
    by_id = {b["id"]: b for b in data["biases"]}

    assert by_id["confirmation_bias"]["source"] == "both"
    assert by_id["anchoring_bias"]["source"] == "vector"
    assert by_id["sunk_cost_fallacy"]["source"] == "llm"


def test_llm_and_vector_scores_reported_separately_not_blended(monkeypatch):
    client = _make_client(monkeypatch)
    resp = client.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    client.__exit__(None, None, None)

    data = resp.json()
    # Raw per-signal maps are separate top-level fields — never merged onto one scale.
    assert data["llm_scores"] == {"sunk_cost_fallacy": 0.9, "confirmation_bias": 0.7}
    assert data["vector_scores"] == {"confirmation_bias": 0.8, "anchoring_bias": 0.55}
