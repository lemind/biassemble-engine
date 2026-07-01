# Tasks: Semantic Bias Retrieval Service

**Branch**: `001-rag-retrieval` | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

**Total tasks**: 21 | **Phases**: 6

Tests are written with their implementation, not in a separate phase. Each task is a logical unit spanning multiple related files.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable — different files, no blocking dependencies
- **[US1–US4]**: User story this task belongs to

---

## Phase 1: Foundation

**Purpose**: Runnable project with correct dependencies, structure, and tooling.

- [x] T001 Bootstrap project: create full directory tree per plan.md (`src/`, `knowledge/`, `scripts/`, `migrations/`, `tests/`, `evaluations/positive/`, `evaluations/negative/`, `evaluations/edge/`, `evaluations/adversarial/`, `evaluations/regression/`, `evaluations/baselines/`, `evaluations/runs/`, `artifacts/`); write `pyproject.toml` with all runtime + dev deps; configure Ruff (line-length 100, select E/F/I) and mypy (strict, Python 3.11) in `pyproject.toml`; write `.env.example` with all required keys and placeholder values (DATABASE_URL, RAG_API_KEY, TAXONOMY_VERSION, etc.); run `uv sync`
- [x] T002 Write core schemas and config: `src/config.py` (Settings with pydantic-settings), `src/schemas/internal.py` (ChunkType constants, FullBiasDocument, CandidateChunk, RetrievedBias, RetrievalMetadata), `src/schemas/request.py` (StoryAnalysis, RetrieveRequest — `request_id: str | None = None`), `src/schemas/response.py` (BiasResult with retrieval_score, RetrieveResponse — `request_id: str`)

**Checkpoint**: `uv run python -c "from src.config import settings; print(settings.taxonomy_version)"` prints today's date.

---

## Phase 2: Bootstrap Deployment

**Purpose**: A live service returning empty biases so biassemble-core can be wired up and exercise the fallback path from day one. Real retrieval replaces the stubs in Phase 4.

- [x] T003 Write `src/providers/base.py` (EmbeddingProvider ABC: `embed_texts()`, `embed_query()`, `model_name`, `dimension`) and `src/providers/sentence_transformer.py` (SentenceTransformerProvider — load once at construction, dimension property returns 384)
- [x] T004 Write stub FastAPI app: `src/api/app.py` (lifespan: load EmbeddingProvider, validate `provider.dimension == settings.embedding_dimension` — crash if mismatch, create asyncpg pool); `src/api/routes/retrieve.py` with stub `POST /retrieve-biases` (Bearer auth check, return `{"biases": [], "retrieved_chunks": 0, taxonomy_version, embedding_model, request_id}`), stub `GET /health` (static response), stub `GET /stats` (static response). Empty biases → biassemble-core falls back to static taxonomy, which is correct.
- [x] T005 Write `Dockerfile` (python:3.11-slim, uv install, non-root user, `CMD uvicorn src.api.app:app`) and `railway.toml` (`healthcheckPath = "/health"`, `healthcheckTimeout = 300`)
- [x] T006 Deploy to HF Spaces (Leminds/biassemble-engine). Verify `GET /health` responds with `model_loaded: true`. Verify `GET /health` responds with `model_loaded: true`.
- [ ] T007 [US1] ⚠️ cross-repo (biassemble-core) Wire biassemble-core: update `assessment.service.ts` to call `POST /retrieve-biases` before building the assessment prompt (500ms timeout, fallback to static taxonomy on any error or empty biases). Confirm biassemble-core works end-to-end using the fallback path.

**Checkpoint**: biassemble-core frontend works. `/health` returns 200 with `model_loaded: true`. biassemble-core falls back to static taxonomy since stub returns `biases: []`.

---

## Phase 3: Knowledge Pipeline (US2)

**Goal**: Developer authors or updates a bias document, runs the indexer, new content is retrievable without code changes.

**Independent Test**: `uv run python scripts/run_indexing.py` → 150+ rows in Supabase, `artifacts/chunks.json` shows all 30 biases with 5 chunks each.

