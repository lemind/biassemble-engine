# Data Model: Taxonomy Retrieval Improvement

**Date**: 2026-07-02 | **Branch**: `002-improve-taxonomy-retrieval`

This document describes only what changes relative to `specs/001-rag-retrieval/data-model.md`. Everything not mentioned here is unchanged.

---

## New: `CHUNK_TYPE_OBSERVABLE_PATTERNS` constant (conditional, Phase 5)

Added to `src/schemas/internal.py` only if Phase 5 is triggered by the gate condition.

```python
# src/schemas/internal.py (Phase 5 addition)
CHUNK_TYPE_OBSERVABLE_PATTERNS = "observable_patterns"
```

---

## Changed: `RawDocument` — new `paragraph_index` field

```python
# src/indexing/sources/base.py
@dataclass
class RawDocument:
    bias_id: str
    chunk_type: str
    text: str
    source: str
    metadata: dict
    paragraph_index: int = 0   # position within section; 0 for single-chunk sections
```

`paragraph_index` defaults to 0 for sections that produce one chunk (definition, false positives, related biases). `TaxonomySource` sets it when splitting multi-paragraph sections.

---

## Changed: `TaxonomySource._parse()` — paragraph splitting

`TaxonomySource._parse()` now produces multiple `RawDocument`s per `examples` section instead of one per section. Indicators are still emitted as a single `RawDocument` — grouping into thematic clusters happens in `chunk_builder`, not in `TaxonomySource`.

**For `examples` sections** (split per paragraph):
```python
# Split on double newline — existing paragraph formatting convention.
# Each non-empty paragraph is a separate RawDocument with the same chunk_type.
paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
for i, para in enumerate(paragraphs):
    domain = _extract_domain(para)       # returns None if no [Domain] prefix
    clean = _strip_domain_label(para)    # removes [Domain] prefix from text
    meta = {"source_file": path.name, "display_name": display_name}
    if domain:
        meta["domain"] = domain
    docs.append(RawDocument(
        bias_id=bias_id,
        chunk_type="examples",
        text=clean,
        source=self.name,
        metadata=meta,
        paragraph_index=i,
    ))
```

**Domain label extraction**: paragraphs starting with `[Label]` (e.g., `[Political]`) have the domain extracted and stored in `metadata.domain`. The label is stripped from `chunk_text` before embedding.

**Controlled vocabulary**: domain labels are single words only — `Political`, `Social`, `Management`, `Consumer`, `Legal`, `Medical`. Hyphens, ampersands, and multi-word phrases are not supported by the regex and must not be used in knowledge files. STYLE_GUIDE documents this list.

```python
import re
_DOMAIN_RE = re.compile(r"^\[([A-Za-z]+)\]\s*")  # single-word labels only

def _extract_domain(text: str) -> str | None:
    m = _DOMAIN_RE.match(text)
    return m.group(1).lower() if m else None

def _strip_domain_label(text: str) -> str:
    return _DOMAIN_RE.sub("", text)
```

**For `indicators` sections** (group into thematic clusters, 2–3 groups):

Bullets are grouped into thematic clusters in `chunk_builder` (not in `TaxonomySource`), since grouping requires semantic reasoning about bullet content. `TaxonomySource` passes the raw indicator text as a single `RawDocument` (`paragraph_index=0`). `chunk_builder` splits it into groups.

---

## Changed: `chunk_builder.build_chunks()` — indicator grouping + chunk_index

**chunk_index**: Changed from canonical section position (0–4) to `section_base * 100 + paragraph_index`, where `section_base` is the 0-based position of the chunk's section in `_CANONICAL_ORDER`. Invariant asserted — documents the assumption and surfaces overflow immediately.

```python
# chunk_index computation in build_chunks()
assert doc.paragraph_index < 100, (
    f"paragraph_index overflow: {doc.bias_id} {doc.chunk_type} idx={doc.paragraph_index}"
)
section_base = _CANONICAL_ORDER.index(doc.chunk_type)
chunk_index = section_base * 100 + doc.paragraph_index
```

**Indicator grouping**: After receiving the single indicator `RawDocument`, `chunk_builder` groups the bullets into 2–3 thematic clusters. Uses word-boundary (`\b`) regex matching — not substring `in` — to prevent false matches (e.g., `"overstates"` contains `"states"`, `"characteristics"` contains `"acts"`). Unmatched bullets go to the smallest group (not fixed to "reasoning"). Distribution warning fires when one group captures >80% of bullets, signalling that the keyword list needs updating for post-rewrite indicator language.

