# Data Model: Semantic Bias Retrieval Service

**Date**: 2026-06-27 | **Branch**: `001-rag-retrieval`

---

## ChunkType Constants

String constants — not an enum. Each `KnowledgeSource` validates its own chunk types; future sources can introduce new ones without touching this file.

```python
# src/schemas/internal.py
CHUNK_TYPE_DEFINITION     = "semantic_definition"
CHUNK_TYPE_EXAMPLE        = "semantic_example"
CHUNK_TYPE_INDICATOR      = "semantic_indicator"
CHUNK_TYPE_FALSE_POSITIVE = "semantic_false_positive"
CHUNK_TYPE_RELATED        = "semantic_related"
```

`TaxonomySource` uses these five. `source_section` is always the original markdown heading free-text (e.g. `"False Positives"`), independent of `chunk_type`.

---

## Database: `bias_embeddings`

Primary storage for indexed bias knowledge. One row per chunk per bias per taxonomy version.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID PK | No | Auto-generated row identifier |
| `bias_id` | TEXT | No | Kebab-case bias identifier, e.g. `confirmation_bias` |
| `chunk_type` | TEXT | No | Semantic constant: `semantic_definition`, `semantic_example`, `semantic_indicator`, `semantic_false_positive`, `semantic_related` |
| `source_section` | TEXT | No | Original markdown heading, e.g. `Definition`, `False Positives` |
| `chunk_text` | TEXT | No | The text that was embedded. Prefixed with bias name, e.g. `"Confirmation Bias — Definition: ..."` |
| `chunk_hash` | TEXT | No | `SHA256(bias_id + chunk_type + chunk_text + taxonomy_version)` — changes when content or version changes |
| `full_document` | JSONB | No | All fields for this bias. See structure below. Same object on every row for the same `(bias_id, taxonomy_version)`. |
| `embedding` | vector(384) | No | all-MiniLM-L6-v2 output |
| `source` | TEXT | No | `"taxonomy"` (v1 only) |
| `metadata` | JSONB | No | Source-specific KV pairs. See provenance schema below. |
| `taxonomy_version` | TEXT | No | Immutable snapshot ID, e.g. `v1`, `v2` |
| `embedding_model` | TEXT | No | Model name, e.g. `all-MiniLM-L6-v2` |
| `chunk_index` | INTEGER | No | Section order within the bias document (0-based, by markdown heading position) |
| `indexed_at` | TIMESTAMPTZ | No | When this row was written by the indexer. `MAX(indexed_at)` is used by `/health` to report last index time. |
| `created_at` | TIMESTAMPTZ | No | DB-side row creation timestamp (default `NOW()`). Redundant with `indexed_at` for inserts; retained for audit purposes. |

### `full_document` JSONB structure

Every row for a given `(bias_id, taxonomy_version)` carries the same `full_document`. This enables single-query retrieval — the matching chunk is found, the full bias content is already on the row.

```json
{
  "name": "Confirmation Bias",
  "definition": "The tendency to search for, interpret, favor, and recall information that confirms or supports prior beliefs or values.",
  "examples": "An investor only reads news that supports their existing position...",
  "indicators": "Seeks confirming evidence. Dismisses contradictory sources...",
  "false_positives": "A scientist who forms a hypothesis and then tests it is not exhibiting confirmation bias...",
  "related_biases": "Anchoring Bias, Availability Heuristic, Motivated Reasoning"
}
```

Keys are always the six fields above. `name` is the display name (title-cased, from the `# Heading` in the markdown file). The remaining keys match the section names normalised to lowercase snake_case.

**Consistency rule**: `chunk_builder` builds `full_document` for each `bias_id` once, then attaches the same dict object to all chunks for that bias. Never build `full_document` per-chunk.

The JSONB is deserialized into a typed dataclass in `searcher.py` on retrieval:

```python
@dataclass
class FullBiasDocument:
    name: str
    definition: str
    examples: str
    indicators: str
    false_positives: str
    related_biases: str
```

`CandidateChunk.full_document` is typed as `FullBiasDocument`, not `dict`. This catches missing fields at deserialization time rather than silently returning `None` downstream.

**Future extension — `FieldProvenance`**: when multiple `KnowledgeSource`s contribute to the same bias, field-level provenance becomes necessary (e.g., `definition` from taxonomy, `examples` from a textbook). A future `FieldProvenance` dataclass would wrap each field with `text`, `source`, and `metadata`. Not implemented in v1 — the current single-source structure is the seam where it would be introduced.

