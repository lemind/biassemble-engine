"""T012: selection_strategy flag safety (FR-004).

vector_only and nli_union response shape must be unchanged by this feature
(the additive `source` field is present but null — contract v3 explicitly
allows "absent / null" for byte-compat with v1/v2 clients); llm_union must
produce a valid result; an unknown flag value must raise at Settings()
construction, never silently fall back to a default.
"""
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.app import app
from src.config import Settings, settings
from src.nli.classifier import NLIResult
from src.schemas.internal import CandidateChunk, FullBiasDocument
from src.selection.llm_union import LLMUnionStrategy
from src.selection.nli_union import NLIUnionStrategy
from src.selection.vector_only import VectorOnlyStrategy

STORY_PAYLOAD = {"story": "Marcus bought NovaTech at $142 and refuses to sell."}
HEADERS = {"Authorization": f"Bearer {settings.rag_api_key}"}

CATALOG = [("confirmation_bias", "Confirmation Bias", ["reads only agreeing sources"])]


def _mock_provider() -> MagicMock:
    m = MagicMock()
    m.model_name = "all-MiniLM-L6-v2"
    m.embed_query.return_value = [0.1] * 384
    return m


def _mock_candidate() -> CandidateChunk:
    doc = FullBiasDocument(
        name="Confirmation Bias", definition="d", examples="e",
        indicators="i", false_positives="fp", related_biases="rb",
    )
    return CandidateChunk(
        bias_id="confirmation_bias", chunk_type="semantic_definition",
        source_section="Definition", source="taxonomy",
        chunk_text="...", full_document=doc, retrieval_score=0.9,
    )


def _client_for(monkeypatch, strategy, empty_search=True):
    if empty_search:
        async def fake_search(*_a, **_kw):
            return [_mock_candidate()]
        monkeypatch.setattr("src.selection.vector_only.search_chunks", fake_search)

    @asynccontextmanager
    async def fake_lifespan(a):
        a.state.provider = _mock_provider()
        a.state.pool = MagicMock()
        a.state.roster = []
        a.state.selection_strategy = strategy
        yield

    monkeypatch.setattr(app.router, "lifespan_context", fake_lifespan)
    return TestClient(app).__enter__()


def _post(client):
    resp = client.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    client.__exit__(None, None, None)
    return resp


def test_vector_only_response_shape_unchanged(monkeypatch):
    strategy = VectorOnlyStrategy(_mock_provider(), MagicMock())
    resp = _post(_client_for(monkeypatch, strategy))

    assert resp.status_code == 200
    bias = resp.json()["biases"][0]
    assert bias["source"] is None
    assert set(bias) == {
        "id", "name", "retrieval_score", "definition",
        "examples", "indicators", "false_positives", "related_biases", "source",
    }


def test_nli_union_response_shape_unchanged(monkeypatch):
    nli_classifier = MagicMock()
    nli_classifier.classify.return_value = NLIResult(
        scores={"confirmation_bias": 0.95},
        raw_scores={},
        latency_ms=5.0,
        truncated_premise=False,
    )
    strategy = NLIUnionStrategy(
        nli_classifier,
        combiner=None,
        vector_strategy=VectorOnlyStrategy(_mock_provider(), MagicMock()),
        hypotheses=[("confirmation_bias", "The narrator seeks confirming evidence.")],
        hypotheses_version="v1",
    )
    resp = _post(_client_for(monkeypatch, strategy))

    assert resp.status_code == 200
    bias = resp.json()["biases"][0]
    assert bias["source"] is None
    assert set(bias) == {
        "id", "name", "retrieval_score", "definition",
        "examples", "indicators", "false_positives", "related_biases", "source",
    }


def test_llm_union_produces_valid_result(monkeypatch):
    generator = MagicMock()
    generator.context_tokens = 4096
    generator.max_output_tokens = 512
    generator.count_tokens.return_value = 10
    generator.generate.return_value = (
        '[{"bias_id": "confirmation_bias", "confidence": 0.9, "evidence": "quote"}]'
    )
    strategy = LLMUnionStrategy(
        generator, CATALOG, VectorOnlyStrategy(_mock_provider(), MagicMock())
    )
    resp = _post(_client_for(monkeypatch, strategy))

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["biases"]) == 1
    assert data["biases"][0]["id"] == "confirmation_bias"
    generator.generate.assert_called_once()


def test_unknown_selection_strategy_raises_not_silently_defaults():
    with pytest.raises(ValidationError):
        Settings(selection_strategy="not_a_real_strategy")
