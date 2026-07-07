"""Endpoint tests for POST /retrieve-biases.

All tests use a fake lifespan so the real SentenceTransformer model is never
loaded and no DB connection is opened. The retriever function itself is mocked
where needed so these tests only verify routing, auth, error mapping, and
response shape — not retrieval correctness.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.config import settings
from src.schemas.internal import (
    CandidateChunk,
    FullBiasDocument,
    RetrievalMetadata,
    RetrievedBias,
)
from src.schemas.response import BiasResult
from src.selection.vector_only import VectorOnlyStrategy

STORY_PAYLOAD = {"story": "Marcus bought NovaTech at $142 and refuses to sell."}
HEADERS = {"Authorization": f"Bearer {settings.rag_api_key}"}


def _make_mock_provider() -> MagicMock:
    m = MagicMock()
    m.model_name = "all-MiniLM-L6-v2"
    m.embed_query.return_value = [0.1] * 384
    return m


def _make_client(monkeypatch, pool, roster=None):
    mock_provider = _make_mock_provider()

    @asynccontextmanager
    async def fake_lifespan(a):
        a.state.provider = mock_provider
        a.state.pool = pool
        a.state.roster = roster or []
        a.state.selection_strategy = VectorOnlyStrategy(mock_provider, pool)
        yield

    monkeypatch.setattr(app.router, "lifespan_context", fake_lifespan)
    # Must use TestClient as context manager so lifespan __enter__ runs.
    return TestClient(app).__enter__()


@pytest.fixture
def client(monkeypatch):
    c = _make_client(monkeypatch, pool=MagicMock())
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def client_no_pool(monkeypatch):
    c = _make_client(monkeypatch, pool=None)
    yield c
    c.__exit__(None, None, None)


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_401_without_auth(client):
    resp = client.post("/retrieve-biases", json=STORY_PAYLOAD)
    assert resp.status_code == 401


def test_401_wrong_token(client):
    resp = client.post(
        "/retrieve-biases",
        headers={"Authorization": "Bearer wrong-token"},
        json=STORY_PAYLOAD,
    )
    assert resp.status_code == 401


# ── Infrastructure errors ─────────────────────────────────────────────────────

def test_503_database_unavailable(client_no_pool):
    resp = client_no_pool.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "database_unavailable"


def test_503_index_not_found(client, monkeypatch):
    # Vector search returns nothing → index hasn't been built for this taxonomy_version
    async def empty_search(*_a, **_kw):
        return []

    monkeypatch.setattr("src.selection.vector_only.search_chunks",empty_search)
    resp = client.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["error"] == "index_not_found"
    assert "taxonomy_version" in detail


def test_503_request_timeout(client, monkeypatch):
    import asyncio

    async def slow_search(*_a, **_kw):
        await asyncio.sleep(10)
        return []

    monkeypatch.setattr("src.selection.vector_only.search_chunks",slow_search)
    # Drop timeout to 1ms so the test doesn't actually wait
    monkeypatch.setattr("src.api.routes.retrieve.settings.request_timeout_ms", 1)
    resp = client.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "request_timeout"


# ── Happy path ────────────────────────────────────────────────────────────────

def _mock_bias() -> RetrievedBias:
    return RetrievedBias(
        bias_id="confirmation_bias",
        name="Confirmation Bias",
        retrieval_score=0.82,
        sources=["taxonomy"],
        matched_chunk_type="semantic_definition",
        matched_text="Confirmation Bias — Definition: ...",
        definition="Seeking out information that confirms existing beliefs.",
        examples="...",
        indicators="...",
        false_positives="...",
        related_biases="...",
    )


def _mock_meta() -> RetrievalMetadata:
    return RetrievalMetadata(
        retrieval_id="test-request-id",
        embedding_model="all-MiniLM-L6-v2",
        taxonomy_version=settings.taxonomy_version,
        query_strategy="repeated_story",
        query_length=100,
        embedding_latency_ms=10,
        search_latency_ms=20,
        rerank_latency_ms=1,
        total_latency_ms=31,
        candidate_chunks=10,
        surviving_chunks=3,
        returned_biases=1,
        top_retrieval_score=0.82,
        avg_retrieval_score=0.82,
        threshold_used=0.45,
    )


def test_200_happy_path_biases_present(client, monkeypatch):
    async def fake_retrieve(req, provider, pool, strategy):
        return [_mock_bias()], _mock_meta()

    monkeypatch.setattr("src.api.routes.retrieve.retriever.retrieve", fake_retrieve)

    resp = client.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["biases"]) == 1
    assert data["biases"][0]["retrieval_score"] == pytest.approx(0.82)


def test_200_request_id_echoed(client, monkeypatch):
    async def fake_retrieve(req, provider, pool, strategy):
        return [_mock_bias()], _mock_meta()

    monkeypatch.setattr("src.api.routes.retrieve.retriever.retrieve", fake_retrieve)

    resp = client.post(
        "/retrieve-biases",
        headers=HEADERS,
        json={**STORY_PAYLOAD, "request_id": "my-id-123"},
    )
    assert resp.json()["request_id"] == "test-request-id"  # echoes meta.retrieval_id


def test_200_retrieved_chunks_count(client, monkeypatch):
    async def fake_retrieve(req, provider, pool, strategy):
        return [_mock_bias()], _mock_meta()

    monkeypatch.setattr("src.api.routes.retrieve.retriever.retrieve", fake_retrieve)

    resp = client.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    assert resp.json()["retrieved_chunks"] == 10  # meta.candidate_chunks


def test_200_empty_biases_for_neutral_story(client, monkeypatch):
    # Search finds chunks but all scores are below threshold → roster fallback fires.
    # The client fixture has an empty roster, so biases == [].
    doc = FullBiasDocument(
        name="X", definition="d", examples="e",
        indicators="i", false_positives="fp", related_biases="rb",
    )
    low_score_chunk = CandidateChunk(
        bias_id="some_bias", chunk_type="semantic_definition",
        source_section="Definition", source="taxonomy",
        chunk_text="...", full_document=doc, retrieval_score=0.1,
    )

    async def low_score_search(*_a, **_kw):
        return [low_score_chunk]

    monkeypatch.setattr("src.selection.vector_only.search_chunks",low_score_search)

    resp = client.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json()["biases"] == []


def test_200_roster_fallback_when_nothing_retrieved(monkeypatch):
    # When all candidates are below threshold, retriever returns empty biases list
    # → roster fallback fires and returns pre-built roster entries.
    roster = [
        BiasResult(id="confirmation-bias", name="Confirmation Bias",
                   retrieval_score=0.0, definition="Seeking info that confirms existing beliefs.",
                   examples="", indicators="", false_positives="", related_biases=""),
        BiasResult(id="anchoring", name="Anchoring Bias",
                   retrieval_score=0.0, definition="Over-relying on the first piece of information.",
                   examples="", indicators="", false_positives="", related_biases=""),
    ]
    client = _make_client(monkeypatch, pool=MagicMock(), roster=roster)

    doc = FullBiasDocument(
        name="X", definition="d", examples="e",
        indicators="i", false_positives="fp", related_biases="rb",
    )
    below_threshold = CandidateChunk(
        bias_id="some_bias", chunk_type="semantic_definition",
        source_section="Definition", source="taxonomy",
        chunk_text="...", full_document=doc, retrieval_score=0.1,
    )

    async def low_score_search(*_a, **_kw):
        return [below_threshold]

    monkeypatch.setattr("src.selection.vector_only.search_chunks",low_score_search)

    resp = client.post("/retrieve-biases", headers=HEADERS, json=STORY_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["biases"]) == 2
    ids = {b["id"] for b in data["biases"]}
    assert ids == {"confirmation-bias", "anchoring"}
    assert data["biases"][0]["retrieval_score"] == 0.0

    client.__exit__(None, None, None)