### `metadata` provenance schema

Each `KnowledgeSource` populates `metadata` with source-specific fields. v1 has only `TaxonomySource`; future sources extend without schema changes.

| Source | Fields |
|--------|--------|
| `TaxonomySource` | `{"source_file": "confirmation_bias.md"}` |
| `BookSource` (future) | `{"title": "...", "author": "...", "page": 42, "isbn": "..."}` |
| `WikipediaSource` (future) | `{"url": "https://en.wikipedia.org/...", "snapshot_date": "2026-01-01", "license": "CC BY-SA"}` |
| `PaperSource` (future) | `{"doi": "10.1234/...", "title": "...", "authors": ["..."], "year": 2024}` |

This enables citation rendering and source filtering (`WHERE metadata->>'license' = 'CC BY-SA'`) without schema migrations.

**Indexes**:
- `bias_embeddings_embedding_idx` — IVFFlat cosine, lists=10 (retune at sqrt(rows) when > 1000 rows)
- `bias_embeddings_bias_id_idx` — btree on `bias_id`
- `bias_embeddings_source_idx` — btree on `source`
- `bias_embeddings_taxonomy_version_idx` — btree on `taxonomy_version`
- `bias_embeddings_dedup_idx` — UNIQUE on `(taxonomy_version, bias_id, chunk_type, chunk_hash)`
- `bias_embeddings_metadata_idx` — GIN on `metadata` (enables `WHERE metadata->>'domain' = 'finance'` filtering)

**Invariants**:
- `taxonomy_version` is immutable after rows are inserted — never re-index into an existing version
- `full_document` is identical across all rows sharing the same `(bias_id, taxonomy_version)`
- `chunk_hash` must change when `chunk_text` changes — enforced by the UNIQUE dedup index

---

## Internal Schemas (Python)

### `RawDocument` (source output)

Output of `TaxonomySource.load()`. One per markdown section per bias file.

```python
@dataclass
class RawDocument:
    bias_id: str        # from filename stem: "confirmation_bias"
    chunk_type: str     # raw section label, e.g. "definition", "examples" — NOT the semantic constant
    text: str           # raw markdown section text (not yet prefixed or normalised)
    source: str         # "taxonomy"
    metadata: dict      # TaxonomySource sets {"source_file": "confirmation_bias.md"}
```

**`chunk_type` here is the raw section label** (`"definition"`, `"false_positives"`), not the semantic constant. `chunk_builder` maps this to the `CHUNK_TYPE_*` constant and stores both:
- DB `chunk_type` ← semantic constant (`"semantic_definition"`)
- DB `source_section` ← original markdown heading (`"Definition"`)

### `CandidateChunk` (searcher output)

```python
@dataclass
class CandidateChunk:
    bias_id: str
    chunk_type: str               # semantic constant e.g. CHUNK_TYPE_DEFINITION
    source_section: str           # original markdown heading e.g. "Definition"
    source: str                   # knowledge source e.g. "taxonomy", "book" — for multi-source debugging
    chunk_text: str
    full_document: FullBiasDocument
    retrieval_score: float        # cosine similarity 0.0–1.0
```

### `RetrievedBias` (reranker output)

```python
@dataclass
class RetrievedBias:
    bias_id: str
    name: str                  # display name from full_document.name, e.g. "Confirmation Bias"
    retrieval_score: float     # max chunk retrieval_score across all matching chunks for this bias
    sources: list[str]         # knowledge sources that contributed, e.g. ["taxonomy"]
    matched_chunk_type: str    # semantic constant of the chunk that scored highest
    matched_text: str          # the chunk text that scored highest
    definition: str            # from full_document.definition
    examples: str              # from full_document.examples
    indicators: str            # from full_document.indicators
    false_positives: str       # from full_document.false_positives
    related_biases: str        # from full_document.related_biases
```

`name` is populated from `full_document.name`. `sources` lists all knowledge sources whose chunks survived the threshold for this bias — in v1 always `["taxonomy"]`, meaningful once multiple sources are indexed. `matched_chunk_type` and `matched_text` are logged server-side, never in the API response.

### `RetrievalMetadata` (observability)

