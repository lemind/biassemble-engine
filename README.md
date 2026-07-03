---
title: Biassemble Engine
emoji: 🧠
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
short_description: Semantic bias retrieval microservice
pinned: false
---

# biassemble-engine

Semantic RAG microservice. Receives a story and structured analysis from biassemble-core, embeds the query, searches a pgvector index of bias knowledge chunks, and returns the top matching biases with retrieval scores.

**Pure retriever. No LLM calls. No business logic.**

## Stack

- FastAPI + Pydantic v2
- sentence-transformers (`all-MiniLM-L6-v2`)
- pgvector (Supabase)
- asyncpg
- uv
- Railway (Docker)

## Setup

```bash
# Install dependencies
uv sync

# Copy and fill in DATABASE_URL and RAG_API_KEY
cp .env.example .env

# Seed the database (first time or after knowledge changes)
ALL_PROXY="" all_proxy="" HF_HUB_OFFLINE=1 uv run python scripts/generate_seed_sql.py
supabase link --project-ref <project-ref>
supabase db query --linked --file artifacts/seed_embeddings.sql

# Run locally
uv run uvicorn src.api.app:app --reload
```

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/retrieve-biases` | Bearer token | Retrieve top biases for a story |
| `GET` | `/health` | None | Liveness + DB connectivity check |
| `GET` | `/stats` | None | Index snapshot (counts, versions, sources) |
| `POST` | `/evaluate` | Bearer token | Run evaluation suite, return EvalRun JSON |

### POST /retrieve-biases

```json
{
  "story": "Marcus bought NovaTech at $142...",
  "story_analysis": {
    "themes": ["investing", "loss aversion"],
    "beliefs": ["stock will recover"],
    "claims": ["sunk cost is recoverable"]
  }
}
```

Returns biases array with `retrieval_score`, `definition`, `examples`, `indicators`, `false_positives`, `related_biases`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | Supabase PostgreSQL connection string |
| `RAG_API_KEY` | — | Shared Bearer secret with biassemble-core |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformer model name |
| `EMBEDDING_DIMENSION` | `384` | Must match model output dimension |
| `TAXONOMY_VERSION` | `2026-06-28` | Active knowledge version; must match seeded rows |
| `SEARCH_TOP_K` | `20` | Candidate chunks retrieved from vector index |
| `RETURN_TOP_K` | `5` | Max biases returned after reranking |
| `SIMILARITY_THRESHOLD` | `0.45` | Minimum cosine similarity to pass reranking |
| `QUERY_STRATEGY` | `repeated_story` | Query construction strategy |
| `RERANK_STRATEGY` | `max` | Score collapse strategy per bias |
| `INDEX_BATCH_SIZE` | `32` | Embedding batch size during indexing |
| `REQUEST_TIMEOUT_MS` | `450` | Per-request timeout (must be < caller's 500ms deadline) |
| `LOG_LEVEL` | `INFO` | structlog minimum level |
| `GIT_SHA` | — | Set at build time; surfaced in `/stats` |

## Evaluation

```bash
# Run via deployed service (recommended — no proxy issues)
# Set ENGINE_URL in .env, then:
.venv/bin/python scripts/run_evaluation.py --promote

# Promote saves result to evaluations/baselines/ locally
```

The script calls `POST /evaluate` on the deployed HF Spaces service, receives the `EvalRun` JSON, prints the metrics table, and saves to `evaluations/runs/`. Add `--promote` to copy to `evaluations/baselines/`.

### Metrics

| Metric | What it measures |
|--------|-----------------|
| **Recall@5** | Did the correct bias appear in the top 5 results? 1.0 = always found, 0.0 = never found. Main success signal. |
| **Precision@5** | Of the 5 results returned, how many were actually correct? Penalises returning noise alongside the right answer. |
| **MRR** (Mean Reciprocal Rank) | How high up was the correct bias ranked? 1.0 = always #1, 0.5 = usually #2. Measures ranking quality, not just presence. |
| **Empty Retrieval Rate** | For stories with no bias, did the engine correctly return nothing above threshold? Should stay at 100%. |

### Story groups

| Group | Description |
|-------|-------------|
| **Positive** | Story clearly exhibits a known bias. Engine should find it. |
| **Negative** | No bias present. Engine should return nothing (empty retrieval rate). |
| **Edge** | Bias is subtle or indirect. Harder to retrieve. |
| **Adversarial** | Story uses the vocabulary of a bias domain (investing, politics) without actually exhibiting one. Designed to fool the retriever. |

Targets: Recall@5 ≥ 0.85 on positive stories; empty_rate ≥ 90% on negative stories.

## Deploy (Railway)

1. Set all env vars in the Railway dashboard
2. Add `GIT_SHA=$RAILWAY_GIT_COMMIT_SHA` as a build-time variable
3. `railway.toml` configures health check path `/health`, timeout 300s
4. After deploy: `GET /health` should show `database_connected: true`, `rows_indexed: 190`

## Re-indexing after knowledge changes

```bash
# Edit knowledge/*.md files, then:
ALL_PROXY="" all_proxy="" HF_HUB_OFFLINE=1 uv run python scripts/generate_seed_sql.py
supabase db query --linked --file artifacts/seed_embeddings.sql

# Verify
uv run python scripts/run_evaluation.py --promote
```

## Spec

See [biassemble-rag-spec-v1.md](biassemble-rag-spec-v1.md).