- [x] T008 Write `migrations/001_create_bias_embeddings.sql` (all columns, 5 indexes: btree on bias_id/source/taxonomy_version, UNIQUE dedup on `(taxonomy_version, bias_id, chunk_type, chunk_hash)`, GIN on metadata — **no vector index at v1**, exact scan is accurate and fast at 150 rows; add IVFFlat when rows exceed 300) and apply to Supabase. Write `src/db/connection.py` (asyncpg pool: `get_pool()`, `close_pool()`) and `src/db/queries.py` (SQL constants file, populated incrementally).
- [x] T009 [US2] Write knowledge source abstractions: `src/indexing/sources/base.py` (RawDocument dataclass; KnowledgeSource ABC with `name: str` property, `version: str` property, `load() -> list[RawDocument]` method — `name` populates DB `source` column, `version` surfaces in `/stats`); `src/indexing/sources/taxonomy.py` (TaxonomySource: `name = "taxonomy"`, `version = settings.taxonomy_version`, reads `knowledge/*.md`, parses `## Heading` sections, sets `metadata={"source_file": filename}`)
- [x] T010 [P] [US2] Author all ~30 `knowledge/*.md` bias files — one per bias, every file must have all five sections (`## Definition`, `## Examples`, `## Indicators`, `## False Positives`, `## Related Biases`). False Positives must be substantive, not a placeholder. Write `knowledge/STYLE_GUIDE.md` documenting: tone (factual, no hedging); hard length limits (Definition ≤250 words, Examples ≤350 words, Indicators ≤10 bullets, False Positives ≤10 bullets); domain diversity rule (each Examples section must cover ≥2 domains — finance, medicine, politics, academia, etc.); naming conventions (kebab-case filename = bias_id); mandatory False Positives rule.
- [x] T011 [US2] Write `src/indexing/normalizer.py` — strip excess whitespace, validate mandatory headings (error and halt if `false_positives` missing), normalize heading aliases (`False Positive` → `False Positives`, `Example` → `Examples`), remove duplicate `bias_id`s with warning. Write `tests/test_normalizer.py` — missing false_positives raises, alias normalization works, duplicates are dropped with warning.
- [x] T012 [US2] Write `src/indexing/chunk_builder.py` — build `FullBiasDocument` per `bias_id` once (consistency rule: same object attached to all chunks), produce 5 chunks per bias with `chunk_type` mapping table (raw label → semantic constant → source_section), `chunk_hash = SHA256(bias_id + "|" + chunk_type + "|" + chunk_text + "|" + taxonomy_version)` (pipe-delimited — prevents concatenation collisions), prefix each `chunk_text` with bias name. Print validation stats on completion. Write `tests/test_chunk_builder.py` — each bias produces ≥5 chunks, `bias_id` matches filename stem, `chunk_text` prefixed with bias name, `full_document` has all 6 keys, `chunk_hash` is non-empty SHA256, `false_positives` field present and non-empty.
- [x] T013 [US2] Write `src/indexing/embedder.py` (accepts EmbeddingProvider, batch-embeds chunk texts in `settings.index_batch_size` batches, writes `artifacts/embeddings.json`); `src/indexing/indexer.py` (orchestrates: load → normalize → build chunks → embed → upsert rows via UNIQUE dedup index, writes `artifacts/chunks.json`, prints row count). Write `scripts/run_indexing.py` CLI — loads config, instantiates provider, runs indexer, prints final stats. Run it, verify 150+ rows in Supabase.

**Checkpoint**: `uv run pytest tests/test_normalizer.py tests/test_chunk_builder.py` green. `SELECT COUNT(*) FROM bias_embeddings WHERE taxonomy_version='2026-06-28'` returns ≥150.

> **Seeding note** (2026-07-01): `run_indexing.py` fails mid-operation due to proxy TCP timeout against Supabase. Workaround: generate offline with `scripts/generate_seed_sql.py`, then apply via `supabase db query --linked --file artifacts/seed_embeddings.sql` (HTTPS Management API, bypasses TCP). 190 rows inserted successfully.

---

## Phase 4: Retrieval Engine (US1)

**Goal**: Replace stub endpoint with real semantic retrieval. Marcus/NovaTech story returns the correct biases.

**Independent Test**: `curl -X POST .../retrieve-biases -H "Authorization: Bearer dev-secret-change-me" -d '{"story": "Marcus bought NovaTech at $142..."}' ` → Confirmation Bias, Anchoring Bias, Sunk Cost Fallacy in top 5 with `retrieval_score > 0.45`.

