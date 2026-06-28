# Implementation Plan: Semantic Bias Retrieval Service

**Branch**: `001-rag-retrieval` | **Date**: 2026-06-27 | **Spec**: [spec.md](spec.md)

## Summary

Build a Python RAG microservice that replaces static bias taxonomy injection in `biassemble-core` with dynamic semantic retrieval. Given a news story, the service returns the most relevant cognitive biases from a pre-indexed knowledge base using cosine similarity search on sentence embeddings. Architecture: indexing pipeline (markdown documents → embeddings → pgvector) + retrieval pipeline (story → query vector → cosine search → threshold filter → max-score collapse) + FastAPI HTTP interface.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: FastAPI 0.115+, Pydantic v2, pydantic-settings, sentence-transformers 3.0+ (`all-MiniLM-L6-v2`), asyncpg 0.29+, pgvector 0.3+, structlog 24+, uvicorn

**Storage**: PostgreSQL + pgvector extension via Supabase (same instance as biassemble-core). Table: `bias_embeddings`. Vector dimension: 384 (all-MiniLM-L6-v2).

**Testing**: pytest + pytest-asyncio, httpx (TestClient only)

**Target Platform**: Linux server (Railway persistent container)

**Project Type**: Web service (microservice)

**Performance Goals**: Retrieval p95 < 300ms, health endpoint < 50ms

**Constraints**: Memory < 1 GB total; embedding model loaded once at startup; no LLM or external AI API calls; deterministic retrieval for identical inputs and index version

**Scale/Scope**: ~30 biases × 5 chunks = ~150 rows in bias_embeddings for v1. Concurrent requests supported; no serialization.

**Package Manager**: uv (not pip, not poetry)

**Linting / Type checking**: Ruff + mypy

## Constitution Check

Constitution template not yet filled — no gates defined. Proceeding without gate violations.

Post-design review: no patterns introduced that conflict with simplicity, observability, or testability principles visible in biassemble-core conventions.

## Project Structure

### Documentation (this feature)

```text
specs/001-rag-retrieval/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── contracts/           ← Phase 1 output
│   ├── retrieve-biases.md
│   └── health.md
├── checklists/
│   └── requirements.md
└── tasks.md             ← /speckit-tasks output (not yet created)
```

### Source Code (repository root)

```text
biassemble-engine/
├── knowledge/                         # authored bias documents (one .md per bias)
│   ├── STYLE_GUIDE.md                 # authoring conventions (tone, section lengths, naming)
│   ├── confirmation_bias.md
│   ├── anchoring_bias.md
│   └── ...                            # ~30 files total
├── src/
│   ├── api/
│   │   ├── routes/
│   │   │   └── retrieve.py            # POST /retrieve-biases, GET /health, GET /stats
│   │   └── app.py                     # FastAPI app factory + lifespan
│   ├── providers/
│   │   ├── base.py                    # EmbeddingProvider ABC
│   │   └── sentence_transformer.py    # SentenceTransformerProvider
│   ├── indexing/
│   │   ├── sources/
│   │   │   ├── base.py                # KnowledgeSource ABC + RawDocument
│   │   │   └── taxonomy.py            # TaxonomySource (reads knowledge/*.md)
│   │   ├── normalizer.py              # markdown cleanup, heading validation
│   │   ├── chunk_builder.py           # RawDocument[] → chunks + full_document
│   │   ├── embedder.py                # calls EmbeddingProvider
│   │   └── indexer.py                 # orchestrates full indexing pipeline
│   ├── retrieval/
│   │   ├── query_builder.py           # QueryStrategy ABC + RepeatedStoryStrategy
│   │   ├── searcher.py                # pgvector cosine search → CandidateChunk[]
│   │   ├── reranker.py                # threshold filter + max-score collapse → RetrievedBias[]
│   │   └── retriever.py               # orchestrates pipeline, emits RetrievalMetadata
│   ├── evaluation/
│   │   └── evaluate.py                # Recall@K, Precision@K, MRR, Empty Retrieval Rate
│   ├── db/
│   │   ├── connection.py              # asyncpg pool
│   │   └── queries.py                 # all SQL queries
│   ├── schemas/
│   │   ├── request.py                 # RetrieveRequest
│   │   ├── response.py                # RetrieveResponse, BiasResult
│   │   └── internal.py                # CandidateChunk, RetrievedBias, RetrievalMetadata
│   └── config.py                      # Settings from env vars (pydantic-settings)
├── scripts/
│   ├── run_indexing.py                # CLI: full indexing pipeline
│   └── run_evaluation.py              # CLI: evaluate retrieval quality
├── artifacts/                         # gitignored — debug outputs
│   ├── chunks.json
│   └── embeddings.json
├── evaluations/
│   ├── positive/                      # stories with known expected biases
│   │   ├── marcus_novatech.json
│   │   └── ...
│   ├── negative/                      # stories with no bias (expected_bias_ids: [])
│   │   ├── pizza_dinner.json
│   │   └── ...
│   ├── edge/                          # ambiguous cases for threshold calibration
│   ├── adversarial/                   # robustness benchmark (satire, manipulation, hallucinations)
│   ├── regression/                    # permanent bug record — grows forever, never shrinks
│   ├── baselines/                     # promoted reference snapshots
│   │   └── baseline_2026-06-27.json
│   └── runs/                          # every evaluation run output (auto-named by date)
├── migrations/
│   └── 001_create_bias_embeddings.sql
├── tests/
│   ├── test_chunk_builder.py
│   ├── test_reranker.py
│   ├── test_query_builder.py
│   └── test_retrieve_endpoint.py
├── .env
├── .env.example
├── .gitignore
├── pyproject.toml
├── Dockerfile                         # added at implementation step 19
├── railway.toml                       # added at implementation step 19
└── README.md
```

