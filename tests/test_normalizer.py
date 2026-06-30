import logging

import pytest

from src.indexing.normalizer import normalize
from src.indexing.sources.base import RawDocument


def _make_docs(bias_id: str, source_file: str = "test.md") -> list[RawDocument]:
    sections = ["definition", "examples", "indicators", "false_positives", "related_biases"]
    return [
        RawDocument(
            bias_id=bias_id,
            chunk_type=section,
            text=f"Text for {section}",
            source="taxonomy",
            metadata={"source_file": source_file},
        )
        for section in sections
    ]


def test_whitespace_stripped():
    base = _make_docs("b")
    base[0] = RawDocument("b", "definition", "  hello\n\n\n\nworld  ", "taxonomy", {"source_file": "test.md"})
    result = normalize(base)
    assert result[0].text == "hello\n\nworld"


def test_false_positive_alias_normalized():
    docs = [d for d in _make_docs("b") if d.chunk_type != "false_positives"]
    docs.append(RawDocument("b", "false_positive", "fp text", "taxonomy", {"source_file": "test.md"}))
    result = normalize(docs)
    chunk_types = {d.chunk_type for d in result}
    assert "false_positives" in chunk_types
    assert "false_positive" not in chunk_types


def test_example_alias_normalized():
    docs = [d for d in _make_docs("b") if d.chunk_type != "examples"]
    docs.append(RawDocument("b", "example", "ex text", "taxonomy", {"source_file": "test.md"}))
    result = normalize(docs)
    chunk_types = {d.chunk_type for d in result}
    assert "examples" in chunk_types
    assert "example" not in chunk_types


def test_missing_false_positives_raises():
    docs = [d for d in _make_docs("b") if d.chunk_type != "false_positives"]
    with pytest.raises(ValueError, match="false_positives"):
        normalize(docs)


def test_missing_definition_raises():
    docs = [d for d in _make_docs("b") if d.chunk_type != "definition"]
    with pytest.raises(ValueError, match="definition"):
        normalize(docs)


def test_duplicate_bias_id_second_source_dropped():
    docs_a = _make_docs("conf", source_file="confirmation_bias.md")
    docs_b = _make_docs("conf", source_file="confirmation_bias_v2.md")
    result = normalize(docs_a + docs_b)
    sources = {d.metadata["source_file"] for d in result}
    assert sources == {"confirmation_bias.md"}


def test_duplicate_bias_id_warns(caplog: pytest.LogCaptureFixture):
    docs_a = _make_docs("conf", source_file="a.md")
    docs_b = _make_docs("conf", source_file="b.md")
    with caplog.at_level(logging.WARNING, logger="src.indexing.normalizer"):
        normalize(docs_a + docs_b)
    assert "conf" in caplog.text


def test_valid_documents_pass_through():
    docs = _make_docs("bias_a") + _make_docs("bias_b")
    result = normalize(docs)
    assert len(result) == 10
    assert {d.bias_id for d in result} == {"bias_a", "bias_b"}
