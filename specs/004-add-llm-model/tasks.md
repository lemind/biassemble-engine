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

- [ ] T011 [US2] Validate `selection_strategy` in `src/config.py` (or at `src/api/app.py` startup) against the allowed set `{vector_only, nli_union, llm_union}`; unknown → raise at startup, never silently default (FR-004).
- [ ] T012 [P] [US2] Integration test `tests/test_strategy_switch.py` — `vector_only` and `nli_union` responses are unchanged by this feature (no `source` field, identical shape); `llm_union` produces a valid result; an unknown flag value raises.

**Checkpoint**: Reversible — one env var flips between all three; existing paths provably untouched.

---

## Phase 5: User Story 3 — Every bias says which method found it (Priority: P3)

**Goal**: Per-bias `source` (vector/llm/both) in response and logs, with separate per-signal scores.

**Independent Test**: submit a story → each returned bias carries a correct `source`; logs show `bias_admitted` per bias; scores reported separately.

- [ ] T013 [P] [US3] Extend `StrategyMetadata` in `src/selection/base.py` with `llm_scores`, `sources` (bias_id→source), `llm_latency_ms`, `truncated_story` (all optional, default `None`).
- [ ] T014 [P] [US3] In `src/schemas/response.py`: add optional `source: Literal["vector","llm","both"] | None = None` to `BiasResult`, AND add the additive top-level `llm_*` optional fields to `RetrieveResponse` (`llm_model`, `llm_latency_ms`, `truncated_story`, `llm_scores`, `vector_scores`) per contract v3 — all absent/None for other strategies (back-compat, FR-005/FR-010).
- [ ] T015 [US3] In `LLMUnionStrategy` (`src/selection/llm_union.py`), compute per-bias `source` (both/llm/vector), populate `StrategyMetadata.sources` + `llm_scores`, and apply the **deterministic total sort** (source rank → llm_conf desc → vec_score desc → bias_id asc) before top-K; keep llm and vector scores separate (no cross-scale blend, research R5).
- [ ] T016 [US3] Thread `source` into the response in `src/api/routes/retrieve.py` (set `BiasResult.source` from metadata) and add top-level `llm_*` fields per contract v3.
- [ ] T017 [US3] Provenance logging: emit `bias_admitted` (bias_id, source, llm_score, vec_score) per admitted bias and one `llm_selection_done` summary (latency, from_llm/from_vector/from_both counts) in `src/selection/llm_union.py` (FR-006, data-model). Gate the **raw model output** log behind `llm_log_raw` (debug only, research R4/point-5).
- [ ] T018 [US3] Integration test `tests/test_llm_source.py` — a bias only-vector→`vector`, only-llm→`llm`, both→`both`; `source` consistent between response and logs.

**Checkpoint**: Full demo + attribution data — "the LLM caught this, vector caught that."

---

## Phase 6: Polish & Deployment

- [ ] T019 [P] Eval + precision baseline. The harness already computes `precision_at_k` (`src/evaluation/evaluate.py:104`) — **no harness change needed**, but SC-006 needs a baseline: **first run `--strategy nli_union` and record its precision/FP as the baseline**, then run `--strategy llm_union` and compare. Gates: SC-005 recall (pos ≥ 0.85, neg empty ≥ 0.90, adv ≥ 0.333, edge ≥ 0.583) AND SC-006 precision guard (llm_union FP rate ≤ recorded nli_union baseline + ~5pp). Record both runs.
- [ ] T020 [P] Latency profile on cpu-basic for realistic (~200-word) stories → requirement: completes within the RAG timeout budget; target p50 < 45s (SC-002). If it misses, drop to the 0.5B rung and re-run.
- [ ] T021 Update `adr/003-generative-llm-bias-selection.md` §11 execution log and status (PROPOSED → ACCEPTED) once gates pass; update `specs/004-add-llm-model/contracts/retrieve-biases-v3.md` if the shape shifted during implementation.
- [ ] T022 Deploy: set `SELECTION_STRATEGY=llm_union` + `LLM_*` variables on the HF Space (same mechanism as existing `NLI_*`/`REQUEST_TIMEOUT_MS`); confirm model loads, a real story completes under the timeout, and `source`-tagged biases appear — end-to-end from `biassemble-core` (which needs zero changes).

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