```python
@dataclass
class RetrievalMetadata:
    retrieval_id: str          # UUID — correlates all log events for one request
    embedding_model: str
    taxonomy_version: str
    query_strategy: str
    query_length: int          # chars in final query string
    embedding_latency_ms: int
    search_latency_ms: int
    rerank_latency_ms: int
    total_latency_ms: int
    candidate_chunks: int      # before threshold filter
    surviving_chunks: int      # after threshold filter
    returned_biases: int
    top_retrieval_score: float | None
    avg_retrieval_score: float | None
    threshold_used: float
```

---

## API Schemas (Pydantic)

### `RetrieveRequest`

```python
class StoryAnalysis(BaseModel):
    themes: list[str] = []
    beliefs: list[str] = []
    claims: list[str] = []

class RetrieveRequest(BaseModel):
    story: str
    request_id: str | None = None   # UUID from biassemble-core for cross-service correlation
    story_analysis: StoryAnalysis | None = None
```

### `BiasResult` (API DTO — response only)

```python
class BiasResult(BaseModel):
    id: str                  # bias_id, e.g. "confirmation_bias"
    name: str                # display name, e.g. "Confirmation Bias" — from RetrievedBias.name
    retrieval_score: float   # cosine-based score 0.0–1.0; label makes scoring method unambiguous
    definition: str
    examples: str
    indicators: str
    false_positives: str
    related_biases: str
```

### `RetrieveResponse`

```python
class RetrieveResponse(BaseModel):
    biases: list[BiasResult]   # empty list = valid "no biases found", NOT an error
    retrieved_chunks: int      # count before threshold filtering
    taxonomy_version: str
    embedding_model: str
    request_id: str            # echoed from request if provided, otherwise == retrieval_id
```

---

## Config (`Settings`)

```python
class Settings(BaseSettings):
    database_url: str
    rag_api_key: str
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384        # validated against provider.dimension at startup
    taxonomy_version: str = "v1"
    search_top_k: int = 20
    return_top_k: int = 5
    similarity_threshold: float = 0.45
    query_strategy: str = "repeated_story"
    rerank_strategy: str = "max"
    index_batch_size: int = 32
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
```

`taxonomy_version` is read-only after startup — never hot-reload it. All retrieval tuning parameters are in config, not hardcoded, to enable parameter sweeps via evaluation.

---

## Type Transformation: RawDocument → bias_embeddings

`chunk_builder` is the only place these mappings happen:

| `RawDocument.chunk_type` | DB `source_section` | DB `chunk_type` |
|--------------------------|---------------------|-----------------|
| `"definition"` | `"Definition"` | `"semantic_definition"` |
| `"examples"` | `"Examples"` | `"semantic_example"` |
| `"indicators"` | `"Indicators"` | `"semantic_indicator"` |
| `"false_positives"` | `"False Positives"` | `"semantic_false_positive"` |
| `"related_biases"` | `"Related Biases"` | `"semantic_related"` |

`source_section` is the human-readable heading; `chunk_type` is the machine-readable constant used in queries and logs.

---

## Entity Relationships

```
knowledge/*.md
    └── TaxonomySource.load() ──→ RawDocument[]
            └── normalizer ──→ RawDocument[] (validated, headings normalised)
                    └── chunk_builder ──→ chunks[] (with full_document, chunk_hash, chunk_type mapping)
                            └── embedder ──→ (chunk + vector)[]
                                    └── indexer ──→ bias_embeddings rows

bias_embeddings rows
    └── searcher (cosine query) ──→ CandidateChunk[]
            └── reranker (threshold + collapse) ──→ RetrievedBias[]
                    └── retriever (+ RetrievalMetadata logs) ──→ RetrieveResponse
```

---

## State Transitions

### taxonomy_version lifecycle

```
author edits knowledge/*.md
    → bump TAXONOMY_VERSION (e.g. v1 → v2)
    → run_indexing.py: new rows inserted under v2
    → old rows under v1 remain untouched
    → update TAXONOMY_VERSION=v2 in config + redeploy
    → verify /health: rows_indexed reflects v2 count
    → delete v1 rows when no longer needed
```

Re-indexing never overwrites. Bumping `taxonomy_version` is mandatory on every re-index.

### Embedding model swap

```
1. Download new model
2. Update EMBEDDING_MODEL and EMBEDDING_DIMENSION in config
3. If dimension changed: ALTER COLUMN embedding TYPE vector(N) in Supabase
4. Run full re-index under a new taxonomy_version
5. Validate /health: embedding_dimension matches new value
6. Run evaluation — confirm Recall@5 ≥ baseline
```
