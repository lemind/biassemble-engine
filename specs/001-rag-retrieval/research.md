# Research: Semantic Bias Retrieval Service

**Date**: 2026-06-27 | **Branch**: `001-rag-retrieval`

No NEEDS CLARIFICATION items — all technical decisions were pre-specified. This document records decisions, rationale, and alternatives considered.

---

## HTTP Framework

**Decision**: FastAPI

**Rationale**: Async-native, Pydantic v2 integration built-in, automatic OpenAPI docs, minimal boilerplate for a microservice with 2 endpoints. Standard choice for Python ML-serving APIs.

**Alternatives considered**:
- Flask — synchronous by default, no Pydantic integration, more boilerplate
- Starlette — FastAPI is Starlette with extras; no reason to drop down
- Django — far too heavy for a 2-endpoint microservice

---

## Database Client

**Decision**: asyncpg (raw)

**Rationale**: Async-native PostgreSQL driver with the lowest overhead. pgvector operations require raw SQL (`<=>` operator); no ORM can generate this cleanly. Raw SQL is also more readable in interviews — the query intent is explicit.

**Alternatives considered**:
- SQLAlchemy async — adds abstraction that obscures the vector similarity query; harder to explain; adds dependency weight
- psycopg3 — good alternative but asyncpg has better performance benchmarks and wider adoption in Python async services
- Databases (encode) — thin wrapper over asyncpg but adds indirection without benefit

---

## Embedding Model

**Decision**: `all-MiniLM-L6-v2` via sentence-transformers

**Rationale**: 384-dim vectors, ~80MB model weight, CPU-friendly (no GPU required on Railway), 256-token context window. Fast enough for sub-300ms p95 target. Well-understood quality for semantic similarity. Free, runs locally — no API cost per request.

**Token limit awareness**: 256 tokens (~200 words). Query builder truncates story to 100 words before repeating, leaving budget for analysis fields.

**Alternatives considered**:
- OpenAI text-embedding-3-small — 1536 dims, API cost per request, latency unpredictable, adds external dependency
- text-embedding-ada-002 — deprecated
- bge-small-en — comparable quality to MiniLM but less adoption and fewer resources
- Fine-tuned model — not justified at this scale and data volume

---

## Vector Store

**Decision**: pgvector on Supabase (same PostgreSQL instance as biassemble-core)

**Rationale**: No new infrastructure. Supabase already provisioned, credentials already available. pgvector IVFFlat index with `lists=10` is appropriate for ~150 chunks (retune at sqrt(rows) if corpus exceeds 1000). Cosine similarity via `<=>` operator.

**Alternatives considered**:
- Pinecone — managed vector DB, adds cost and external dependency; overkill for 150 chunks
- Weaviate — self-hosted complexity; no benefit over pgvector at this scale
- Qdrant — similar story to Weaviate
- In-memory FAISS — no persistence across restarts; Railway containers restart on deploy

---

## Structured Logging

**Decision**: structlog

**Rationale**: Python-native structured logging. Each retrieval request emits typed events with `retrieval_id` for correlation. Mirrors what `biassemble-core` uses. Output is JSON-parseable for log aggregators.

**Alternatives considered**:
- Python stdlib `logging` — unstructured by default; adding structure requires significant boilerplate
- loguru — better DX but less common in production Python services; structlog more battle-tested

---

## Package Manager

**Decision**: uv

**Rationale**: Fast, reproducible, lockfile-based. `uv sync` installs all dependencies in seconds. `uv run` runs commands in the project virtualenv without activation. Recommended for new Python projects in 2025+.

**Alternatives considered**:
- pip + venv — slower, no lockfile by default
- poetry — slower than uv, more opinionated, larger footprint
- conda — wrong tool for a web service

---

## No LangChain / LlamaIndex

**Decision**: Raw primitives only

**Rationale**: Every abstraction in this service must be explainable in an interview. LangChain's retrieval chains hide the cosine query, the threshold logic, and the collapse step — exactly the parts a hiring manager for an LLM engineering role will ask about. Using raw asyncpg + pgvector makes the retrieval logic transparent and shows understanding of what RAG actually does.

**Alternatives considered**:
- LangChain — hides implementation details; version churn is high; not appropriate for a portfolio project demonstrating understanding
- LlamaIndex — same concern; adds abstraction overhead without benefit at this scale

---

## Deployment

**Decision**: Railway (persistent Docker container)

**Rationale**: The embedding model (~80MB) must be loaded into memory at startup. Serverless (Vercel, Lambda) is incompatible — cold starts would reload the model on every request. Railway provides persistent containers with health check support and `$PORT` env injection. Docker image is portable to Fly.io, Render, or DO App Platform with zero code changes.

**Alternatives considered**:
- Vercel — serverless only; model reload latency unacceptable
- AWS Lambda — same issue; also adds IAM complexity
- Fly.io — viable alternative but Railway is simpler to configure for this scale
- Self-hosted — unnecessary complexity for a portfolio project

---

## Embedding Provider Abstraction

**Decision**: `EmbeddingProvider` ABC with `SentenceTransformerProvider` as the only v1 implementation

**Rationale**: Mirrors biassemble-core's `LLMProvider` / `GeminiProvider` pattern. Allows swapping to OpenAI embeddings or a fine-tuned model without touching retrieval code. The abstraction boundary is thin — `embed_texts()` and `embed_query()` are the only methods needed.

**Dimension validation**: `provider.dimension` is checked against `settings.embedding_dimension` at startup. Mismatch causes startup crash rather than silent garbage retrieval.

---

## ChunkType Constants vs Enum

**Decision**: String constants (`CHUNK_TYPE_DEFINITION = "semantic_definition"` etc.)

**Rationale**: An enum would require extending `ChunkType` for every new source type (BookSource, PaperSource). Future sources must be able to introduce custom chunk types (`"case_study"`, `"clinical_scenario"`) without modifying the core constants file. Validation happens at the source level, not globally.

---

## Denormalized `full_document` JSONB

**Decision**: Store all chunks for a bias on every row in `full_document` JSONB

**Rationale**: Single-query retrieval — find matching chunk, return full bias content immediately. No second lookup. Storage overhead is negligible (<1 MB for 30 biases × 5 chunks). Consistency enforced by building `full_document` per bias once and attaching the same object to all its chunks.

---

## taxonomy_version Immutability

**Decision**: `taxonomy_version` is a content snapshot identifier, never mutated

**Rationale**: Re-indexing with the same version string creates duplicate rows (old and new text both returned by searcher). Bumping version on every re-index is the only safe approach. Old versions remain until explicitly deleted — no data loss on re-index.
