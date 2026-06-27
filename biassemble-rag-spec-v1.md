# biassemble-rag — Service Specification v1.3

## Purpose

Standalone Python microservice providing semantic bias retrieval for Biassemble.

Replaces static taxonomy injection in `biassemble-core` with dynamic retrieval: given a story, return the most semantically relevant biases from a rich knowledge base as structured context for the LLM assessment prompt.

This service is a **pure retriever**. It never calls an LLM. It has no knowledge of the public app.

Dependency rule: `biassemble-core` → `biassemble-rag` → `pgvector`. Never reversed.

---

## Repository

Separate repo: `biassemble-rag`

Reason: independent Python runtime, deploy target, versioning, and CI. Keeps `biassemble-core` boundary intact.

---

## Stack

| Layer | Technology |
|---|---|
| HTTP framework | FastAPI |
| Validation | Pydantic v2 + pydantic-settings |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`) via `EmbeddingProvider` abstraction |
| Database client | asyncpg |
| Vector operations | pgvector Python client |
| Structured logging | structlog |
| Package manager | uv |
| Linting / formatting | Ruff |
| Type checking | mypy |
| Tests | pytest + pytest-asyncio |
| Deploy | Railway (Dockerfile) — image is portable; zero code changes to move to Fly.io, Render, or DO App Platform |

No LangChain. No LlamaIndex. No SQLAlchemy. Raw primitives only.

`httpx` is a future dependency — add when the first external knowledge source (`WikipediaSource`) is implemented.

---

## Internal Schemas

Three distinct concepts — do not collapse them into one class.

### `ChunkType` constants

`chunk_type` for taxonomy chunks uses string constants — not an enum. An enum would require extending for every new chunk type from future sources (`BookSource`, `PaperSource`) which defeats extensibility. Each `KnowledgeSource` validates its own chunk types.

```python
# src/schemas/internal.py
CHUNK_TYPE_DEFINITION     = "semantic_definition"
CHUNK_TYPE_EXAMPLE        = "semantic_example"
CHUNK_TYPE_INDICATOR      = "semantic_indicator"
CHUNK_TYPE_FALSE_POSITIVE = "semantic_false_positive"
CHUNK_TYPE_RELATED        = "semantic_related"
```

`TaxonomySource` uses these constants. `BookSource` can introduce `"case_study"`, `"clinical_scenario"` etc. without touching this file. Validation happens at the source level, not globally.

`source_section` remains free text — derived from authored Markdown headings, not our code.

### `CandidateChunk` (searcher output)
```python
@dataclass
class CandidateChunk:
    bias_id: str
    chunk_type: str         # string constant — e.g. CHUNK_TYPE_DEFINITION
    source_section: str     # original markdown heading: "Definition", "Examples", etc.
    chunk_text: str
    full_document: dict
    score: float
```

### `RetrievedBias` (reranker output)
```python
@dataclass
class RetrievedBias:
    bias_id: str
    score: float            # max chunk score
    matched_chunk_type: str # which chunk type drove the match
    matched_text: str       # the chunk text that scored highest
    definition: str
    examples: str
    indicators: str
    false_positives: str
    related_biases: str
```

### `BiasResult` (API DTO — response only)
```python
class BiasResult(BaseModel):
    id: str
    name: str
    score: float
    definition: str
    examples: str
    indicators: str
    false_positives: str
    related_biases: str
