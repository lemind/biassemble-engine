import logging
import re
from dataclasses import replace

from src.indexing.sources.base import RawDocument

log = logging.getLogger(__name__)

# All five sections every bias file must contain.
_MANDATORY_CHUNK_TYPES: frozenset[str] = frozenset(
    {"definition", "examples", "indicators", "false_positives", "related_biases"}
)

# Singular heading variants that TaxonomySource may produce; map to canonical plural form.
_ALIAS_MAP: dict[str, str] = {
    "false_positive": "false_positives",
    "example": "examples",
    "indicator": "indicators",
    "related_bias": "related_biases",
}


def normalize(documents: list[RawDocument]) -> list[RawDocument]:
    """Clean, deduplicate, and validate raw docs from a knowledge source.

    Called between KnowledgeSource.load() and chunk_builder. Halts on any
    bias missing a mandatory section so indexing never silently produces
    incomplete embeddings.
    """
    cleaned = [_clean(doc) for doc in documents]
    deduped = _deduplicate(cleaned)
    _validate(deduped)
    return deduped


def _clean(doc: RawDocument) -> RawDocument:
    """Strip excess whitespace and resolve chunk_type aliases to canonical names."""
    return replace(
        doc,
        text=re.sub(r"\n{3,}", "\n\n", doc.text).strip(),
        chunk_type=_ALIAS_MAP.get(doc.chunk_type, doc.chunk_type),
    )


def _deduplicate(documents: list[RawDocument]) -> list[RawDocument]:
    """Drop docs whose bias_id was already seen from a different source file.

    Each bias_id appears five times (one per section) from the same file — that
    is normal and all five are kept. A second file claiming the same bias_id is
    a conflict: warn and discard the later file entirely.
    """
    first_source: dict[str, str] = {}
    warned: set[str] = set()
    result: list[RawDocument] = []

    for doc in documents:
        src = doc.metadata.get("source_file", "")
        if doc.bias_id not in first_source:
            first_source[doc.bias_id] = src
            result.append(doc)
        elif first_source[doc.bias_id] == src:
            result.append(doc)
        else:
            if doc.bias_id not in warned:
                log.warning(
                    "duplicate bias_id %r: keeping %r, dropping %r",
                    doc.bias_id,
                    first_source[doc.bias_id],
                    src,
                )
                warned.add(doc.bias_id)

    return result


def _validate(documents: list[RawDocument]) -> None:
    """Raise ValueError if any bias_id is missing a mandatory section."""
    by_bias: dict[str, set[str]] = {}
    for doc in documents:
        by_bias.setdefault(doc.bias_id, set()).add(doc.chunk_type)

    for bias_id, chunk_types in by_bias.items():
        missing = _MANDATORY_CHUNK_TYPES - chunk_types
        if missing:
            raise ValueError(
                f"bias_id {bias_id!r} missing mandatory sections: {sorted(missing)}"
            )
