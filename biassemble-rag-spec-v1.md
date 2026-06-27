# biassemble-rag — Service Specification v1.0

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
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`) |
| Database client | asyncpg |
| Vector operations | pgvector Python client |
| External HTTP | httpx (for future knowledge sources) |
| Package manager | uv |
| Tests | pytest + pytest-asyncio |
| Deploy | Railway (Dockerfile) |

No LangChain. No LlamaIndex. Raw primitives only.

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
│   ├── indexing/
│   │   ├── sources/
│   │   │   ├── base.py            # KnowledgeSource abstract base class
│   │   │   └── taxonomy.py        # TaxonomySource — reads knowledge/*.md
│   │   ├── document_builder.py    # source → chunks list
│   │   ├── embedder.py            # sentence-transformers wrapper
│   │   └── indexer.py             # orchestrates full indexing pipeline
│   ├── retrieval/
│   │   ├── query_builder.py       # builds weighted retrieval query string
│   │   ├── searcher.py            # pgvector cosine search
│   │   ├── reranker.py            # threshold filter + max-score collapse
│   │   └── retriever.py           # orchestrates retrieval pipeline
│   ├── evaluation/
│   │   └── evaluate.py            # Recall@K, Precision@K against golden dataset
│   ├── db/
│   │   ├── connection.py          # asyncpg pool
│   │   └── queries.py             # all SQL queries
│   ├── schemas/
│   │   ├── request.py             # RetrieveRequest
│   │   └── response.py            # RetrieveResponse, BiasResult
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
  chunk_type       TEXT NOT NULL,          -- free text, not enum
  chunk_text       TEXT NOT NULL,          -- the text that was embedded
  full_document    JSONB NOT NULL,         -- all chunks for this bias, keyed by chunk_type
  embedding        vector(384),            -- all-MiniLM-L6-v2 dimension
  source           TEXT NOT NULL DEFAULT 'taxonomy',
  metadata         JSONB NOT NULL DEFAULT '{}',
  taxonomy_version TEXT NOT NULL,          -- e.g. "v1", "v2"
  embedding_model  TEXT NOT NULL,          -- e.g. "all-MiniLM-L6-v2"
  chunk_index      INTEGER NOT NULL DEFAULT 0,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
```

**Key design decision:** `full_document JSONB` stores all chunk types for the bias on every row. This means retrieval is **one query** — find the matching chunk, return the full document immediately. No second lookup needed.

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
      ▼  document_builder.build_chunks()
chunks  →  artifacts/chunks.json   (inspect here if debugging)
      │
      ▼  embedder.embed_batch()
embeddings  →  artifacts/embeddings.json   (inspect here if debugging)
      │
      ▼  indexer.insert()
bias_embeddings (PostgreSQL + pgvector)
```

Intermediate JSON artifacts are written to `artifacts/` (gitignored). They exist for debugging only — inspect them to verify text quality and embedding shape before inserting.

### `document_builder.py`

Input: `list[RawDocument]`
Output: list of chunk dicts ready for embedding + insertion.

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

Example `chunk_text`: `"Confirmation Bias — Indicators: Seeks confirming evidence. Dismisses contradictory sources. Frames noise as anything that disagrees."`

### `embedder.py`

Load `SentenceTransformer` once at module level. Never reload per request.

```python
embed_texts(texts: list[str]) -> list[list[float]]   # batch, for indexing
embed_query(text: str) -> list[float]                 # single, for retrieval
```

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

Weight the story higher than analysis fields. Repeat story text to increase its signal weight in the embedding.

```python
def build(story: str, analysis: StoryAnalysis | None) -> str:
    parts = [story, story]   # story repeated — higher weight
    if analysis:
        if analysis.themes:
            parts.append("Themes: " + ", ".join(analysis.themes))
        if analysis.beliefs:
            parts.append("Beliefs: " + ", ".join(analysis.beliefs))
        if analysis.claims:
            parts.append("Claims: " + ", ".join(analysis.claims))
    return " ".join(parts)
```

### Searcher (`src/retrieval/searcher.py`)

Single SQL query. Returns `bias_id`, `chunk_type`, `chunk_text`, `full_document`, `score`.

```sql
SELECT
  bias_id,
  chunk_type,
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
  "retrieved_chunks": 12
}
```

`biases` may be empty if no chunks exceed `SIMILARITY_THRESHOLD`.
`retrieved_chunks` is the count before threshold filtering — useful for debugging without leaking internals.
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
  "database_connected": true
}
```

---

