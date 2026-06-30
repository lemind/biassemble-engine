from pathlib import Path

from src.indexing.chunk_builder import build_chunks
from src.indexing.sources.base import RawDocument

TAXONOMY_VERSION = "2026-06-28"


def _make_docs(bias_id: str, display_name: str | None = None) -> list[RawDocument]:
    """Build a valid set of 5 RawDocuments for one bias, as normalizer would produce."""
    name = display_name or bias_id.replace("_", " ").title()
    sections = ["definition", "examples", "indicators", "false_positives", "related_biases"]
    return [
        RawDocument(
            bias_id=bias_id,
            chunk_type=section,
            text=f"Text for {section}.",
            source="taxonomy",
            metadata={"source_file": f"{bias_id}.md", "display_name": name},
        )
        for section in sections
    ]


def test_each_bias_produces_five_chunks():
    chunks = build_chunks(_make_docs("confirmation_bias"), TAXONOMY_VERSION)
    assert len(chunks) == 5


def test_bias_id_matches_filename_stem():
    chunks = build_chunks(_make_docs("confirmation_bias"), TAXONOMY_VERSION)
    for chunk in chunks:
        stem = Path(chunk.metadata["source_file"]).stem
        assert chunk.bias_id == stem


def test_chunk_text_prefixed_with_bias_name():
    chunks = build_chunks(_make_docs("confirmation_bias", "Confirmation Bias"), TAXONOMY_VERSION)
    for chunk in chunks:
        assert chunk.chunk_text.startswith("Confirmation Bias")


def test_full_document_has_all_six_fields():
    chunks = build_chunks(_make_docs("confirmation_bias"), TAXONOMY_VERSION)
    fd = chunks[0].full_document
    assert fd.name
    assert fd.definition
    assert fd.examples
    assert fd.indicators
    assert fd.false_positives
    assert fd.related_biases


def test_false_positives_present_and_non_empty():
    chunks = build_chunks(_make_docs("anchoring_bias"), TAXONOMY_VERSION)
    fd = chunks[0].full_document
    assert fd.false_positives != ""


def test_chunk_hash_is_sha256_hex():
    chunks = build_chunks(_make_docs("confirmation_bias"), TAXONOMY_VERSION)
    for chunk in chunks:
        assert len(chunk.chunk_hash) == 64
        assert all(c in "0123456789abcdef" for c in chunk.chunk_hash)


def test_same_full_document_instance_shared_across_chunks():
    """Consistency rule: all 5 chunks for a bias must share the exact same object."""
    chunks = build_chunks(_make_docs("confirmation_bias"), TAXONOMY_VERSION)
    first = chunks[0].full_document
    assert all(c.full_document is first for c in chunks)


def test_hash_differs_across_taxonomy_versions():
    docs = _make_docs("confirmation_bias")
    hashes_v1 = {c.chunk_hash for c in build_chunks(docs, "2026-06-28")}
    hashes_v2 = {c.chunk_hash for c in build_chunks(docs, "2026-07-01")}
    assert hashes_v1.isdisjoint(hashes_v2)


def test_multiple_biases_all_chunks_present():
    docs = _make_docs("confirmation_bias") + _make_docs("anchoring_bias")
    chunks = build_chunks(docs, TAXONOMY_VERSION)
    assert len(chunks) == 10
    assert {c.bias_id for c in chunks} == {"confirmation_bias", "anchoring_bias"}


def test_chunk_type_is_semantic_constant():
    chunks = build_chunks(_make_docs("confirmation_bias"), TAXONOMY_VERSION)
    types = {c.chunk_type for c in chunks}
    assert types == {
        "semantic_definition",
        "semantic_example",
        "semantic_indicator",
        "semantic_false_positive",
        "semantic_related",
    }


def test_source_section_is_human_readable():
    chunks = build_chunks(_make_docs("confirmation_bias"), TAXONOMY_VERSION)
    sections = {c.source_section for c in chunks}
    assert sections == {"Definition", "Examples", "Indicators", "False Positives", "Related Biases"}


def test_chunk_index_is_canonical_regardless_of_file_order():
    """chunk_index must reflect canonical section order, not markdown file order."""
    sections = ["related_biases", "false_positives", "indicators", "examples", "definition"]
    docs = [
        RawDocument("b", s, f"text {s}", "taxonomy", {"source_file": "b.md", "display_name": "B"})
        for s in sections
    ]
    chunks = build_chunks(docs, TAXONOMY_VERSION)
    index_by_section = {c.source_section: c.chunk_index for c in chunks}
    assert index_by_section["Definition"] == 0
    assert index_by_section["Examples"] == 1
    assert index_by_section["Indicators"] == 2
    assert index_by_section["False Positives"] == 3
    assert index_by_section["Related Biases"] == 4


def test_derive_name_fallback_when_no_display_name_in_metadata():
    """Chunks built from docs without display_name in metadata use the derived name."""
    docs = [
        RawDocument("sunk_cost_fallacy", s, f"text {s}", "taxonomy", {"source_file": "sunk_cost_fallacy.md"})
        for s in ["definition", "examples", "indicators", "false_positives", "related_biases"]
    ]
    chunks = build_chunks(docs, TAXONOMY_VERSION)
    assert chunks[0].full_document.name == "Sunk Cost Fallacy"
