---
title: Biassemble Engine
emoji: 🧠
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
short_description: Bias retrieval — vector + local-LLM search
pinned: false
---

# biassemble-engine

Bias retrieval microservice. Receives a story from biassemble-core and returns the cognitive biases it likely exhibits. **Two search methods run concurrently and their results are unioned:**

- **Vector search** — embeds the story and searches a pgvector index of the bias catalog. Fast and precise on domains it has indexed; blind on domains it hasn't.
- **LLM search** — a small local model (**Gemma-3-4B-it**, GGUF Q4_K_M, via `llama-cpp-python`, CPU) reads the story against all bias ids and names those that apply. Catches biases vector search misses in unfamiliar domains (space, deep-sea, etc.).

Each returned bias is tagged with which method(s) found it — `source: ["vector"] | ["llm"] | ["vector","llm"]`. The search method is selectable via `SELECTION_STRATEGY`: `vector_only` (pure retriever), `nli_union` (DeBERTa NLI + vector), or `llm_union` (Gemma + vector, the above).

## Stack

- FastAPI + Pydantic v2
- sentence-transformers (`all-MiniLM-L6-v2`) — vector search
- **Gemma-3-4B-it (GGUF Q4_K_M) via llama-cpp-python — LLM search (`llm_union`)**
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

Defaults below are the bare `src/config.py` fallbacks (used for local dev / a non-Space docker run with nothing else set). **The deployed HF Space does not use these** — its actual live values live in [`space-vars.env`](space-vars.env), git-tracked, pushed with `.venv/bin/python scripts/sync_space_vars.py`. HF Space Variables always override the Dockerfile's `ENV` lines, so editing the Space's web UI directly causes silent drift from git — that already happened once (`REQUEST_TIMEOUT_MS` stuck at 60000 in production while everything in git said 120000). Change deployed config in `space-vars.env`, not the web UI.

| Variable | Local default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | Supabase PostgreSQL connection string (Space Secret, not in space-vars.env) |
| `RAG_API_KEY` | — | Shared Bearer secret with biassemble-core (Space Secret) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformer model name |
| `EMBEDDING_DIMENSION` | `384` | Must match model output dimension |
| `TAXONOMY_VERSION` | `2026-06-28` | Active knowledge version; must match seeded rows |
| `SEARCH_TOP_K` | `20` | Candidate chunks retrieved from vector index |
| `RETURN_TOP_K` | `5` | Max biases returned after reranking |
| `SIMILARITY_THRESHOLD` | `0.45` | Minimum cosine similarity to pass reranking |
| `QUERY_STRATEGY` | `repeated_story` | Query construction strategy |
| `RERANK_STRATEGY` | `max` | Score collapse strategy per bias |
| `INDEX_BATCH_SIZE` | `32` | Embedding batch size during indexing |
| `SELECTION_STRATEGY` | `vector_only` | `vector_only` \| `nli_union` \| `llm_union` — deployed Space runs `llm_union` |
| `REQUEST_TIMEOUT_MS` | `450` | Per-request timeout; deployed Space runs `120000` (CPU LLM inference is seconds, not ms — see space-vars.env) |
| `LOG_LEVEL` | `INFO` | structlog minimum level |
| `GIT_SHA` | — | Set at build time; surfaced in `/stats` |

## Scripts

All scripts use `.venv/bin/python`. `uv run` hangs through the local SOCKS proxy — use the venv Python directly.

---

### `scripts/run_indexing.py` — rebuild the vector index

**When**: after any change to `knowledge/*.md` files or after bumping `TAXONOMY_VERSION` in `.env`.

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_indexing.py
```

Loads knowledge files → normalises → chunks → embeds → upserts to Supabase. Skips rows that already exist (same hash). Prints inserted vs skipped counts.

**Fallback (if upsert times out)**: use `generate_seed_sql.py` + Supabase CLI instead (see below).

---

### `scripts/generate_seed_sql.py` — generate SQL seed file (no DB connection)

**When**: `run_indexing.py` fails with TCP timeouts through the SOCKS proxy. Produces a SQL file you apply via the Supabase web console or CLI.

```bash
# Step 1 — generate artifacts/seed_embeddings.sql
HF_HUB_OFFLINE=1 .venv/bin/python scripts/generate_seed_sql.py

# Step 2 — apply via Supabase CLI (uses HTTPS, bypasses TCP proxy)
supabase link --project-ref <project-ref>   # one-time
supabase db query --linked --file artifacts/seed_embeddings.sql
```

---

### `scripts/run_evaluation.py` — evaluate retrieval quality

Runs all eval scenarios and reports Recall@5, Precision@5, MRR, nDCG@5, and empty_rate per story group. Saves a run JSON to `evaluations/runs/`. Use `--promote` to copy to `evaluations/baselines/` (sets the comparison baseline for future runs).

#### Mode comparison

| | Local (`ENGINE_URL=""`) | Remote (`.env` `ENGINE_URL` set) |
|---|---|---|
| Vector search | psql against Supabase directly | HF Space runs it |
| NLI inference | DeBERTa on your CPU | DeBERTa on Space CPU |
| Code under test | Working directory (local edits visible) | Deployed Space SHA |
| Hypothesis file | Local `hypotheses/` | Space's deployed copy |
| When to use | Iterating before push | Post-deploy smoke test |

#### Remote mode — post-deploy smoke test

**When**: after pushing and confirming the Space is running.

```bash
# ENGINE_URL is read from .env automatically
PYTHONUNBUFFERED=1 .venv/bin/python scripts/run_evaluation.py --strategy nli_union --promote
```

Calls `POST /evaluate` on the deployed Space (async job queue), polls for result, saves JSON locally.

#### Local sync mode — iterate before deploy

**When**: developing locally; validates local code and hypothesis changes before push.

```bash
# NLI+vector combined (canonical gate command)
ENGINE_URL="" HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_evaluation.py --strategy nli_union --promote