```python
import re

_VERBAL = re.compile(r"\b(says|tells|claims|insists|argues|states|asserts|declares)\b")
_BEHAVIORAL = re.compile(r"\b(chooses|avoids|seeks|refuses|selects|invests|buys|sells|acts upon|acts on)\b")

def _group_indicator_bullets(text: str) -> list[str]:
    """Split indicator bullet list into 2-3 thematic groups.

    Categories: reasoning (thoughts/beliefs), behavioral (actions/choices), verbal (speech).
    Unmatched bullets go to the smallest non-empty group.
    Warns if any group captures >80% of bullets.
    """
    bullets = [b.strip().lstrip("- ").strip() for b in text.splitlines() if b.strip()]
    if not bullets:
        return []

    groups: dict[str, list[str]] = {"reasoning": [], "behavioral": [], "verbal": []}
    for b in bullets:
        lower = b.lower()
        if _VERBAL.search(lower):
            groups["verbal"].append(b)
        elif _BEHAVIORAL.search(lower):
            groups["behavioral"].append(b)
        else:
            groups["reasoning"].append(b)

    # Re-assign unmatched (reasoning) bullets to smallest group if another group exists
    non_empty = {k: v for k, v in groups.items() if v}
    if len(non_empty) > 1 and groups["reasoning"]:
        smallest = min((k for k in non_empty if k != "reasoning"), key=lambda k: len(non_empty[k]))
        non_empty[smallest].extend(groups["reasoning"])
        non_empty["reasoning"] = [b for b in groups["reasoning"] if False]  # clear

    result = ["\n- " + "\n- ".join(v) for v in non_empty.values() if v]

    # Distribution health check
    total = sum(len(v) for v in non_empty.values() if v)
    for name, v in non_empty.items():
        if v and total > 0 and len(v) / total > 0.8:
            print(
                f"chunk_builder WARNING: indicator group '{name}' has {len(v)}/{total} bullets "
                f"— keyword signals may need updating for post-rewrite indicator language"
            )
    return result
```

Each group becomes its own `RawDocument` with `paragraph_index=0,1,2` before being passed through the existing chunk pipeline. `chunk_builder` handles this internally — `TaxonomySource` still emits one `RawDocument` for the indicators section.

---

## Changed: `BiasChunk` — `metadata` carries `domain` for Phase 4 chunks

The `metadata` field already exists. No schema change. Phase 4 domain-tagged paragraphs will have:

```python
BiasChunk.metadata = {
    "source_file": "overconfidence_bias.md",
    "display_name": "Overconfidence Bias",
    "domain": "political"   # present only on domain-tagged paragraphs
}
```

The existing GIN index on `metadata` already supports `WHERE metadata->>'domain' = 'political'` filtering.

---

## No change: `full_document` JSONB

`FullBiasDocument` fields remain the full merged section text. Splitting happens at the chunk level — `full_document.examples` still contains all paragraphs concatenated, `full_document.indicators` still contains all bullets. `_build_full_document()` in `chunk_builder` is unchanged.

The matched chunk text is already available on `RetrievedBias.matched_text` and `RetrievedBias.matched_chunk_type` for logging and diagnostic purposes.

---

## Changed: `ScenarioResult` — diagnostics field

```python
# src/evaluation/evaluate.py
@dataclass
class ScenarioResult:
    scenario_id: str
    group: str
    expected: list[str]
    retrieved: list[str]
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    error: str | None = None
    retrieved_with_diagnostics: list[dict] | None = None  # populated with --diagnostics flag
```

`retrieved_with_diagnostics` is `None` in normal eval runs. When `--diagnostics` is passed:

```python
# Each dict in retrieved_with_diagnostics:
{
    "bias_id": "confirmation_bias",
    "retrieval_score": 0.412,
    "matched_chunk_type": "semantic_indicator",
    "matched_text": "Confirmation Bias — Indicators: ..."
}
```

This is populated from the `RetrievedBias` objects returned by `rerank()` before they are reduced to bias IDs.

---

## New file: `scripts/probe_chunk.py`

Standalone script. No DB connection. Compares embedding similarity of an old chunk vs. a new chunk against a target story.

```
uv run python scripts/probe_chunk.py \
  --story "The evidence is clear: our policies are working." \
  --old "Confidence intervals that are too narrow relative to actual outcome distributions" \
  --new "States an outcome as certain or inevitable without acknowledging the possibility of being wrong"
```

Output:
```
old: 0.182
new: 0.341
delta: +0.159  IMPROVED
```

Pass condition: `new_score > old_score`. No fixed threshold. This is the condition for **indicator rewrites** (T002) — confirming that the rewritten chunk embeds closer to the story than the old one.

**Domain paragraph validation (T005) is stricter**: a domain example paragraph must satisfy `new_score > SIMILARITY_THRESHOLD` (the threshold set in Phase 2). A paragraph that beats the old chunk but still falls below the retrieval threshold won't be retrieved — the probe must confirm it clears the live threshold, not just that it improved.

---