- [x] T014 [US1] Write observability infrastructure: configure structlog in `src/observability.py` (JSON renderer in production, console in dev, log_level from settings); write `TimingContext` helper (context manager measuring wall-clock ms, yielding elapsed); define log event keys as constants. Write `tests/test_observability.py` — structlog events contain expected keys (`request_id`, `event`, `latency_ms`), TimingContext returns non-negative int.
- [x] T015 [US1] Write query builder with tests: `src/retrieval/query_builder.py` (QueryStrategy ABC, RepeatedStoryStrategy — truncate story to 100 words, repeat twice, append analysis fields labeled `Themes:`, `Beliefs:`, `Claims:`, total ≤256 tokens; QUERY_STRATEGY_REGISTRY dict; `get_query_strategy()` resolver); `tests/test_query_builder.py` — story text appears twice, analysis fields appended when present, works without story_analysis, base class is abstract.
- [x] T016 [US1] Write searcher and reranker with tests: `src/retrieval/searcher.py` (cosine SQL `embedding <=> $1::vector`, filter by taxonomy_version, LIMIT search_top_k, deserialize JSONB `full_document` → FullBiasDocument); `src/retrieval/reranker.py` (threshold filter → group by bias_id → max retrieval_score collapse → populate sources list → sort descending → top return_top_k → RetrievedBias[]); `tests/test_reranker.py` — below-threshold chunks dropped, all-below → empty list, sorted descending, no duplicate bias_id, return_top_k respected, sources list populated.
- [x] T017 [US1] Write `src/retrieval/retriever.py` — `request_id = request.request_id or str(uuid4())`; orchestrates query_builder → embed → searcher → reranker using TimingContext per step; enforces `settings.request_timeout_ms = 450` (raises timeout before biassemble-core's 500ms deadline); emits structlog events (`retrieval_started`, `query_embedded`, `vector_search`, `reranked`, `completed`) each carrying `request_id` and step latencies; returns `(list[RetrievedBias], RetrievalMetadata)`. No trace files — structlog is the only observability artifact. Replace stub `POST /retrieve-biases` in `src/api/routes/retrieve.py` with real retriever call. Write `tests/test_retrieve_endpoint.py` — happy path: 200 with biases array, `retrieval_score` on each bias, `retrieved_chunks` count, `request_id` echoed; failure paths: 401 without auth, 401 with wrong token, 503 when DB unavailable, 503 when no rows for taxonomy_version (index_not_found), 200 with `biases: []` for neutral story (not a 503).

**Checkpoint**: `uv run pytest tests/` all green. Marcus/NovaTech curl returns 3 expected biases. Pizza story returns `biases: []`. **NFR check**: send 10 concurrent requests via `asyncio.gather` with `httpx.AsyncClient` — total wall time should be ≈ single request time, not 10× (verifies NFR-003 no serialization). Measure p95 latency under load — must be under 300ms (NFR-001). Deploy to Railway — biassemble-core now receives real RAG results.

---

## Phase 5: Evaluation (US3)

**Goal**: Run evaluation, see per-scenario metrics, save baseline. Re-runs show deltas.

**Independent Test**: `uv run python scripts/run_evaluation.py` prints Recall@5, MRR, nDCG per group and aggregate. Saves `evaluations/runs/run_YYYY_MM_DD.json`. Second run prints deltas against latest baseline.

- [x] T018 [P] [US3] Seed evaluation datasets: `evaluations/positive/*.json` (≥3 stories with `expected_bias_ids` — port Marcus/NovaTech from biassemble-core); `evaluations/negative/*.json` (≥5 no-bias stories with `expected_bias_ids: []`); `evaluations/edge/*.json` (≥2 ambiguous stories for threshold calibration, not counted in primary metrics); `evaluations/adversarial/*.json` (≥3 adversarial stories — politician speech, satire, emotionally manipulative narrative, AI-hallucinated story); `evaluations/regression/` (leave empty for now — add a file here every time a retrieval bug is found and fixed, never delete). Each file: `{"scenario_id", "group", "story", "story_analysis": null, "expected_bias_ids": [...]}`.
- [x] T019 [US3] Write evaluation pipeline: `src/evaluation/evaluate.py` (load datasets by group, run retriever per scenario, compute per-group Recall@K, Precision@K, MRR, nDCG, empty_rate; compare against latest baseline and compute deltas); `scripts/run_evaluation.py` (formatted table output: scenario / expected / retrieved / Recall@5 / MRR / nDCG; saves result to `evaluations/runs/run_YYYY_MM_DD.json`; `--promote` flag copies to `evaluations/baselines/baseline_YYYY-MM-DD.json`). Run it — confirm Recall@5 ≥ 0.85 on positive stories, empty_rate ≥ 90% on negative stories. Run `--promote` to save baseline.

**Checkpoint**: `evaluations/baselines/baseline_YYYY-MM-DD.json` saved. Metrics printed. Change similarity_threshold → re-run → deltas shown in output.

---

## Phase 6: Operations (US4)

**Goal**: Replace stub health/stats responses with real data from the DB.

**Independent Test**: `GET /health` returns `rows_indexed > 0`, `database_connected: true`. `GET /stats` returns `chunk_count_by_type` with entries per type.

- [x] T020 [US4] Replace stub `/health` and `/stats` in `src/api/routes/retrieve.py` with real DB queries: `/health` — `COUNT(*)` and `MAX(indexed_at)` for current taxonomy_version, connectivity probe, `provider_dimension` from loaded model, responds even when DB is down (returns `database_connected: false`); `/stats` — `GROUP BY chunk_type`, `GROUP BY source`, `GROUP BY taxonomy_version` (exposes all versions in DB, not just active), reads `GIT_SHA` env var (null if absent). Add SQL to `src/db/queries.py`. Write `README.md` — setup instructions (`uv sync`, `.env` config, `run_indexing.py`, `run_evaluation.py`), endpoint reference table (method, path, auth, purpose), env vars table, Railway deploy steps. Deploy to Railway — confirm real data in responses.

**Checkpoint**: `/health` shows correct `rows_indexed`. `/stats` shows `chunk_count_by_type` breakdown. Both respond under 50ms. `/health` correctly reports `database_connected: false` when DB is unreachable. **NFR check**: `docker stats` on the running container — memory footprint must stay under 1 GB under normal load (NFR-007).

---

## Phase 7: Remote Evaluation Endpoint (US3)

**Goal**: Run the evaluation pipeline from the deployed service where Supabase is reachable directly (no proxy). Local machine triggers it via HTTPS and saves results.

**Why**: Local asyncpg vector queries hang through the SOCKS proxy (type introspection second round-trip). HF Spaces has direct DB access — run evaluation there, return `EvalRun` JSON to caller.

- [ ] T021 [US3] Add `POST /evaluate` to `src/api/routes/retrieve.py` — auth-gated (Bearer), runs `run_evaluation(provider, pool, eval_dir=Path("evaluations"), ...)` using the app's already-open pool and provider, returns the full `EvalRun` as JSON. Add `GET /evaluate/latest` to fetch the most recent run (reads `evaluations/runs/` at startup or caches). Update `scripts/run_evaluation.py` to call the endpoint via `httpx` when `PSQL_SEARCH=false` (deployed mode), save result to `evaluations/runs/run_YYYY-MM-DD.json`, handle `--promote`. Add endpoint to README endpoint table. Contract: see `specs/001-rag-retrieval/contracts/evaluate.md` (to be created).

**Checkpoint**: `curl -X POST .../evaluate -H "Authorization: Bearer ..."` returns JSON with `group_metrics`, `scenario_results`, `k`. Local script saves the file and prints the same table as today's `run_evaluation.py`.

---

## Dependencies & Execution Order

```
T001 → T002 → T003 → T004 → T005 → T006 → T007   (stub live, core wired)
                                       ↓
                     T008 → T009 → T011 → T012 → T013  (indexing pipeline)
                             ↑
                     T010 [P] (knowledge authoring — parallel with T009 onward)
                                                ↓
                     T014 → T015 → T016 → T017  (retrieval engine live)
                                       ↓
                     T018 [P] + T019  (evaluation baseline)
                                       ↓
                     T020  (real health/stats)
                                       ↓
                     T021  (remote /evaluate endpoint)
```

### Parallel Opportunities

- T010 (knowledge authoring) can run in parallel with T009 and the pipeline code — they touch different files
- T018 (seed datasets) can run in parallel with T015–T016 since it's only JSON files
- T002 schemas and T001 can be sequential since schemas depend on directory tree

### Key Design Notes

- **request_id everywhere**: one name, one concept. `request_id = request.request_id or str(uuid4())`. All structlog events, RetrievalMetadata, and the API response use `request_id`. No dual naming.
- **No trace files**: structlog + Railway logs are the only observability artifacts. Trace files were removed — they're write-once, almost-never-read IO debt.
- **taxonomy_version as date**: `"2026-06-27"` not `"v1"`. Immediately tells you which evaluation baseline corresponds to which index.
- **Stub first**: biassemble-core wired at T007 before any real retrieval exists. Exercises fallback immediately.
- **Tests with code**: every implementation task includes its tests inline.
- **Evaluation runs vs baselines**: `evaluations/runs/` holds every run, `evaluations/baselines/` holds promoted reference points. `--promote` is explicit.
