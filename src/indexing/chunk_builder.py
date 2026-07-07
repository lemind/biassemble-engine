import hashlib
import re
from dataclasses import dataclass
from typing import Any

from src.indexing.sources.base import RawDocument
from src.schemas.internal import (
    CHUNK_TYPE_DEFINITION,
    CHUNK_TYPE_EXAMPLE,
    CHUNK_TYPE_FALSE_POSITIVE,
    CHUNK_TYPE_INDICATOR,
    CHUNK_TYPE_RELATED,
    CHUNK_TYPE_STORY_PATTERN,
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
    "story_patterns":  (CHUNK_TYPE_STORY_PATTERN,  "Story Pattern"),
}

# Canonical section order — chunk_index is derived from this, not from the order
# sections appear in the markdown file, so ordering is consistent across all biases.
_CANONICAL_ORDER: list[str] = [
    "definition", "examples", "indicators", "false_positives", "related_biases", "story_patterns"
]

# Post-T002 indicators use first-person thinking language. _VERBAL captures the
# reasoning/cognitive register; _BEHAVIORAL captures the action register.
_VERBAL = re.compile(
    r"\b(treats|judges|believes|rates|evaluates|assumes|expects|hears|concludes"
    r"|draws|attributes|estimates|remembers|feels|finds|forms|trusts|accepts"
    r"|interprets|dismisses|states|claims|insists|asserts|declares|says|tells)\b"
)
_BEHAVIORAL = re.compile(
    r"\b(makes|takes|refuses|explains|avoids|uses|holds|chooses|changes"
    r"|resists|prefers|applies|gives|reads|asks|adopts|sets|plans|revises"
    r"|updates|invests|buys|bets|stays|adjusts|lowers|increases|struggles"
    r"|defers|selects|seeks)\b"
)


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
            section_base = _CANONICAL_ORDER.index(doc.chunk_type)

            if doc.chunk_type == "indicators":
                groups = _group_indicator_bullets(doc.text)
                if not groups:
                    groups = [doc.text]
                for para_idx, group_text in enumerate(groups):
                    if para_idx >= 100:
                        raise ValueError(f"paragraph_index overflow: {bias_id} indicators idx={para_idx}")
                    chunk_text = f"{full_doc.name} — {source_section}: {group_text}"
                    chunks.append(BiasChunk(
                        bias_id=bias_id,
                        chunk_type=semantic_type,
                        source_section=source_section,
                        chunk_text=chunk_text,
                        chunk_hash=_compute_hash(bias_id, semantic_type, chunk_text, taxonomy_version),
                        full_document=full_doc,
                        source=doc.source,
                        metadata=doc.metadata,
                        chunk_index=section_base * 100 + para_idx,
                    ))
            elif doc.chunk_type == "story_patterns":
                if doc.paragraph_index >= 100:
                    raise ValueError(f"paragraph_index overflow: {bias_id} story_patterns idx={doc.paragraph_index}")
                # No bias-name prefix — keep raw story text so embedding stays in
                # the same vector space as real user stories.
                chunk_text = doc.text
                chunks.append(BiasChunk(
                    bias_id=bias_id,
                    chunk_type=semantic_type,
                    source_section=source_section,
                    chunk_text=chunk_text,
                    chunk_hash=_compute_hash(bias_id, semantic_type, chunk_text, taxonomy_version),
                    full_document=full_doc,
                    source=doc.source,
                    metadata=doc.metadata,
                    chunk_index=section_base * 100 + doc.paragraph_index,
                ))
            else:
                if doc.paragraph_index >= 100:
                    raise ValueError(f"paragraph_index overflow: {bias_id} {doc.chunk_type} idx={doc.paragraph_index}")
                chunk_text = f"{full_doc.name} — {source_section}: {doc.text}"
                chunks.append(BiasChunk(
                    bias_id=bias_id,
                    chunk_type=semantic_type,
                    source_section=source_section,
                    chunk_text=chunk_text,
                    chunk_hash=_compute_hash(bias_id, semantic_type, chunk_text, taxonomy_version),
                    full_document=full_doc,
                    source=doc.source,
                    metadata=doc.metadata,
                    chunk_index=section_base * 100 + doc.paragraph_index,
                ))

    _print_stats(chunks)
    return chunks


def _build_full_document(bias_id: str, docs: list[RawDocument]) -> FullBiasDocument:
    """Assemble FullBiasDocument from all sections for a single bias_id."""
    by_section: dict[str, list[str]] = {}
    for doc in docs:
        by_section.setdefault(doc.chunk_type, []).append(doc.text)
    display_name = docs[0].metadata.get("display_name") or _derive_name(bias_id)
    return FullBiasDocument(
        name=display_name,
        definition=by_section.get("definition", [""])[0],
        examples="\n\n".join(by_section.get("examples", [])),
        indicators=by_section.get("indicators", [""])[0],
        false_positives=by_section.get("false_positives", [""])[0],
        related_biases=by_section.get("related_biases", [""])[0],
    )


def _group_indicator_bullets(text: str) -> list[str]:
    """Split indicator bullet list into thematic groups (behavioral / verbal).

    Unmatched bullets go to the smallest classified group. If no behavioral or
    verbal bullets are found, returns a single group containing all bullets.
    Warns when any group captures >80% of bullets — signals keyword list needs
    updating for the post-rewrite indicator language.
    """
    bullets = [b.strip().lstrip("- ").strip() for b in text.splitlines() if b.strip()]
    if not bullets:
        return []

    verbal: list[str] = []
    behavioral: list[str] = []
    unmatched: list[str] = []

    for b in bullets:
        lower = b.lower()
        if _VERBAL.search(lower):
            verbal.append(b)
        elif _BEHAVIORAL.search(lower):
            behavioral.append(b)
        else:
            unmatched.append(b)

    classified = [g for g in [behavioral, verbal] if g]

    if not classified:
        return ["- " + "\n- ".join(unmatched)]

    total = sum(len(g) for g in classified)  # snapshot before unmatched redistribution
    if unmatched:
        smallest = min(classified, key=len)
        smallest.extend(unmatched)
    for g in classified:
        if total > 0 and len(g) / total > 0.8:
            print(
                f"chunk_builder WARNING: indicator group has {len(g)}/{total} bullets "
                f"— keyword signals may need updating for post-rewrite indicator language"
            )

    return ["- " + "\n- ".join(g) for g in classified]


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
