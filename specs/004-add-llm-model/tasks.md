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

- [ ] T001 Add and pin `llama-cpp-python` (a version with prebuilt CPU wheels) and `huggingface_hub` to `pyproject.toml`; record the fallback note (raw `transformers` if the wheel fails to build) in a comment per research R3.
- [ ] T002 [P] Add `llm_model_repo`, `llm_gguf_file`, `llm_context_tokens`, `llm_max_output_tokens`, `llm_temperature`, `llm_threads`, `llm_log_raw` settings (defaults per data-model.md) to `src/config.py` — do not yet wire them anywhere.

---

## Phase 2: Foundational — VALIDATION GATE (blocks ALL user stories)

**Purpose**: Prove the model detects biases at all before any integration (SC-001).

- [ ] T003 Write `scripts/spike_llm_bias.py` (throwaway): download the GGUF via `huggingface_hub`, build a prompt (system + catalog `bias_id`/`name`/`indicators` + story), greedily generate, print raw output + parsed JSON + wall time. Run on 2–3 known-bias stories (overconfidence, sunk-cost, confirmation) + 1 neutral story. **Measure cold vs warm separately** — load, then run the same story 3× — so later comparisons aren't cold-vs-warm apples-to-oranges; report both the first-call (cold) and steady-state (warm) latency.
- [ ] T004 Record the spike result in `specs/004-add-llm-model/research.md` (append a "Spike result" note): which model rung passed, measured cold + warm ~200-word latency on cpu-basic, and a first read on false positives (did the neutral story stay empty?). Go/no-go. **GATE: if no-go, stop here.**

**Checkpoint**: Model provably names catalog biases within a plausible latency budget. Integration may begin.

---

## Phase 3: User Story 1 — Engine finds biases with a read-once model (Priority: P1) 🎯 MVP

**Goal**: `SELECTION_STRATEGY=llm_union` returns catalog biases for a story (LLM names them, vector runs concurrently), completing within budget.

**Independent Test**: `POST /retrieve-biases` with a ~200-word overconfidence story under `llm_union` → returns overconfidence (± others) as a completed `200`, wall time < 45s on cpu-basic.

- [ ] T005 [P] [US1] Create `src/llm/__init__.py` and `src/llm/generator.py` — `LLMGenerator` wrapping `llama-cpp-python`: load the GGUF once at construction (threads/context/temperature from config), expose `generate(prompt) -> str`. Raise clearly on load failure (FR-007).
- [ ] T006 [P] [US1] Create `src/llm/prompt.py` — `build_prompt(story, catalog)` where `catalog` is **injected from the existing catalog/roster provider (not hardcoded)** so a larger taxonomy needs no change (research R4). Implement parsing as the **explicit staged pipeline** (research R4): `extract_json → validate_schema → validate_catalog → list[BiasCandidate]`, each stage logging its in/out counts; malformed at any stage → `[]`, never raises (FR-007).
- [ ] T007 [US1] Create `src/selection/llm_union.py` — `LLMUnionStrategy` implementing the `SelectionStrategy` Protocol: run `generator` + existing `VectorOnlyStrategy` concurrently via `asyncio.gather` (mirror `nli_union.py`); union-admit (LLM-named OR `vec ≥ vec_gate`); return `(scores, candidates, StrategyMetadata)`. Greedy/deterministic (FR-011).
- [ ] T008 [US1] Wire startup in `src/api/app.py` — add `elif settings.selection_strategy == "llm_union":` branch that loads `LLMGenerator`, logs `llm_model_loaded`, runs a ~200-word warmup and logs `llm_warmup_complete` latency (mirror the NLI warmup), and constructs `LLMUnionStrategy`. **Only model-*load* failure aborts startup** with a clear error (parity with the NLI branch); a **warmup failure is caught and logged as informational, NOT fatal** — a transient warmup hiccup must not prevent boot.
- [ ] T009 [P] [US1] Unit test `tests/test_llm_prompt.py` — `parse_biases` drops non-catalog ids, repairs loose JSON, returns `[]` on garbage without raising.
- [ ] T010 [US1] Integration test `tests/test_llm_union.py` — with a stubbed/tiny generator, `llm_union` returns admitted biases for a known-bias story and an empty list for a neutral one; request succeeds.

**Checkpoint**: US1 independently testable — the engine does LLM-powered bias retrieval end-to-end.

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

- [ ] T019 [P] Run the eval harness against the new strategy: `python -m src.evaluation.evaluate --strategy llm_union` → SC-005 recall gates (pos ≥ 0.85, neg empty ≥ 0.90, adv ≥ 0.333, edge ≥ 0.583) **AND SC-006 precision guard** (new-method false-positive rate ≤ NLI baseline + ~5pp — a generative model can lift recall while inventing biases); record both.
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
