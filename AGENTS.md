# AGENTS.md — biassemble-engine

## Commands

```bash
uv sync                          # Install dependencies
uv run uvicorn src.api.app:app --reload  # Start dev server
uv run pytest                    # Run tests (all)
uv run pytest tests/unit/        # Unit tests only
uv run pytest tests/integration/ # Integration tests (needs DB)
uv run mypy src/                 # Type checking
uv run ruff check src/           # Linting
uv run ruff format src/          # Formatting
python scripts/run_indexing.py   # Full indexing pipeline
python scripts/run_evaluation.py # Evaluate retrieval quality
```

## Current State

- Active stage: check spec `biassemble-rag-spec-v1.md` for implementation order
- DB: Supabase (same instance as biassemble-core, separate table `bias_embeddings`)
- Index: not yet populated — run `scripts/run_indexing.py` after knowledge files are written

## Repository Structure

```
/home/dl/_prog/biassemble/
├── biassemble/          ← App repo (BE + FE)
├── biassemble-core/     ← Core TS repo (LLM pipeline)
└── biassemble-engine/   ← THIS REPO — Python RAG service
```

Each repo has its own `.git`, branch, and deploy target. They are independent.

## Critical Rules

1. **Pure retriever** — This service never calls an LLM. No LLM imports, no prompt construction.
2. **Dependency direction** — `biassemble-core` → `biassemble-engine` → `pgvector`. Never reversed.
3. **No LangChain / LlamaIndex** — Raw primitives only. If you reach for a framework, stop.
4. **ChunkType is an enum** — Never pass raw strings where `ChunkType` is expected.
5. **EmbeddingProvider is the boundary** — `embedder.py` never imports `sentence_transformers` directly.
6. **Validate at ingestion** — `normalizer.py` and `chunk_builder.py` must emit warnings/errors. No silent failures.
7. **RetrievalMetadata on every request** — Every retrieval must emit structured logs with `retrieval_id`.
8. **taxonomy_version is read-only after startup** — Never change it at runtime.
9. **Evaluation before tuning** — Establish baseline Recall@5 before touching threshold/top-k.
10. **Scope discipline** — Do only what was explicitly asked.
11. **Single-line commits** — `feat: add chunk_builder`, not multi-line bodies.

## Architecture Boundaries

| Module | Owns | Does NOT own |
|--------|------|-------------|
| `normalizer.py` | Heading validation, dedup, whitespace | Chunking, embedding |
| `chunk_builder.py` | Chunking, full_document construction, chunk_hash | Normalization, embedding |
| `embedder.py` | Calls `EmbeddingProvider` | Imports sentence_transformers directly |
| `searcher.py` | SQL query → `CandidateChunk[]` | Reranking, threshold filtering |
| `reranker.py` | Threshold filter, max-score collapse → `RetrievedBias[]` | Embedding, search |
| `retriever.py` | Orchestration, `RetrievalMetadata` emission | Business logic |

## Git Convention

Format: `<tag>(<scope>): <short description>`

Tags: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`, `perf:`

Examples:
- `feat(indexing): add normalizer with heading validation`
- `feat(retrieval): implement max-score reranker`
- `fix: correct chunk_hash to include taxonomy_version`

**Single-line commit messages only.**

## When To Ask

### Act without asking:
- Fix typos, lint errors, type errors
- Add missing null checks
- Improve tests within the same module
- Refactor ≤1 file with zero behavior change

### Ask before acting:
- Changes to DB schema or migrations
- Adding/removing dependencies
- Changing `EmbeddingProvider` interface
- Modifying API request/response schema
- Committing code — show summary first
- Any work beyond the explicitly stated task

## Skills

Load these skill files when working on related tasks:

- `.skills/rag-pipeline.md` — Retrieval flow, CandidateChunk → RetrievedBias → BiasResult
- `.skills/indexing-pipeline.md` — TaxonomySource, normalizer, chunk_builder, embedder, indexer
- `.skills/embedding-provider.md` — EmbeddingProvider ABC, SentenceTransformerProvider
- `.skills/evaluation.md` — Recall@K, Precision@K, MRR, Coverage, golden dataset format

## Docs

- `biassemble-rag-spec-v1.md` — Full service specification (source of truth)

## Forbidden

- LangChain, LlamaIndex, or any LLM orchestration framework
- SQLAlchemy or any ORM — raw asyncpg SQL only
- Calling an LLM from this service
- Silent ingestion failures (warn or error explicitly)
- Global mutable state
- Adding dependencies without explicit approval
- Committing `.env` or secrets
- Hot-reloading `taxonomy_version` at runtime
