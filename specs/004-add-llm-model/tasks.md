---
description: "Task list — Generative LLM Bias Selection (spec 004)"
---

# Tasks: Generative LLM Bias Selection

**Input**: Design documents from `specs/004-add-llm-model/` · Decision: `adr/003-generative-llm-bias-selection.md`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/retrieve-biases-v3.md, quickstart.md

**Tests**: Included (lean) — the project ships a `tests/` suite and the eval harness is the merge arbiter. Unit tests target the fragile bits (JSON parse/repair, source tagging); the eval run (SC-001..006) is the real gate.

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: parallelizable (different files, no incomplete deps)
- **[Story]**: US1/US2/US3 for story-phase tasks only

---

## ⚠️ Phase 2 is a hard GO/NO-GO gate

Per ADR-003 §2 (falsifiability) and spec FR-008/SC-001: **T003 (the spike) blocks every task after it.** If the model can't find biases, stop — escalate the model rung (0.5B↔1.5B↔3B) or reconsider. Do not build integration on a model that doesn't work.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies for local CPU GGUF inference.

- [x] T001 Added `llama-cpp-python==0.3.19` (exact pin — highest version with a prebuilt cp311 `linux_x86_64` CPU wheel on the abetlen index; base image `python:3.11-slim` has no build tools so source builds are impossible) + `huggingface-hub>=0.26.0` to `pyproject.toml`, with a new `[[tool.uv.index]]` `llama-cpp-cpu` (abetlen CPU wheels) + `[tool.uv.sources]` mapping mirroring the existing `pytorch-cpu` pattern, and the `transformers`-fallback note in a comment. Regenerated `uv.lock` (resolved from the CPU index; `uv lock --check` passes so the `--frozen` Docker build stays valid). **Pin still provisional — the spike (T003) is where the wheel actually loads on the Space kernel.**
- [x] T002 [P] Added `llm_model_repo` (default `Qwen/Qwen2.5-1.5B-Instruct-GGUF`), `llm_gguf_file` (`qwen2.5-1.5b-instruct-q4_k_m.gguf` — verified the file exists in the repo), `llm_context_tokens`, `llm_max_output_tokens`, `llm_temperature`, `llm_threads`, `llm_log_raw` to `src/config.py` (defaults per data-model.md), not wired anywhere. Verified config parses with the new fields.

---

## Phase 2: Foundational — VALIDATION GATE (blocks ALL user stories)

**Purpose**: Prove the model detects biases at all before any integration (SC-001).

- [x] T003 Wrote `scripts/spike_llm_bias.py` and ran it end-to-end (glibc, source-built llama-cpp-python, Qwen2.5-1.5B Q4, 38-bias catalog from `knowledge/*.md`). Cold vs warm measured. **Key fix discovered mid-spike: instruct model needs the chat template (`create_chat_completion`), not raw text completion** — raw gave garbage.
- [x] T004 Recorded the "Spike result — GO" section in `research.md`: 3/4 stories exact + 1 plausible, neutral → `[]` (no hallucination); load 0.7s, warm ~12s local (full catalog), cpu-basic gated at T020; **musl-wheel-vs-glibc finding → build from source** (Dockerfile + pyproject updated, re-locked). Go. **GATE PASSED.**

**Checkpoint**: ✅ Model provably names catalog biases (valid in-catalog JSON, no hallucination on neutral). Integration may begin. Carry-forward into US1: use `create_chat_completion`; watch cpu-basic latency (T020) with prompt-prefix caching as the primary lever.

---

## Phase 3: User Story 1 — Engine finds biases with a read-once model (Priority: P1) 🎯 MVP

**Goal**: `SELECTION_STRATEGY=llm_union` returns catalog biases for a story (LLM names them, vector runs concurrently), completing within budget.

**Independent Test**: `POST /retrieve-biases` with a ~200-word overconfidence story under `llm_union` → returns overconfidence (± others) as a completed `200`, wall time < 45s on cpu-basic.