## New file: `scripts/tune_threshold.py`

Sweeps `similarity_threshold` from 0.25 to 0.60 in 0.025 steps. For each value, reports negative group empty_rate, adversarial group empty_rate (adversarial stories contain real biases — too-high threshold empties them wrongly), and positive group Recall@5 (guard against threshold crushing positive retrievals). See research.md for sample output format. Operator sets the chosen value in `.env` manually.

---

## `taxonomy_version` naming convention

Format: `"YYYY-MM-DD.N"` where N is a 1-based sequential sub-version within the day.

| Phase completed | New `taxonomy_version` | Real reindex? | What changed |
|---|---|---|---|
| Baseline (existing) | `"2026-07-02"` or latest | — | Pre-feature baseline |
| Phase 1 complete (indicators rewritten) | `"2026-07-02.1"` | Yes — same 5 chunks, different text | Indicator text changed in all 38 files |
| Phase 2 complete (all chunks split) | `"2026-07-02.2"` | Yes — chunk count grows ~190→380 | Chunk structure changed; indexer changes deployed |
| Phase 3 diagnostics run | same as Phase 2 | No | Diagnostic eval run only; no new index |
| Phase 4 complete (domain examples added) | `"2026-07-02.3"` | Yes — new chunks for specific biases | New domain paragraphs added |
| Phase 5 complete (observable_patterns, if triggered) | `"2026-07-02.4"` | Yes — new chunk type for all biases | observable_patterns section added |

Phase 1 reindex is real and independent — it changes only chunk text, not structure. Phase 2 reindex changes structure. Running them as separate versions allows isolating the text-quality improvement (Phase 1) from the structural improvement (Phase 2) in evaluation results.

Every evaluation run JSON includes `taxonomy_version` — phase-boundary comparisons are always unambiguous.

---

## `chunk_index` examples after splitting

For `confirmation_bias` with 4 example paragraphs and 3 indicator groups:

| section | paragraph_index | chunk_index | description |
|---|---|---|---|
| definition | 0 | 0 | single definition chunk |
| examples | 0 | 101 | first example paragraph |
| examples | 1 | 102 | second example paragraph |
| examples | 2 | 103 | third example paragraph |
| examples | 3 | 104 | fourth example paragraph |
| indicators | 0 | 200 | reasoning pattern group |
| indicators | 1 | 201 | behavioral pattern group |
| indicators | 2 | 202 | verbal pattern group |
| false_positives | 0 | 300 | single false positive chunk |
| related_biases | 0 | 400 | single related biases chunk |

Total: 10 chunks for this bias (was 5). Across 38 biases: ~380 chunks (was 190). Still within exact-scan territory; no IVFFlat needed until the threshold is crossed.

---

## `bias_embeddings` dedup index behaviour after splitting

`UNIQUE ON (taxonomy_version, bias_id, chunk_type, chunk_hash)` — unchanged. Multiple rows with the same `(bias_id, chunk_type)` are valid as long as `chunk_hash` differs. Since `chunk_hash` is `SHA256(bias_id|chunk_type|chunk_text|taxonomy_version)`, each paragraph produces a different hash. No index migration required.

---

## `observable_patterns` section in knowledge files (Phase 5, conditional)

New `## Observable Patterns` section in each knowledge file. STYLE_GUIDE additions:

```
## Observable Patterns
- ≤8 phrases per bias
- Each phrase ≤12 words
- Written in first-person, direct speech, or imperative register
- No analytics language ("confidence intervals", "risk estimates", "probability")
- Phrases represent what someone SAYS when exhibiting the bias, not what an analyst observes
```

Example (overconfidence_bias):
```
## Observable Patterns
The evidence is clear.
The results speak for themselves.
I've already looked into it.
There's no real doubt here.
Anyone who examines the facts will agree.
We don't need to consider the other possibility.
```

`TaxonomySource` maps `"observable patterns"` heading → `"observable_patterns"` chunk_type. `chunk_builder` produces one chunk for the full set of phrases (no per-phrase splitting).

`observable_patterns` is appended to `_CANONICAL_ORDER` as position 5 (after `related_biases` at position 4). `chunk_index` for observable_patterns chunks = `500 + paragraph_index` (always 500 in practice since the section produces one chunk).

```python
# src/indexing/chunk_builder.py (Phase 5 addition)
_CANONICAL_ORDER: list[str] = [
    "definition",           # section_base 0 → chunk_index 0xx
    "examples",             # section_base 1 → chunk_index 1xx
    "indicators",           # section_base 2 → chunk_index 2xx
    "false_positives",      # section_base 3 → chunk_index 3xx
    "related_biases",       # section_base 4 → chunk_index 4xx
    "observable_patterns",  # section_base 5 → chunk_index 500  (Phase 5)
]
```