# Vector-only (default) — baseline measurement
ENGINE_URL="" HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_evaluation.py

# With diagnostics — writes evaluations/diagnostics/diagnostics_YYYY-MM-DD.json
ENGINE_URL="" HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_evaluation.py --diagnostics

# NLI-only — measures DeBERTa signal alone (W_VEC=0); run before sweep
ENGINE_URL="" HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_evaluation.py --strategy nli_only
```

`ENGINE_URL=""` overrides the `.env` value and forces local psql path. `HF_HUB_OFFLINE=1` prevents the `transformers` library from checking HF Hub for model updates — DeBERTa loads from local cache only (no effect on the HF Space).

Note: `--strategy nli_only/nli_union` requires DeBERTa cached locally. First run without `HF_HUB_OFFLINE=1` to download it.

#### Eval metrics

| Metric | What it measures |
|--------|-----------------|
| **Recall@5** | Did the correct bias appear in the top 5? 1.0 = always found. Main success signal. |
| **Precision@5** | Of the 5 returned, how many were correct? Penalises noise. |
| **MRR** | How high was the correct bias ranked? 1.0 = always #1. |
| **empty_rate** | For stories with no bias, did the engine correctly return nothing above threshold? Target: 100% on negative group. |

#### Story groups

| Group | Description |
|-------|-------------|
| **positive** | Story clearly exhibits a known bias — engine should find it. |
| **negative** | No bias present — engine should return nothing (empty_rate signal). |
| **edge** | Bias is subtle or indirect. Harder to retrieve. |
| **adversarial** | Uses bias-domain vocabulary without actually exhibiting the bias. Designed to fool the retriever. |

Targets: Recall@5 ≥ 0.85 on positive; empty_rate ≥ 90% on negative.

---

### `scripts/tune_threshold.py` — find optimal thresholds

#### Similarity threshold sweep (default)

**When**: after reindexing with a new taxonomy version; finds the highest `SIMILARITY_THRESHOLD` where `neg_empty_rate = 100%` without crushing positive Recall@5.

```bash
PSQL_SEARCH=true HF_HUB_OFFLINE=1 .venv/bin/python scripts/tune_threshold.py
```

Sweeps 0.250–0.600 in 0.025 steps. Pick the highest threshold where `neg_empty = 100%` and `pos_recall@5 ≥ baseline`. Set `SIMILARITY_THRESHOLD` in `.env`.

#### NLI weight sweep (`--sweep-weights`, T026)

**When**: after running `--strategy nli_only` eval (T025); finds the best `W_NLI` / `NLI_GATE` / `COMBINED_THRESHOLD` config for the combined NLI+vector strategy.

```bash
# First run — downloads DeBERTa model (~500MB):
PSQL_SEARCH=true .venv/bin/python scripts/tune_threshold.py --sweep-weights

# Subsequent runs — model already cached:
PSQL_SEARCH=true HF_HUB_OFFLINE=1 .venv/bin/python scripts/tune_threshold.py --sweep-weights
```

Fetches vector candidates from DB once per scenario, runs NLI inference once per scenario, then re-applies 36 configs in-memory. Grid: `W_NLI ∈ {0.5, 0.7, 0.9}` × `NLI_GATE ∈ {0.70, 0.75, 0.80}` × `COMBINED_THRESHOLD ∈ {0.50, 0.55, 0.60, 0.65}`.

Pick the row where `neg_empty = 100%` and `pos_r@5` is highest. Set `W_NLI`, `NLI_GATE`, `COMBINED_THRESHOLD` in `.env`.

---

### `scripts/probe_chunk.py` — cosine delta probe

**When**: validating a rewritten knowledge chunk or new example paragraph before committing. Confirms the new text embeds closer to a failing story than the old text.

```bash
.venv/bin/python scripts/probe_chunk.py \
  --story "The evidence is clear: our policies are working." \
  --old  "Confidence intervals that are too narrow relative to actual outcome distributions" \
  --new  "States an outcome as certain or inevitable without acknowledging the possibility of being wrong"
# → old: 0.019 / new: 0.162 / delta: +0.143 IMPROVED
```

Pass condition: `new_score > old_score`. For domain paragraph validation (T005), also verify `new_score > SIMILARITY_THRESHOLD`.

---

### `scripts/generate_story_patterns.py` — generate story pattern snippets (LLM)

**When**: authoring `## Story Patterns` sections in `knowledge/*.md`. Calls Gemini to generate 50 short snippets per bias covering diverse domains and phrasings; appends them to the knowledge file.

```bash
GEMINI_API_KEY=<key> .venv/bin/python scripts/generate_story_patterns.py --bias confirmation_bias
GEMINI_API_KEY=<key> .venv/bin/python scripts/generate_story_patterns.py --bias confirmation_bias --dry-run
```

`--dry-run` prints without writing. Generates 5 batches of 10 snippets; each batch sees previous output to avoid domain repetition.

---

## Evaluation baselines

Baseline files live in `evaluations/baselines/`. The most recent one is used automatically as the comparison target when you run any eval. Run with `--promote` to set a new baseline after a verified improvement.

## Deploy (HF Spaces)

1. Push to the `main` branch (`git push hf HEAD:main`) — HF Spaces builds from the Dockerfile automatically
2. Config lives in [`space-vars.env`](space-vars.env), not the web UI — run `.venv/bin/python scripts/sync_space_vars.py` (add `--dry-run` to preview) to push any changes
3. After deploy: `GET /health` should show `database_connected: true`

## Spec

See [biassemble-rag-spec-v1.md](biassemble-rag-spec-v1.md).
