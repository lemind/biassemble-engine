# biassemble-engine

Standalone Python microservice providing semantic bias retrieval for [Biassemble](https://frontend-topaz-eight-10.vercel.app).

Given a story, returns the most semantically relevant cognitive biases from a structured knowledge base — used as context for the LLM assessment in `biassemble-core`.

**Pure retriever. No LLM calls. No business logic.**

## Stack

- FastAPI + Pydantic v2
- sentence-transformers (`all-MiniLM-L6-v2`)
- pgvector (Supabase)
- asyncpg
- uv
- Railway (Docker)

## Endpoints

- `POST /retrieve-biases` — returns top-K biases for a given story
- `GET /health` — service + DB + model status

## Setup

```bash
uv sync
cp .env.example .env
# fill DATABASE_URL and RAG_API_KEY
python scripts/run_indexing.py
```

## Spec

See [biassemble-rag-spec-v1.md](biassemble-rag-spec-v1.md).
