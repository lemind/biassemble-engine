import pytest

from src.schemas.internal import CandidateChunk, FullBiasDocument
from src.retrieval.reranker import rerank

THRESHOLD = 0.45


def _doc(name: str = "Bias Name") -> FullBiasDocument:
    return FullBiasDocument(
        name=name,
        definition="def",
        examples="ex",
        indicators="ind",
        false_positives="fp",
        related_biases="rb",
    )


def _chunk(
    bias_id: str,
    score: float,
    source: str = "taxonomy",
    chunk_type: str = "semantic_definition",
) -> CandidateChunk:
    return CandidateChunk(
        bias_id=bias_id,
        chunk_type=chunk_type,
        source_section="Definition",
        source=source,
        chunk_text=f"{bias_id} chunk text",
        full_document=_doc(bias_id.replace("_", " ").title()),
        retrieval_score=score,
    )


def test_below_threshold_chunks_dropped():
    chunks = [_chunk("confirmation_bias", 0.3), _chunk("anchoring_bias", 0.6)]
    result = rerank(chunks, THRESHOLD, return_top_k=5)
    assert len(result) == 1
    assert result[0].bias_id == "anchoring_bias"


def test_all_below_threshold_returns_empty():
    chunks = [_chunk("confirmation_bias", 0.1), _chunk("anchoring_bias", 0.2)]
    assert rerank(chunks, THRESHOLD, return_top_k=5) == []


def test_sorted_descending_by_score():
    chunks = [
        _chunk("anchoring_bias", 0.5),
        _chunk("confirmation_bias", 0.8),
        _chunk("sunk_cost_fallacy", 0.65),
    ]
    result = rerank(chunks, THRESHOLD, return_top_k=5)
    scores = [r.retrieval_score for r in result]
    assert scores == sorted(scores, reverse=True)


def test_no_duplicate_bias_id():
    chunks = [
        _chunk("confirmation_bias", 0.8),
        _chunk("confirmation_bias", 0.6),
        _chunk("confirmation_bias", 0.7),
    ]
    result = rerank(chunks, THRESHOLD, return_top_k=5)
    assert len(result) == 1


def test_max_score_wins_per_bias():
    chunks = [
        _chunk("confirmation_bias", 0.6),
        _chunk("confirmation_bias", 0.9),
        _chunk("confirmation_bias", 0.7),
    ]
    result = rerank(chunks, THRESHOLD, return_top_k=5)
    assert result[0].retrieval_score == 0.9


def test_return_top_k_respected():
    chunks = [_chunk(f"bias_{i}", 0.5 + i * 0.01) for i in range(10)]
    result = rerank(chunks, THRESHOLD, return_top_k=3)
    assert len(result) == 3


def test_sources_list_populated():
    chunks = [
        _chunk("confirmation_bias", 0.8, source="taxonomy"),
        _chunk("confirmation_bias", 0.75, source="secondary"),
    ]
    result = rerank(chunks, THRESHOLD, return_top_k=5)
    assert "taxonomy" in result[0].sources
    assert "secondary" in result[0].sources


def test_sources_list_no_duplicates():
    chunks = [
        _chunk("confirmation_bias", 0.8, source="taxonomy"),
        _chunk("confirmation_bias", 0.75, source="taxonomy"),
    ]
    result = rerank(chunks, THRESHOLD, return_top_k=5)
    assert result[0].sources.count("taxonomy") == 1


def test_full_document_fields_populated():
    result = rerank([_chunk("confirmation_bias", 0.8)], THRESHOLD, return_top_k=5)
    r = result[0]
    assert r.definition == "def"
    assert r.examples == "ex"
    assert r.indicators == "ind"
    assert r.false_positives == "fp"
    assert r.related_biases == "rb"


def test_matched_chunk_type_set():
    chunk = _chunk("confirmation_bias", 0.8, chunk_type="semantic_example")
    result = rerank([chunk], THRESHOLD, return_top_k=5)
    assert result[0].matched_chunk_type == "semantic_example"
