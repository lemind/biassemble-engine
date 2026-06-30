import hashlib
from dataclasses import dataclass
from typing import Any

from src.indexing.sources.base import RawDocument
from src.schemas.internal import (
    CHUNK_TYPE_DEFINITION,
    CHUNK_TYPE_EXAMPLE,
    CHUNK_TYPE_FALSE_POSITIVE,
    CHUNK_TYPE_INDICATOR,
    CHUNK_TYPE_RELATED,
    FullBiasDocument,
)

# Maps raw chunk_type (from normalizer) → (semantic_constant, human_readable_heading).
# source_section is the heading as it appears in the API response and DB.
_CHUNK_TYPE_MAP: dict[str, tuple[str, str]] = {
    "definition":      (CHUNK_TYPE_DEFINITION,    "Definition"),
    "examples":        (CHUNK_TYPE_EXAMPLE,        "Examples"),
    "indicators":      (CHUNK_TYPE_INDICATOR,      "Indicators"),
    "false_positives": (CHUNK_TYPE_FALSE_POSITIVE, "False Positives"),
    "related_biases":  (CHUNK_TYPE_RELATED,        "Related Biases"),
}

# Canonical section order — chunk_index is derived from this, not from the order
# sections appear in the markdown file, so ordering is consistent across all biases.
_CANONICAL_ORDER: list[str] = [
    "definition", "examples", "indicators", "false_positives", "related_biases"
]


@dataclass
class BiasChunk:
    """One chunk row ready for embedding and DB insertion."""

    bias_id: str
    chunk_type: str            # semantic constant e.g. "semantic_definition"
    source_section: str        # human-readable heading e.g. "False Positives"
    chunk_text: str            # prefixed text passed to the embedding model
    chunk_hash: str            # SHA256 dedup key — changes when content or version changes
    full_document: FullBiasDocument  # same object on all chunks for this bias_id
    source: str
    metadata: dict[str, Any]
    chunk_index: int           # section order within the bias document (0-based)


def build_chunks(documents: list[RawDocument], taxonomy_version: str) -> list[BiasChunk]:
    """Convert normalized RawDocuments into BiasChunks ready for embedding.

    Builds FullBiasDocument once per bias_id and attaches the same instance to
    all five chunks — so any change to the bias content is reflected everywhere
    without risk of stale copies.
    """
    by_bias: dict[str, list[RawDocument]] = {}
    for doc in documents:
        by_bias.setdefault(doc.bias_id, []).append(doc)

    chunks: list[BiasChunk] = []
    for bias_id, docs in by_bias.items():
        full_doc = _build_full_document(bias_id, docs)
        for doc in docs:
            mapping = _CHUNK_TYPE_MAP.get(doc.chunk_type)
            if mapping is None:
                continue
            semantic_type, source_section = mapping
            chunk_text = f"{full_doc.name} — {source_section}: {doc.text}"
            chunks.append(
                BiasChunk(
                    bias_id=bias_id,
                    chunk_type=semantic_type,
                    source_section=source_section,
                    chunk_text=chunk_text,
                    chunk_hash=_compute_hash(bias_id, semantic_type, chunk_text, taxonomy_version),
                    full_document=full_doc,
                    source=doc.source,
                    metadata=doc.metadata,
                    chunk_index=_CANONICAL_ORDER.index(doc.chunk_type),
                )
            )

    _print_stats(chunks)
    return chunks


def _build_full_document(bias_id: str, docs: list[RawDocument]) -> FullBiasDocument:
    """Assemble FullBiasDocument from all sections for a single bias_id."""
    by_section: dict[str, str] = {doc.chunk_type: doc.text for doc in docs}
    display_name = docs[0].metadata.get("display_name") or _derive_name(bias_id)
    return FullBiasDocument(
        name=display_name,
        definition=by_section.get("definition", ""),
        examples=by_section.get("examples", ""),
        indicators=by_section.get("indicators", ""),
        false_positives=by_section.get("false_positives", ""),
        related_biases=by_section.get("related_biases", ""),
    )


def _derive_name(bias_id: str) -> str:
    """Fallback when metadata has no display_name: 'sunk_cost_fallacy' → 'Sunk Cost Fallacy'."""
    return bias_id.replace("_", " ").title()


def _compute_hash(bias_id: str, chunk_type: str, chunk_text: str, taxonomy_version: str) -> str:
    """SHA256 of pipe-delimited fields — pipes prevent concatenation collisions."""
    payload = f"{bias_id}|{chunk_type}|{chunk_text}|{taxonomy_version}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _print_stats(chunks: list[BiasChunk]) -> None:
    bias_count = len({c.bias_id for c in chunks})
    print(f"chunk_builder: {len(chunks)} chunks across {bias_count} biases")