```

`matched_chunk_type` and `matched_text` are **not** in the API response. Log them server-side for debugging retrieval regressions.

---

## Project Structure

```
biassemble-rag/
├── knowledge/
│   ├── confirmation_bias.md
│   ├── anchoring_bias.md
│   ├── sunk_cost_fallacy.md
│   └── ...                        # one .md file per bias (~30 total)
├── src/
│   ├── api/
│   │   ├── routes/
│   │   │   └── retrieve.py        # POST /retrieve-biases
│   │   └── app.py                 # FastAPI app factory
│   ├── providers/
│   │   ├── base.py                # EmbeddingProvider abstract base class
│   │   └── sentence_transformer.py  # SentenceTransformerProvider — wraps sentence-transformers
│   ├── indexing/
│   │   ├── sources/
│   │   │   ├── base.py            # KnowledgeSource abstract base class
│   │   │   └── taxonomy.py        # TaxonomySource — reads knowledge/*.md
│   │   ├── normalizer.py          # markdown cleanup, heading validation, dedup
│   │   ├── chunk_builder.py       # source → chunks list (renamed from document_builder)
│   │   ├── embedder.py            # calls EmbeddingProvider
│   │   └── indexer.py             # orchestrates full indexing pipeline
│   ├── retrieval/
│   │   ├── query_builder.py       # QueryStrategy base + RepeatedStoryStrategy
│   │   ├── searcher.py            # pgvector cosine search → CandidateChunk[]
│   │   ├── reranker.py            # threshold filter + max-score collapse → RetrievedBias[]
│   │   └── retriever.py           # orchestrates pipeline, emits RetrievalMetadata
│   ├── evaluation/
│   │   └── evaluate.py            # Recall@K, Precision@K, MRR, Empty Retrieval Rate
│   ├── db/
│   │   ├── connection.py          # asyncpg pool
│   │   └── queries.py             # all SQL queries
│   ├── schemas/
│   │   ├── request.py             # RetrieveRequest
│   │   ├── response.py            # RetrieveResponse, BiasResult (API DTO)
│   │   └── internal.py            # CandidateChunk, RetrievedBias, RetrievalMetadata
│   └── config.py                  # settings from env vars
├── scripts/
│   ├── run_indexing.py            # CLI: full indexing pipeline
│   └── run_evaluation.py          # CLI: evaluate retrieval quality
├── artifacts/                     # gitignored intermediate outputs
│   ├── chunks.json                # output of document_builder step
│   └── embeddings.json            # output of embedder step
├── evaluations/
│   └── golden/
│       └── retrieval/             # labeled stories with expected bias IDs
│           ├── marcus_novatech.json
│           └── ...
├── migrations/
│   └── 001_create_bias_embeddings.sql
├── .env.example
├── .gitignore                     # includes .env, artifacts/
├── pyproject.toml
├── Dockerfile
├── railway.toml
└── README.md
```

---

## Knowledge Layer

### Format

Each bias lives in `knowledge/{bias_id}.md`. Free-form markdown. Sections are flexible — the document builder parses them.

Recommended sections per file:

```markdown
# Confirmation Bias

## Definition
...

## Examples
...

## Indicators
...

## False Positives
...

## Related Biases
...
```

The `false_positives` section is mandatory for every bias. It is the primary guard against Biassemble's core product risk.

### KnowledgeSource abstraction (`src/indexing/sources/base.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class RawDocument:
    bias_id: str
    chunk_type: str        # "definition", "examples", etc. — free text
    text: str
    source: str            # "taxonomy", "wiki", "paper", "manual"
    metadata: dict         # arbitrary — version, url, author, etc.

class KnowledgeSource(ABC):
    @abstractmethod
    def load(self) -> list[RawDocument]:
        ...
```

Only `TaxonomySource` exists initially. `WikipediaSource`, `PaperSource` can be added later without touching retrieval.

### TaxonomySource (`src/indexing/sources/taxonomy.py`)

Reads all `.md` files in `knowledge/`. Parses sections by `## Heading`. Each section → one `RawDocument`. Preserves the bias_id from filename.

---

## Database Schema

### `bias_embeddings` table

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS bias_embeddings (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bias_id          TEXT NOT NULL,
  chunk_type       TEXT NOT NULL,          -- semantic type: "semantic_definition", "semantic_example", etc.
  source_section   TEXT NOT NULL,          -- original markdown heading: "Definition", "Examples", etc.
  chunk_text       TEXT NOT NULL,          -- the text that was embedded
  chunk_hash       TEXT NOT NULL,          -- SHA256(bias_id + chunk_type + chunk_text + taxonomy_version) — changes when text or version changes
  full_document    JSONB NOT NULL,         -- all chunks for this bias, keyed by chunk_type
  embedding        vector(384),            -- all-MiniLM-L6-v2 dimension
  source           TEXT NOT NULL DEFAULT 'taxonomy',
  metadata         JSONB NOT NULL DEFAULT '{}',
  taxonomy_version TEXT NOT NULL,          -- e.g. "v1", "v2"
  embedding_model  TEXT NOT NULL,          -- e.g. "all-MiniLM-L6-v2"
  chunk_index      INTEGER NOT NULL DEFAULT 0,
  indexed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- lists = 10 is appropriate for ~150 chunks. Retune (sqrt(rows)) when corpus exceeds 1000 rows.
CREATE INDEX IF NOT EXISTS bias_embeddings_embedding_idx
  ON bias_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);