**Structure Decision**: Single project, Python package under `src/`. No monorepo — standalone microservice with its own repo and deploy target.

## Implementation Order

The sequence ensures each step is runnable or inspectable before the next. Evaluation uses the actual retrieval pipeline — no separate raw SQL path. If embedding quality needs isolated measurement, use a `"pure_vector"` QueryStrategy variant rather than a separate code path.

| Step | What | Checkpoint |
|------|------|-----------|
| 1 | pyproject.toml, uv sync, configure .env | `uv run python -c "import fastapi"` succeeds |
| 2 | migrations/001_create_bias_embeddings.sql, apply to Supabase | Table visible in Supabase dashboard |
| 3 | knowledge/*.md — all ~30 bias files with false_positives | File count matches bias list |
| 4 | KnowledgeSource ABC + TaxonomySource | `TaxonomySource().load()` returns RawDocument list |
| 5 | normalizer.py | Missing false_positives raises validation error |
| 6 | chunk_builder.py + tests | chunks.json written, validation stats printed |
| 7 | EmbeddingProvider ABC + SentenceTransformerProvider | `provider.embed_query("test")` returns 384-dim vector |
| 8 | embedder.py + indexer.py + scripts/run_indexing.py | Script runs end-to-end without errors |
| 9 | Run indexing, verify 150+ rows in Supabase | Inspect artifacts/chunks.json and embeddings.json |
| 10 | Seed evaluations/ — 3+ positive + 5+ negative + edge stories | Files parseable as JSON |
| 11 | query_builder.py (QueryStrategy + RepeatedStoryStrategy) + tests | Tests pass |
| 12 | searcher.py → CandidateChunk[] | Manual test: embed query, call searcher, inspect results |
| 13 | reranker.py → RetrievedBias[] + tests | Tests pass including threshold=1.0 → empty list |
| 14 | retriever.py — orchestrates pipeline, emits structured logs + trace artifact | End-to-end retrieval works in isolation |
| 15 | evaluate.py + scripts/run_evaluation.py using retrieval pipeline | Recall@5, MRR, nDCG printed per scenario and aggregate |
| 16 | Run evaluation — save baseline snapshot to evaluations/baselines/baseline_v1.json | Recall@5 ≥ 0.85; empty_rate ~100% on negative stories |
| 17 | FastAPI app + /retrieve-biases + /health + /stats + endpoint tests | `uv run pytest` green; manual curl works |
| 18 | Dockerfile + railway.toml | `docker build` succeeds locally |
| 19 | Deploy to Railway, verify /health and /stats | rows_indexed > 0, database_connected: true |
| 20 | Update biassemble-core to call this service | End-to-end: story → RAG → LLM prompt → assessment |

## Complexity Tracking

No violations — no abstractions introduced beyond what the spec requires.
