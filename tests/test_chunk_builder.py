from pathlib import Path


from src.indexing.chunk_builder import _group_indicator_bullets, build_chunks
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
    """chunk_index must use section_base*100 formula, independent of markdown order."""
    sections = ["related_biases", "false_positives", "indicators", "examples", "definition"]
    docs = [
        RawDocument("b", s, f"text {s}", "taxonomy", {"source_file": "b.md", "display_name": "B"})
        for s in sections
    ]
    chunks = build_chunks(docs, TAXONOMY_VERSION)
    index_by_section = {c.source_section: c.chunk_index for c in chunks}
    assert index_by_section["Definition"] == 0        # section_base 0 * 100 + 0
    assert index_by_section["Examples"] == 100        # section_base 1 * 100 + 0
    assert index_by_section["Indicators"] == 200      # section_base 2 * 100 + 0
    assert index_by_section["False Positives"] == 300 # section_base 3 * 100 + 0
    assert index_by_section["Related Biases"] == 400  # section_base 4 * 100 + 0


def test_derive_name_fallback_when_no_display_name_in_metadata():
    """Chunks built from docs without display_name in metadata use the derived name."""
    docs = [
        RawDocument("sunk_cost_fallacy", s, f"text {s}", "taxonomy", {"source_file": "sunk_cost_fallacy.md"})
        for s in ["definition", "examples", "indicators", "false_positives", "related_biases"]
    ]
    chunks = build_chunks(docs, TAXONOMY_VERSION)
    assert chunks[0].full_document.name == "Sunk Cost Fallacy"


def test_multiple_example_paragraphs_produce_separate_chunks():
    """Each example paragraph (split by TaxonomySource) becomes its own chunk."""
    docs = _make_docs("confirmation_bias")
    # Replace the single examples doc with two separate paragraph docs
    docs = [d for d in docs if d.chunk_type != "examples"]
    docs += [
        RawDocument("confirmation_bias", "examples", "Para one.", "taxonomy",
                    {"source_file": "confirmation_bias.md", "display_name": "Confirmation Bias"},
                    paragraph_index=0),
        RawDocument("confirmation_bias", "examples", "Para two.", "taxonomy",
                    {"source_file": "confirmation_bias.md", "display_name": "Confirmation Bias"},
                    paragraph_index=1),
    ]
    chunks = build_chunks(docs, TAXONOMY_VERSION)
    example_chunks = [c for c in chunks if c.source_section == "Examples"]
    assert len(example_chunks) == 2
    assert example_chunks[0].chunk_index == 100
    assert example_chunks[1].chunk_index == 101


def test_example_paragraph_index_in_chunk_index():
    """chunk_index for examples = 1*100 + paragraph_index."""
    docs = _make_docs("anchoring_bias")
    docs = [d for d in docs if d.chunk_type != "examples"]
    docs.append(RawDocument(
        "anchoring_bias", "examples", "Para.", "taxonomy",
        {"source_file": "anchoring_bias.md", "display_name": "Anchoring Bias"},
        paragraph_index=3,
    ))
    chunks = build_chunks(docs, TAXONOMY_VERSION)
    ex = next(c for c in chunks if c.source_section == "Examples")
    assert ex.chunk_index == 103


def test_full_document_examples_concatenated_from_multiple_paragraphs():
    """FullBiasDocument.examples joins split paragraphs back with double newline."""
    docs = _make_docs("confirmation_bias")
    docs = [d for d in docs if d.chunk_type != "examples"]
    docs += [
        RawDocument("confirmation_bias", "examples", "First.", "taxonomy",
                    {"source_file": "f.md", "display_name": "C"}, paragraph_index=0),
        RawDocument("confirmation_bias", "examples", "Second.", "taxonomy",
                    {"source_file": "f.md", "display_name": "C"}, paragraph_index=1),
    ]
    chunks = build_chunks(docs, TAXONOMY_VERSION)
    fd = chunks[0].full_document
    assert fd.examples == "First.\n\nSecond."


def test_indicator_grouping_verbal_and_behavioral():
    """Bullets matching verbal/behavioral regex split into two groups."""
    docs = _make_docs("confirmation_bias")
    docs = [d for d in docs if d.chunk_type != "indicators"]
    docs.append(RawDocument(
        "confirmation_bias", "indicators",
        "- States the conclusion before reviewing evidence\n- Refuses to read contradicting studies",
        "taxonomy",
        {"source_file": "confirmation_bias.md", "display_name": "Confirmation Bias"},
    ))
    chunks = build_chunks(docs, TAXONOMY_VERSION)
    indicator_chunks = [c for c in chunks if c.source_section == "Indicators"]
    assert len(indicator_chunks) == 2
    assert indicator_chunks[0].chunk_index == 200
    assert indicator_chunks[1].chunk_index == 201


def test_indicator_all_unmatched_produces_one_group():
    """When no bullets match reasoning/behavioral, all go into a single group."""
    groups = _group_indicator_bullets(
        "- Ponders the implications without deciding\n- Wonders whether the risk is real"
    )
    assert len(groups) == 1


def test_indicator_grouping_empty_text():
    assert _group_indicator_bullets("") == []


def test_group_indicator_bullets_uses_word_boundary():
    """'overstates' must not match 'states'; 'characteristics' must not match 'acts'."""
    groups = _group_indicator_bullets(
        "- overstates the risk\n- exhibits characteristics of overconfidence"
    )
    # No true verbal/behavioral match → single group
    assert len(groups) == 1