CREATE INDEX IF NOT EXISTS bias_embeddings_bias_id_idx
  ON bias_embeddings (bias_id);

CREATE INDEX IF NOT EXISTS bias_embeddings_source_idx
  ON bias_embeddings (source);

CREATE INDEX IF NOT EXISTS bias_embeddings_taxonomy_version_idx
  ON bias_embeddings (taxonomy_version);

-- Prevents duplicate inserts during re-index runs
CREATE UNIQUE INDEX IF NOT EXISTS bias_embeddings_dedup_idx
  ON bias_embeddings (taxonomy_version, bias_id, chunk_type, chunk_hash);

-- Enables domain filtering: WHERE metadata->>'domain' = 'finance'
CREATE INDEX IF NOT EXISTS bias_embeddings_metadata_idx
  ON bias_embeddings USING gin (metadata);
```

**Key design decision:** `full_document JSONB` stores all chunk types for the bias on every row. This means retrieval is **one query** — find the matching chunk, return the full document immediately. No second lookup needed.

**Denormalization is intentional.** Storage overhead is negligible (<1 MB for 30 biases × 5 chunks). Retrieval simplicity is prioritized over storage efficiency at this scale.

**`taxonomy_version` is immutable.** Never re-index into an existing version — bump it on every re-index run (`v1` → `v2`). If you edit a knowledge file and re-run indexing with the same version, you get two rows for the same `(bias_id, chunk_type)` — the old text and the new text. Both get returned by the searcher. Always treat `taxonomy_version` as a content snapshot identifier, not a mutable label.

**EmbeddingProvider swap requires schema migration.** The `dimension` property on `EmbeddingProvider` must be validated against the DB column on startup. Switching from `all-MiniLM-L6-v2` (384 dims) to `text-embedding-3-small` (1536 dims) requires `ALTER COLUMN embedding TYPE vector(1536)` or a new table. Document this in the migration when it happens.

**`taxonomy_version` + `embedding_model`:** required on every row. When you reindex with a new model or updated taxonomy, old rows remain intact. Delete by version when ready to clean up.

---

## Indexing Pipeline

### Execution flow

```
knowledge/*.md
      │
      ▼  TaxonomySource.load()
RawDocument[]
      │
      ▼  normalizer.normalize()      ← cleans markdown, validates headings, deduplicates
RawDocument[]
      │
      ▼  chunk_builder.build_chunks()
chunks  →  artifacts/chunks.json   (inspect here if debugging)
      │
      ▼  embedder.embed_batch()
embeddings  →  artifacts/embeddings.json   (inspect here if debugging)
      │
      ▼  indexer.insert()
bias_embeddings (PostgreSQL + pgvector)
```

Intermediate JSON artifacts are written to `artifacts/` (gitignored). They exist for debugging only — inspect them to verify text quality and embedding shape before inserting.

### `normalizer.py`

Taxonomy-specific. Sits between `TaxonomySource` and `chunk_builder`. Responsibilities:
- Strip excess whitespace and markdown artifacts
- Validate mandatory headings — **error** if `false_positives` missing
- Normalize heading aliases (`False Positive` → `False Positives`)
- Remove duplicate documents (same `bias_id` from two sources)

Does not touch embedding or chunking logic. Keeps `chunk_builder` pure.

**Scope:** this normalizer is for `TaxonomySource` only. Future sources (`BookSource`, `PaperSource`) own their own validation — they will not have `false_positives` headings and will have different structural rules. Do not generalize this normalizer.

### `chunk_builder.py`

Input: `list[RawDocument]`
Output: list of chunk dicts ready for embedding + insertion. Emits validation statistics — do not silently swallow problems.

```
Knowledge Validation
  30 biases | 150 chunks
  Missing false_positives: 0   ← warn if > 0
  Duplicate bias_ids: 0        ← error if > 0
  Broken related references: 1 ← warn
  Empty sections: 0            ← warn if > 0 (e.g. definition: "")
  Too short (<50 chars): 2     ← warn (e.g. definition: "Bias.")
  Too long (>5000 chars): 0    ← warn (authoring mistake, not a retrieval bug)
  Avg definition length: 312 chars
  Avg examples length: 480 chars
```

For each bias, build `full_document` dict:
```python
{
  "definition": "...",
  "examples": "...",
  "indicators": "...",
  "false_positives": "...",
  "related_biases": "..."
}
```

Each row gets this full dict in `full_document`. The `chunk_text` is the text for that specific chunk type. The bias name must be prepended to `chunk_text` for retrieval signal.

**`full_document` consistency rule:** build the complete `full_document` dict for each `bias_id` first, then attach the same object to all chunks for that bias. Never build `full_document` per-chunk — this guarantees all rows for a bias return identical document content regardless of which chunk the searcher matches.

`chunk_type` is the **semantic type** (`semantic_definition`, `semantic_example`, `semantic_false_positive`, etc.).
`source_section` is the **original markdown heading** (`Definition`, `Examples`, `False Positives`).

This separation allows later splitting one heading into multiple semantic chunk types without schema changes.

Example `chunk_text`: `"Confirmation Bias — Indicators: Seeks confirming evidence. Dismisses contradictory sources. Frames noise as anything that disagrees."`

`chunk_hash = SHA256(bias_id + chunk_type + chunk_text + taxonomy_version)` — computed by `chunk_builder`, stored on every row. Hash changes when text or taxonomy version changes, enabling safe dedup on re-index.

### `EmbeddingProvider` (`src/providers/base.py`)

Mirrors biassemble-core's `LLMProvider` / `GeminiProvider` pattern. Swap implementations without touching retrieval.

```python
class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...
    @property
    @abstractmethod
    def model_name(self) -> str: ...
    @property
    @abstractmethod
    def dimension(self) -> int: ...
```

`SentenceTransformerProvider` is the only implementation in v1. Load model once at construction — never reload per request.

### `embedder.py`

Thin orchestration layer. Accepts an `EmbeddingProvider`, delegates to it. Does not import `sentence_transformers` directly.

### `indexer.py`

Orchestrates: load → build → embed → write artifacts → insert.

On re-index: do not delete old rows. Insert new rows with updated `taxonomy_version`. Caller decides when to clean up old versions.

---

## Retrieval Pipeline

### Execution flow

```
RetrieveRequest { story, story_analysis? }
      │
      ▼  query_builder.build()
weighted query string
      │
      ▼  embedder.embed_query()
query vector
      │
      ▼  searcher.search(top_k=SEARCH_TOP_K)
top-K chunks with scores
      │
      ▼  reranker.apply_threshold(SIMILARITY_THRESHOLD)
filtered chunks  (may be empty)
      │
      ▼  reranker.collapse(top_k=RETURN_TOP_K)
top biases (0 to RETURN_TOP_K)
      │
      ▼
RetrieveResponse
```

### Query builder (`src/retrieval/query_builder.py`)

Query strategies are pluggable. The active strategy is selected via `QUERY_STRATEGY` config. This allows A/B evaluation without touching retrieval logic.

```python
class QueryStrategy(ABC):
    @abstractmethod
    def build(self, story: str, analysis: StoryAnalysis | None) -> str: ...

class RepeatedStoryStrategy(QueryStrategy):
    """Default. Truncates story to 100 words, repeats it, then appends analysis fields.

    Token limit: all-MiniLM-L6-v2 truncates input at 256 tokens (~200 words).
    A full story repeated twice would exceed this silently — themes/beliefs/claims
    would be cut off entirely. Truncating the story to 100 words before repeating
    leaves ~100 tokens for analysis fields within the 256-token budget.
    """
    MAX_STORY_WORDS = 100

    def build(self, story: str, analysis: StoryAnalysis | None) -> str:
        words = story.split()
        truncated = " ".join(words[:self.MAX_STORY_WORDS])
        parts = [truncated, truncated]
        if analysis:
            if analysis.themes:
                parts.append("Themes: " + ", ".join(analysis.themes))
            if analysis.beliefs:
                parts.append("Beliefs: " + ", ".join(analysis.beliefs))
            if analysis.claims:
                parts.append("Claims: " + ", ".join(analysis.claims))
        return " ".join(parts)
```

Active strategy is resolved via a registry — not if/elif:

```python
QUERY_STRATEGY_REGISTRY: dict[str, type[QueryStrategy]] = {
    "repeated_story": RepeatedStoryStrategy,
}

def get_query_strategy(name: str) -> QueryStrategy:
    cls = QUERY_STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown query strategy: {name}")
    return cls()
```

Only `RepeatedStoryStrategy` is implemented in v1. Add alternatives to the registry when evaluation baseline is established and you have a hypothesis to test.

### Searcher (`src/retrieval/searcher.py`)

Single SQL query. Returns `bias_id`, `chunk_type`, `chunk_text`, `full_document`, `score`.

```sql
SELECT
  bias_id,
  chunk_type,
  source_section,
  chunk_text,
  full_document,
  1 - (embedding <=> $1::vector) AS score
FROM bias_embeddings
WHERE taxonomy_version = $2
ORDER BY embedding <=> $1::vector
LIMIT $3;
```

Pass current `TAXONOMY_VERSION` from config so retrieval always uses the latest indexed version.

### Reranker (`src/retrieval/reranker.py`)

Two steps:

**Step 1 — Threshold filter:**
Drop any chunk with `score < SIMILARITY_THRESHOLD`. If nothing remains, return empty list. This is what allows the service to correctly return 0 biases for a story like "I ate pizza."

**Step 2 — Max-score collapse:**
Group remaining chunks by `bias_id`. Score each bias by `max(chunk_scores)` — not mean. A single highly relevant chunk is a strong signal. Sort descending. Return top `RETURN_TOP_K`.

Enrich each result from `full_document` — all chunk types are already available, no second query needed.

---

## Retrieval Observability

Every request emits structured log events with timing. Mirrors what `llm_calls` does in `biassemble-core` — retrieval becomes equally measurable.

### `RetrievalMetadata`

```python
@dataclass
class RetrievalMetadata:
    retrieval_id: str           # UUID — correlates all log events for one request
    embedding_model: str
    taxonomy_version: str
    query_strategy: str
    query_length: int           # chars in final query string
    embedding_latency_ms: int
    search_latency_ms: int
    rerank_latency_ms: int
    total_latency_ms: int
    candidate_chunks: int       # before threshold filter
    surviving_chunks: int       # after threshold filter
    returned_biases: int
    top_score: float | None
    avg_score: float | None
    threshold_used: float
```

### Structured log events per request

Every event carries `retrieval_id` for correlation.

```
retrieval_started   { retrieval_id, query_length, strategy }
query_embedded      { retrieval_id, latency_ms, model }
vector_search       { retrieval_id, latency_ms, candidate_chunks, top_score, avg_score }
reranked            { retrieval_id, surviving_chunks, returned_biases, threshold, matched_chunk_types }
completed           { retrieval_id, total_latency_ms, returned_biases }
```

Each event includes `retrieval_id`. Full `RetrievalMetadata` is emitted on `completed`. Log `matched_chunk_type` and `matched_text` on `reranked` — not in API response, but critical for debugging retrieval regressions.

`RetrievalMetadata` is **not** returned in the API response. It is written to structured logs only. Later this data can feed dashboards: embedding latency p95, threshold rejection rate, average returned biases per request.

---

## Graceful Degradation

| Failure | Behavior |
|---------|---------|
| DB down at startup | Log error, service starts, `/health` returns `database_connected: false` |
| DB down at request time | Return `503 {"error": "database_unavailable"}` — never return `biases: []` (indistinguishable from "no biases found") |
| Model fails to load | Startup crash — Railway restarts the container. Do not serve requests without a loaded model. |
| Model dimension mismatch | Startup crash — validate `provider.dimension` against `EMBEDDING_DIMENSION` config on startup. A corrupted model download can produce wrong-dimension vectors that insert silently and return garbage scores. Fail fast. |
| `taxonomy_version` not in DB | Return `503 {"error": "index_not_found", "taxonomy_version": "v1"}` — empty results here is a configuration bug, not a valid retrieval result |
| No chunks survive threshold | Return `200 {"biases": [], ...}` — this is the valid "no relevant biases" signal |

`biases: []` must only mean "retrieval ran successfully and found nothing above threshold." All other empty states must return 5xx.

---

## API

### `POST /retrieve-biases`

**Auth:** `Authorization: Bearer {RAG_API_KEY}` header. Return `401` if missing or invalid.

**Request body:**
```json
{
  "story": "string",
  "story_analysis": {
    "themes": ["string"],
    "beliefs": ["string"],
    "claims": ["string"]
  }
}
```
`story_analysis` is optional.

**Response:**
```json
{
  "biases": [
    {
      "id": "confirmation_bias",
      "name": "Confirmation Bias",
      "score": 0.87,
      "definition": "...",
      "examples": "...",
      "indicators": "...",
      "false_positives": "...",
      "related_biases": "..."
    }
  ],
  "retrieved_chunks": 12,
  "taxonomy_version": "v1",
  "embedding_model": "all-MiniLM-L6-v2"
}
```

`biases` may be empty if no chunks exceed `SIMILARITY_THRESHOLD`.
`retrieved_chunks` is the count before threshold filtering — useful for debugging without leaking internals.
`taxonomy_version` and `embedding_model` are included so callers know which index version served the response — critical when debugging evaluation regressions months later.
`query_used` is **not** in the response. Log it server-side only.

**Errors:**
- `401` — auth failure
- `422` — schema invalid (Pydantic automatic)
- `500` — `{ "error": "retrieval_failed", "detail": "..." }`

### `GET /health`

```json
{
  "status": "ok",
  "model_loaded": true,
  "embedding_dimension": 384,
  "embedding_model": "all-MiniLM-L6-v2",
  "taxonomy_version": "v1",
  "rows_indexed": 150,
  "last_indexed_at": "2026-06-27T10:00:00Z",
  "database_connected": true
}
```

`last_indexed_at` is the `MAX(indexed_at)` from `bias_embeddings` for the current `taxonomy_version`. A stale value here means the index was never updated after a knowledge change.

---

## Config (`src/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    rag_api_key: str
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384          # must match provider.dimension — validated on startup
    taxonomy_version: str = "v1"
    search_top_k: int = 20
    return_top_k: int = 5
    similarity_threshold: float = 0.45
    query_strategy: str = "repeated_story"   # pluggable query builder
    rerank_strategy: str = "max"             # "max" = max-score collapse. Placeholder — only "max" exists in v1. Add "mean" or cross-encoder variants here when evaluation justifies it.
    index_batch_size: int = 32               # embedding batch size
    log_level: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
```

All retrieval tuning parameters are in config, not hardcoded. `SEARCH_TOP_K`, `RETURN_TOP_K`, and `SIMILARITY_THRESHOLD` will all need tuning after the evaluation script produces real numbers. `QUERY_STRATEGY` and `RERANK_STRATEGY` enable experimentation without code changes.

`TAXONOMY_VERSION` is read-only after startup. Do not change it via hot reload or env mutation — half of in-flight requests would use one index version while the other half use another. Deploy a new instance to switch versions.

---

## Evaluation

### Golden dataset format (`evaluations/golden/retrieval/*.json`)

```json
{
  "scenario_id": "marcus_novatech",
  "story": "Marcus had bought in at $142...",
  "story_analysis": {
    "themes": ["investment", "sunk cost"],
    "beliefs": ["stock will recover"],
    "claims": []
  },
  "expected_bias_ids": [
    "confirmation_bias",
    "anchoring_bias",
    "sunk_cost_fallacy"
  ]
}
```

Seed from your existing `biassemble-core` golden dataset. The Marcus/NovaTech story and its known biases are already available.

**No-bias stories** use `expected_bias_ids: []`. Port at least 5 from `biassemble-core` no-bias dataset. These are required for threshold calibration — without them you cannot measure false retrieval rate and cannot tune `SIMILARITY_THRESHOLD`.

```json
{
  "scenario_id": "pizza_dinner",
  "story": "I had pizza for dinner and it was good.",
  "expected_bias_ids": []
}
```

Evaluate golden and no-bias stories separately. `empty_rate` on golden should be 0%. `empty_rate` on no-bias should be ~100%.

### Evaluation script (`src/evaluation/evaluate.py`)

Metrics per scenario:

- **Recall@K** — fraction of expected biases in top-K results. Primary metric. `recall = len(expected ∩ retrieved) / len(expected)`
- **Precision@K** — fraction of retrieved biases that were expected. `precision = len(expected ∩ retrieved) / len(retrieved)`
- **MRR** — Mean Reciprocal Rank. `1 / rank` of the first correct hit. Measures how early the right answer appears.
- **Empty Retrieval Rate** — fraction of scenarios returning `biases: []`. Should be 0% on golden stories, ~100% on no-bias stories. Track separately per dataset type.
- **Coverage** — count of distinct `bias_id`s ever retrieved across all scenarios. Meaningful only after 20+ diverse scenarios — at 5 stories only ~10 biases can be expected, so 10/30 is not a quality signal. Flag as post-launch metric; track it but don't gate launch on it.

Aggregate across all scenarios: mean Recall@K, mean Precision@K, mean MRR, empty retrieval rate, coverage count.

### CLI (`scripts/run_evaluation.py`)

Output format:

```
Evaluation — biassemble-rag
Model: all-MiniLM-L6-v2  |  Taxonomy: v1  |  Threshold: 0.45  |  K: 5  |  Strategy: repeated_story

scenario               expected    retrieved   recall@5    precision@5   mrr
────────────────────────────────────────────────────────────────────────────
marcus_novatech        3           3           1.00        1.00          1.00
...

AGGREGATE   recall@5: 0.91   precision@5: 0.74   mrr: 0.88   empty_rate: 0.00   coverage: 18/30
```

**Run evaluation after every change to:**
- Embedding model
- Similarity threshold
- `SEARCH_TOP_K` / `RETURN_TOP_K`
- Knowledge documents
- Query builder logic or strategy

This is the only way to know if a change improved or degraded retrieval. Do not tune blind.

---

## Environment Variables (`.env.example`)

```
DATABASE_URL=postgresql://postgres:[password]@[host]:5432/postgres
RAG_API_KEY=your-secret-key-here
EMBEDDING_MODEL=all-MiniLM-L6-v2
TAXONOMY_VERSION=v1
SEARCH_TOP_K=20
RETURN_TOP_K=5
SIMILARITY_THRESHOLD=0.45
LOG_LEVEL=INFO
```

---

## pyproject.toml

```toml
[project]
name = "biassemble-rag"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.3.0",
    "sentence-transformers>=3.0.0",
    "asyncpg>=0.29.0",
    "pgvector>=0.3.0",
    "structlog>=24.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",     # for TestClient only
    "ruff>=0.4.0",
    "mypy>=1.10.0",
]
eval = [
    "pandas>=2.0.0",     # for run_evaluation.py — metrics tables, CSV export, run comparison
]

# httpx as a runtime dep: add when WikipediaSource or other external knowledge sources are implemented
```

---

## Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache .

COPY . .

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## railway.toml

```toml
[build]
builder = "dockerfile"

[deploy]
startCommand = "uvicorn src.api.app:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
healthcheckTimeout = 300
restartPolicyType = "on_failure"
```

---

## Tests

### `tests/test_chunk_builder.py`
- Each bias produces at least one chunk per section present in the `.md` file
- `bias_id` matches filename
- `chunk_text` contains the bias name
- `full_document` contains all parsed sections as keys
- `chunk_type` and `source_section` are both populated and distinct
- `chunk_hash` is a non-empty string (SHA256)
- `false_positives` section is present — validation output warns if missing

### `tests/test_reranker.py`
- Chunks below `SIMILARITY_THRESHOLD` are dropped before collapse
- Returns empty list if all chunks below threshold
- Returns biases sorted by score descending
- No duplicate `bias_id` in output
- Respects `RETURN_TOP_K` cap

### `tests/test_retrieve_endpoint.py`
- Returns `401` without valid auth header
- Valid request returns `200` with `biases` array
- Each bias in response has all required fields
- `biases` can be empty (threshold filtering)
- `retrieved_chunks` is present in response

### `tests/test_query_builder.py`
- `RepeatedStoryStrategy`: story text appears twice in output (weight boost)
- `story_analysis` fields are labelled and appended
- Works correctly with `story_analysis=None`
- `QueryStrategy` base class is ABC — cannot instantiate directly

---

## Implementation Order

1. Set up repo with uv, install dependencies, configure `.env`
2. Write `migrations/001_create_bias_embeddings.sql`, apply to Supabase
3. Write `knowledge/*.md` files for all ~30 biases (mandatory: `false_positives` section on every file)
4. Implement `KnowledgeSource` base class + `TaxonomySource`
5. Implement `normalizer.py` — heading validation, dedup, markdown cleanup
6. Implement `chunk_builder.py` — write tests, verify `chunks.json` output, check validation stats
7. Implement `embedder.py`
8. Implement `indexer.py` + `scripts/run_indexing.py`
9. Run indexing — verify 150+ rows in Supabase, inspect `artifacts/chunks.json` and `artifacts/embeddings.json`
10. Seed `evaluations/golden/retrieval/` — at least 3 golden stories (with expected biases) + at least 5 no-bias stories (`expected_bias_ids: []`) ported from `biassemble-core`
11. Implement `evaluate.py` + `scripts/run_evaluation.py` — **uses raw SQL against `bias_embeddings` directly, not the retrieval pipeline**. This isolates embedding quality from retrieval code. Pass query vector in, get ranked results back, compute Recall@K, Precision@K, MRR, Empty Retrieval Rate.
12. Run evaluation — establish embedding baseline (Recall@5, empty_rate) before writing any retrieval code
13. Implement `query_builder.py` with `QueryStrategy` base + `RepeatedStoryStrategy` — write tests
14. Implement `searcher.py` → returns `CandidateChunk[]`
15. Implement `reranker.py` → returns `RetrievedBias[]` — write tests
16. Implement `retriever.py` — orchestrates pipeline, emits `RetrievalMetadata` structured logs
17. Update `evaluate.py` to use the retrieval pipeline instead of raw SQL — run evaluation again, confirm metrics equal or better than step 12 baseline
18. Implement FastAPI app + `/retrieve-biases` + `/health` — write endpoint tests
19. Dockerfile + railway.toml
20. Deploy to Railway, verify `/health` response
21. Update `biassemble-core` to call this service before building assessment prompt

---

## Success Criteria

- `run_indexing.py` produces at least 150 rows in `bias_embeddings` (30 biases × minimum 5 chunks each — this is the floor, not the target)
- `POST /retrieve-biases` responds in under 300ms (embedding + vector search)
- Marcus/NovaTech story returns Confirmation Bias, Anchoring Bias, Sunk Cost Fallacy in top 5
- Aggregate Recall@5 ≥ 0.85 across golden dataset
- "I ate pizza" story returns `biases: []` (threshold filter working)
- All tests pass
- `/health` returns `database_connected: true`, correct `rows_indexed`
- Service deployed and reachable from `biassemble-core`

---

## biassemble-core Integration Contract

When `biassemble-core` calls this service (step 21), the following must be defined:

| Concern | Decision |
|---------|---------|
| Where in pipeline | Before building assessment prompt — retrieved biases replace static taxonomy injection |
| Timeout | 500ms. If exceeded, fall back to static taxonomy (do not fail the assessment) |
| Failure fallback | Any 4xx/5xx or timeout → use full static bias catalog as context. Log the failure. Never surface RAG errors to the user. |
| Auth | `Authorization: Bearer {RAG_API_KEY}` — shared secret via env var in both services |
| Call site | `assessment.service.ts` before prompt construction |

The fallback to static taxonomy ensures biassemble-core degrades gracefully if biassemble-engine is down, slow, or returning errors.

---

## What Is Explicitly Out of Scope

- Wikipedia / external knowledge sources — add after evaluation baseline is established
- Cross-encoder reranking — max-score collapse is sufficient for now
- Hybrid search (BM25 + vector) — revisit after measuring pure vector recall
- Caching layer — add after latency is measured in production
- LangChain / LlamaIndex — do not introduce
- Fine-tuning embeddings — not justified at this scale