## Config (`src/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    rag_api_key: str
    embedding_model: str = "all-MiniLM-L6-v2"
    taxonomy_version: str = "v1"
    search_top_k: int = 20
    return_top_k: int = 5
    similarity_threshold: float = 0.45
    log_level: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
```

All retrieval tuning parameters are in config, not hardcoded. `SEARCH_TOP_K`, `RETURN_TOP_K`, and `SIMILARITY_THRESHOLD` will all need tuning after the evaluation script produces real numbers.

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

### Evaluation script (`src/evaluation/evaluate.py`)

Metrics per scenario:

- **Recall@K** — fraction of expected biases present in top-K results. Primary metric. `recall = len(expected ∩ retrieved) / len(expected)`
- **Precision@K** — fraction of retrieved biases that were expected. `precision = len(expected ∩ retrieved) / len(retrieved)`

Aggregate across all scenarios: mean Recall@K, mean Precision@K.

### CLI (`scripts/run_evaluation.py`)

Output format:

```
Evaluation — biassemble-rag
Model: all-MiniLM-L6-v2  |  Taxonomy: v1  |  Threshold: 0.45  |  K: 5

scenario               expected    retrieved   recall@5    precision@5
──────────────────────────────────────────────────────────────────────
marcus_novatech        3           3           1.00        1.00
...

AGGREGATE              mean recall@5: 0.91     mean precision@5: 0.74
```

**Run evaluation after every change to:**
- Embedding model
- Similarity threshold
- `SEARCH_TOP_K` / `RETURN_TOP_K`
- Knowledge documents
- Query builder logic

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
    "python-dotenv>=1.0.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
]
```

---

## Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system .

COPY . .

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

### `tests/test_document_builder.py`
- Each bias produces at least one chunk per section present in the `.md` file
- `bias_id` matches filename
- `chunk_text` contains the bias name
- `full_document` contains all parsed sections as keys
- `false_positives` section is present (warn if missing)

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
- Story text appears twice in output (weight boost)
- `story_analysis` fields are labelled and appended
- Works correctly with `story_analysis=None`

---

## Implementation Order

1. Set up repo with uv, install dependencies, configure `.env`
2. Write `migrations/001_create_bias_embeddings.sql`, apply to Supabase
3. Write `knowledge/*.md` files for all ~30 biases (mandatory: `false_positives` section on every file)
4. Implement `KnowledgeSource` base class + `TaxonomySource`
5. Implement `document_builder.py` — write tests, verify `chunks.json` output
6. Implement `embedder.py`
7. Implement `indexer.py` + `scripts/run_indexing.py`
8. Run indexing — verify 150+ rows in Supabase, inspect `artifacts/chunks.json` and `artifacts/embeddings.json`
9. Seed `evaluations/golden/retrieval/` with Marcus/NovaTech and at least 2 other stories from `biassemble-core` golden dataset
10. Implement `evaluate.py` + `scripts/run_evaluation.py`
11. Run evaluation — establish baseline Recall@5 and Precision@5 before touching retrieval logic
12. Implement `query_builder.py` — write tests
13. Implement `searcher.py`
14. Implement `reranker.py` — write tests
15. Implement `retriever.py`
16. Run evaluation again — confirm metrics equal or better than baseline
17. Implement FastAPI app + `/retrieve-biases` + `/health` — write endpoint tests
18. Dockerfile + railway.toml
19. Deploy to Railway, verify `/health` response
20. Update `biassemble-core` to call this service before building assessment prompt

---

## Success Criteria

- `run_indexing.py` produces 150+ rows in `bias_embeddings` (30 biases × 5+ chunk types)
- `POST /retrieve-biases` responds in under 300ms (embedding + vector search)
- Marcus/NovaTech story returns Confirmation Bias, Anchoring Bias, Sunk Cost Fallacy in top 5
- Aggregate Recall@5 ≥ 0.85 across golden dataset
- "I ate pizza" story returns `biases: []` (threshold filter working)
- All tests pass
- `/health` returns `database_connected: true`, correct `rows_indexed`
- Service deployed and reachable from `biassemble-core`

---

## What Is Explicitly Out of Scope

- Wikipedia / external knowledge sources — add after evaluation baseline is established
- Cross-encoder reranking — max-score collapse is sufficient for now
- Hybrid search (BM25 + vector) — revisit after measuring pure vector recall
- Caching layer — add after latency is measured in production
- LangChain / LlamaIndex — do not introduce
- Fine-tuning embeddings — not justified at this scale