- [x] T005 [P] [US1] Created `src/llm/__init__.py` and `src/llm/generator.py` — `LLMGenerator` loads the GGUF once at construction (via `hf_hub_download` + `llama_cpp.Llama`, threads/context/temperature from config), raises `RuntimeError` clearly on load failure (FR-007). **Deviation from literal task text**: `generate(prompt) -> str` → `generate(system, user) -> str` using `create_chat_completion` — the spike (T003/T004) proved raw completion is broken for this instruct model; documented in the method's docstring.
- [x] T006 [P] [US1] Created `src/llm/prompt.py`. Catalog is **DB-sourced** (`load_catalog(pool, taxonomy_version)`, new `CATALOG_QUERY` in `db/queries.py` reusing the `ROSTER_QUERY` pattern) — loaded once at startup like NLI hypotheses, not hardcoded, not a per-request re-parse of `knowledge/*.md` (research R4). Indicators capped at `_INDICATORS_PER_BIAS = 3` to match the spike's validated config. Staged parse pipeline implemented exactly as specified: `_extract_json → _validate_schema → _validate_catalog → list[BiasCandidate]`, each stage logging in/out counts; any stage failure → `[]`, never raises.
- [x] T007 [US1] Created `src/selection/llm_union.py`. `run_in_executor` dispatch verified correct (mirrors `nli_union.py:46` exactly). Union-admit: LLM-named OR vector-admitted (`vector_scores` pre-filtered by `similarity_threshold` inside `VectorOnlyStrategy`); score = LLM confidence when present else vector score, never blended (research R5). Added defensive try/except around the LLM call in `_run_llm` (not explicit in the task text, but required — an uncaught inference exception would otherwise crash `asyncio.gather` and fail the whole request, violating FR-007's degrade-gracefully requirement).
- [x] T008 [US1] Wired `src/api/app.py`. Only model-load failure aborts startup (raises `RuntimeError`); warmup wrapped in try/except that only logs `llm_warmup_failed` on error, never re-raises — verified this is structurally distinct from the load try/except (two separate try blocks). `pool is None` also aborts startup (`llm_union` cannot build its catalog without the DB — no such guard existed for NLI since hypotheses come from a local YAML file, not the DB).
- [x] T009 [P] [US1] `tests/test_llm_prompt.py` — 7 tests: valid JSON, non-catalog ids dropped, empty array valid, prose-wrapped JSON repaired, garbage → `[]` without raising, missing confidence defaults to 0.5, non-dict array items dropped. All pass.
- [x] T010 [US1] `tests/test_llm_union.py` — 5 tests with a stubbed generator + stubbed vector strategy: known-bias admission, neutral→empty, generator exception degrades to empty (doesn't raise), union-combines with vector scores, non-catalog id dropped. All pass.

**Real end-to-end verification beyond the stubbed tests** (real DB catalog + real downloaded GGUF + real `LLMUnionStrategy`, no mocks): correctly identified `confirmation_bias` for the spike's verbatim story, matching T003/T004 exactly — **confirms the integration itself is correct**. Also surfaced a real, important finding, recorded in research.md: the real DB-sourced catalog (same 3-indicator cap as the spike) runs **48–60s locally**, not the spike's ~12s — a 3–5× gap from indicator text being genuinely more verbose in the DB than the spike's ad-hoc parsing happened to produce (2573 real user-prompt tokens, measured directly; comfortably under `n_ctx=4096`, so not a truncation bug — a genuine prefill-speed cost). **This raises real risk for T020's <45s cpu-basic target** — flagged prominently in research.md so T020 isn't ambushed by a stale 12s estimate. Also observed: the model is prompt-sensitive under greedy decoding (a lightly paraphrased version of the same story returned `[]`, degrading gracefully to vector-only — no crash, FR-007 held) — expected small-model behavior, relevant to T019's eval design, not a code defect.

**Checkpoint**: ✅ US1 independently testable — the engine does LLM-powered bias retrieval end-to-end, verified with real components, not just stubs. Full existing suite (104 tests) + 12 new tests all pass — zero regressions.

---

## Phase 4: User Story 2 — Flag-selectable, existing strategies intact (Priority: P2)

**Goal**: All three strategies selectable by flag; existing two byte-identical; unknown value rejected.

**Independent Test**: run each `SELECTION_STRATEGY` value → valid result; `vector_only`/`nli_union` unchanged; bogus value errors.

- [x] T011 [US2] Added a pydantic `field_validator` on `Settings.selection_strategy` in `src/config.py` against `VALID_SELECTION_STRATEGIES = {vector_only, nli_union, llm_union}`; raises `ValidationError` at `Settings()` construction (import-time startup), never silently falls through to `app.py`'s `else` branch (which previously treated any unrecognized value as `vector_only` — that silent-default gap is what FR-004 closes).
- [x] T012 [P] [US2] `tests/test_strategy_switch.py` — 4 tests via the existing fake-lifespan `TestClient` pattern: `vector_only` and `nli_union` response shape unchanged (asserts exact key set, no `source` field); `llm_union` produces a valid admitted result with a mocked generator; `Settings(selection_strategy="not_a_real_strategy")` raises `ValidationError`. All pass.

**Checkpoint**: Reversible — one env var flips between all three; existing paths provably untouched.

---

## Phase 5: User Story 3 — Every bias says which method found it (Priority: P3)

**Goal**: Per-bias `source` (vector/llm/both) in response and logs, with separate per-signal scores.

**Independent Test**: submit a story → each returned bias carries a correct `source`; logs show `bias_admitted` per bias; scores reported separately.

- [x] T013 [P] [US3] Extended `StrategyMetadata` (`src/selection/base.py`) with `llm_scores`, `sources`, `llm_latency_ms`, `truncated_story` (all optional, default `None`); also extended internal `RetrievalMetadata` (`src/schemas/internal.py`) with the same fields and threaded them through `retriever.py`'s `RetrievalMetadata(...)` construction — not explicit in the task text, but required for the values to actually reach `routes/retrieve.py` (the internal metadata layer this data flows through wasn't otherwise in scope).
- [x] T014 [P] [US3] Added `source: Literal["vector","llm","both"] | None = None` to `BiasResult` and the additive top-level `llm_model`/`llm_latency_ms`/`truncated_story`/`llm_scores`/`vector_scores` to `RetrieveResponse`. **Correction from data-model.md's "absent" framing**: pydantic serializes `None` fields as JSON `null` by default (no `exclude_none` on the route) — contract v3 explicitly allows "absent / null", so this is compliant, but T012's earlier test asserting `"source" not in bias` had to be corrected to `bias["source"] is None` (byte-compat preserved, key-presence claim wasn't accurate).
- [x] T015 [US3] `LLMUnionStrategy` now computes per-bias `source`, applies the deterministic total sort (source rank → llm_conf desc → vec_score desc → bias_id asc) to choose *which* bias_ids survive the `return_top_k` trim, and returns real (never synthetic/blended) llm-or-vector scores for the winners. **Known, documented scope boundary**: final *display order* within that trimmed set still passes through `reranker.py`'s existing single-key numeric sort (shared with vector_only/nli_union, not in this task list) — so a low-llm-confidence "both" bias could display below a high-score "vector"-only bias despite ranking higher by source-rank. Selection correctness (FR-011 determinism, which K survive) holds; exact display-order-under-cross-scale-ties does not fully hold. Flagged in code comments rather than silently claimed as solved or silently expanded into retriever.py/reranker.py (out of scope, shared with other strategies). Also gave `truncated_story` real semantics: added `LLMGenerator.count_tokens`/`truncate_to_tokens` + `prompt.fit_story_to_budget`, since leaving it hardcoded `False` would silently misreport if a story ever did overflow context (not explicit in task text, but required for the field to mean what the contract says).
- [x] T016 [US3] `routes/retrieve.py`: `_to_bias_result` now takes `meta.sources` and sets `BiasResult.source`; top-level `llm_*` fields set only when `meta.selection_strategy == "llm_union"` (kept `None` for vector_only/nli_union so their responses are unaffected).
- [x] T017 [US3] `bias_admitted` (per admitted bias) and `llm_selection_done` (summary: latency, from_llm/from_vector/from_both) logged in `llm_union.py`. Raw model output logged via `log.debug("llm_raw_output", ...)` gated behind `settings.llm_log_raw`.
- [x] T018 [US3] `tests/test_llm_source.py` — 2 tests: source tags correct for a vector-only/llm-only/both scenario in one request (via real HTTP round-trip through the fake-lifespan `TestClient`, proving response `source` is consistent with what the strategy computed since routes/retrieve.py derives it directly from `meta.sources`); llm_scores/vector_scores reported as separate, unblended top-level maps. All pass. **Regression fix**: this phase's `fit_story_to_budget` call broke 3 pre-existing tests that used bare `MagicMock()` generators (missing `context_tokens`/`max_output_tokens`/`count_tokens`) — fixed in `test_llm_union.py` and `test_strategy_switch.py`.

**Checkpoint**: Full demo + attribution data — "the LLM caught this, vector caught that."

---

## Phase 6: Polish & Deployment

- [x] T019 [P] Eval done — but the plan itself changed during execution (model + prompt search), so this became a broad model/format/architecture eval, not just a one-shot baseline. The `--strategy nli_union` baseline already existed (`evaluations/baselines/baseline_2026-07-09.json`); ran `--strategy llm_union` repeatedly across the model swap (Qwen→Gemma), prompt shapes (full-catalog object → ids-only bare list), and narrowing/gate decisions. **Final llm_union (union@5):** pos 0.729, adv 0.333, edge 0.750, neg empty 20%. SC-005: adv/edge pass, positive 0.729 short of 0.85 (deferred to fine-tune), negative empty-rate fails **by design** (no engine neutral-gate — see ADR-003 §11; core does neutral rejection). SC-006 precision guard superseded: the engine is now explicitly a recall-oriented candidate generator, precision is core's job. All recorded in `evaluations/HISTORY.md` "llm_union" section + `run_2026-07-11.json`.
- [~] T020 [P] Latency profiled **locally** (dev machine): ~8–17s warm for realistic stories with the ids-only bare-list format (bare list cut ~3× vs object schema; ~48s→~17s). **cpu-basic profiling still pending — requires the actual deploy (T022).** Mitigation already in place if it misses: `LLM_UNION_TOP_K` down, 0.5B rung, or cpu-upgrade. `REQUEST_TIMEOUT_MS` raised to 60000 (the old 450ms would 503 every LLM request).
- [x] T021 Updated `adr/003-generative-llm-bias-selection.md` — §11 execution log records the model swap, ids-only/no-narrow/no-gate decisions with the novel-domain rationale, `source`-as-array, and top-10; status flipped PROPOSED → ACCEPTED (pending T022 live deploy). Added a coverage note at the vector-search line in §3. Contract v3 shape shifted (`source` scalar → array; added `LLM_UNION_TOP_K`) — reflected in ADR/README; contract doc note pending.
- [~] T022 Deploy **prepared, not yet executed** (user deploys). Dockerfile now bakes the Gemma GGUF into the image (with shared `HF_HOME=/app/.cache/huggingface` so the root-baked model is readable by runtime appuser), comments out the NLI bake, and sets `SELECTION_STRATEGY=llm_union` + `REQUEST_TIMEOUT_MS=60000` as ENV defaults. README updated (vector + LLM search, model named). **Still to do: push, confirm model loads on the Space, a real story completes under the timeout with `source`-tagged biases, and cpu-basic latency is acceptable.** biassemble-core needs zero changes for the request to work (provenance consumption is the separate spec-005 / D015 work).

---

## Dependencies & Execution Order

- **Setup (Phase 1)**: T001 → T002 (T002 [P] with T001 once deps declared).
- **GATE (Phase 2)**: T003 → T004. **Blocks Phases 3–6 entirely.**
- **US1 (Phase 3)**: T005 ‖ T006 → T007 → T008; T009 ‖ (after T006), T010 (after T008). MVP.
- **US2 (Phase 4)**: needs T008 (app wiring). T011 → T012.
- **US3 (Phase 5)**: needs T007 (US1 strategy exists). T013 ‖ T014 → T015 → T016 → T017 → T018.
- **Polish (Phase 6)**: T019 ‖ T020 after US1 (US3 improves them); T021 after gates; T022 last.

### Within `src/api/app.py` and `src/selection/llm_union.py` (same files — sequence)

- app.py: T008 (startup) → T011 (flag validation) may co-locate.
- llm_union.py: T007 (strategy) → T015 (source compute) → T017 (logging).

### Parallel opportunities

```
Phase 1:  T001 → T002 [P]
Phase 3:  T005 [P] ‖ T006 [P] → T007 → T008 ; T009 [P] ; T010
Phase 5:  T013 [P] ‖ T014 [P] → T015 → T016 → T017 → T018
Phase 6:  T019 [P] ‖ T020 [P]
```

---

## Implementation Strategy

### MVP (US1 only)

1. Phase 1 (setup) → Phase 2 (**spike gate — stop if it fails**) → Phase 3 (US1).
2. Validate: `llm_union` returns biases for a real story, completes < 45s on cpu-basic.
3. Ship — the engine now does LLM bias retrieval that actually completes (the thing spec-003 never did).

### Incremental delivery

1. US1 → working LLM retrieval (MVP).
2. US2 → flag safety + provable non-regression of NLI/vector.
3. US3 → source attribution (demo + recall-evaluation data).
4. Polish → eval gates, latency proof, deploy.

## Notes

- T003/T004 are the falsifiability gate (ADR-003 §2) — non-negotiable ordering.
- All API/config/schema changes are additive; `biassemble-core` needs no change (contract v3 §Consumer impact).
- Model is a cartridge (ADR-002 §2): the fine-tune-from-Gemini flywheel (ADR-003 §10) later swaps the GGUF with no code change — out of scope here.
