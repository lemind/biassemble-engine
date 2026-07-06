# Tasks: NLI Zero-Shot Bias Shortlist

**Input**: Design documents from `specs/003-nli-zero-shot-shortlist/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/retrieve-biases-v2.md

**Path convention**: `src/` at repository root (`biassemble-engine/`)

**Tests**: Not requested. No test tasks generated.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US5 maps to spec.md user stories

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Install dependencies and create module scaffolding that all user stories share.

- [x] T001 Install NLI dependencies: `uv add "transformers[sentencepiece]" torch --index pytorch-cpu` and verify import works
- [x] T002 [P] Create `src/selection/__init__.py`, `src/selection/base.py` — `SelectionStrategy` Protocol: `select(story: str) -> dict[str, float]` returning `{bias_id: score}` for all 38 biases
- [x] T003 [P] Create `src/nli/__init__.py` empty module scaffold

**Checkpoint**: `python -c "from transformers import pipeline"` succeeds. Module directories exist.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config plumbing and `VectorOnlyStrategy` must exist before any NLI work begins — all user stories depend on the strategy injection point in `src/main.py`.

- [x] T004 Add new env vars to `src/config.py`: `SELECTION_STRATEGY` (default `"vector_only"`), `NLI_MODEL` (default `"MoritzLaurer/deberta-v3-base-zeroshot-v2.0"`), `W_NLI` (default `0.7`), `W_VEC` (default `0.3`), `NLI_GATE` (default `0.80`), `VEC_GATE` (default `0.35`), `COMBINED_THRESHOLD` (default `0.60`), `SENTENCE_MODE` (default `False`), `HYPOTHESES_PATH` (default `"hypotheses/v1.yaml"`)
- [x] T005 Create `src/selection/vector_only.py` — `VectorOnlyStrategy`: wraps existing retriever output; maps each bias to its `max_chunk_cosine` (0.0 for absent biases — for combiner use only); `retrieval_score` in `BiasResult` remains the raw cosine — backward-compatible with pre-spec response
- [x] T006 Wire `SelectionStrategy` injection into `src/main.py` lifespan: instantiate `VectorOnlyStrategy` when `SELECTION_STRATEGY="vector_only"`; store on `app.state`; pass into retriever call site in `src/retriever.py`
- [x] T007 Update `src/retriever.py` to delegate candidate admission to `app.state.selection_strategy.select(story)` instead of the inline vector threshold — threshold logic moves into `VectorOnlyStrategy`

**Checkpoint**: Existing eval run against Jul 3 baseline reproduces identical numbers. `SELECTION_STRATEGY=vector_only` response is byte-for-byte identical to pre-spec.

---

## Phase 3: User Story 1 — SelectionStrategy Abstraction (Priority: P1)

**Goal**: Strategy switching works end-to-end; `nli_union` path is wired (even before NLI inference exists) and returns the new metadata fields.

**Independent Test**: `SELECTION_STRATEGY=vector_only` → identical baseline. `SELECTION_STRATEGY=nli_union` with a stub NLI → response includes `selection_strategy`, `nli_scores`, `hypotheses_version` fields.

- [x] T008 [US1] Extend `src/schemas.py` `RetrievalMetadata` with optional fields: `selection_strategy: str | None`, `hypotheses_version: str | None`, `nli_latency_ms: float | None`, `truncated_premise: bool | None`, `nli_scores: dict[str, float] | None`, `vector_scores: dict[str, float] | None`, `combined_scores: dict[str, float] | None`
- [x] T009 [US1] Create `src/selection/nli_union.py` — `NLIUnionStrategy` skeleton: constructor accepts `nli_classifier` and `combiner`; `select()` raises `NotImplementedError` (filled in US2/US4); wire into `src/main.py` lifespan when `SELECTION_STRATEGY="nli_union"`
- [x] T010 [US1] Update retriever response building in `src/retriever.py` to populate new `RetrievalMetadata` fields from strategy output when `SELECTION_STRATEGY=nli_union`

**Checkpoint**: `SELECTION_STRATEGY=vector_only` still passes baseline. `SELECTION_STRATEGY=nli_union` raises `NotImplementedError` cleanly (expected — NLI not yet wired).

---

## Phase 4: User Story 2 — NLI Inference Module (Priority: P1)

**Goal**: Model loads at startup, scores 38 biases for a given story within 3s, runs concurrently with vector search.

**Independent Test**: Server starts, model warm. A POST to `/retrieve-biases` with a short story returns in ≤3s with 38 NLI scores. A >512-token story returns `truncated_premise: true`.

- [x] T011 [US2] Create `src/nli/classifier.py` — `NLIClassifier`: `__init__` loads `pipeline("zero-shot-classification", model=config.NLI_MODEL, device=-1)` with `multi_label=True` and `hypothesis_template="{}"` (hardcoded — not configurable); `classify(story: str, hypotheses: list[tuple[str, str]]) -> NLIResult` truncates story to 512 tokens (log truncation), runs batch of 38, returns `NLIResult(scores={bias_id: entailment_score}, latency_ms=..., truncated_premise=...)`
- [x] T012 [US2] Add `NLIClassifier` load to `src/main.py` lifespan handler: `app.state.nli_classifier = NLIClassifier()` — load only when `SELECTION_STRATEGY="nli_union"`; startup fails loudly if model load fails
- [x] T013 [US2] Implement concurrent execution in `src/selection/nli_union.py` `select()`: `asyncio.gather(run_in_executor(nli_classify), vector_search)` — total latency = max, not sum; profile latency on a 200-word story and log result at startup
- [x] T014 [US2] Add `NLIResult` dataclass to `src/nli/classifier.py`: `scores: dict[str, float]` (entailment only, used for selection), `raw_scores: dict[str, dict[str, float]]` (full entailment/neutral/contradiction triplet per bias — saved for calibration analysis, not used in selection), `latency_ms: float`, `truncated_premise: bool`

**Checkpoint**: Sanity ritual — load model, run `evaluations/positive/marcus_novatech.json` against hand-written overconfidence/sunk_cost/absurd hypotheses. Scores must be: high, high, floor. Do this before writing all 38.

---

## Phase 5: User Story 3 — Hypotheses v1 (Priority: P1)

**Goal**: All 38 hypotheses authored, loaded at startup, producing sensible entailment scores.

**Independent Test**: Server starts, hypotheses loaded without error. `evaluations/positive/marcus_novatech.json` scores `anchoring_bias` and `sunk_cost_fallacy` high; an absurd hypothesis scores near zero.

- [x] T015 [P] [US3] Create `src/nli/hypothesis_loader.py` — `load_hypotheses(path: str) -> list[tuple[str, str]]`: reads YAML, validates exactly 38 entries with valid `bias_id` and `hypothesis` fields, raises `ValueError` at startup if any missing or malformed; returns list of `(bias_id, hypothesis)` tuples
- [x] T016 [P] [US3] Create `hypotheses/v1.yaml` — author all 38 hypotheses following authoring rules from `research.md` §Hypothesis Authoring: actor-language, mechanism-shaped, tonal biases get tonal phrasing, disambiguate related biases. Priority order: `overconfidence_bias`, `confirmation_bias`, `sunk_cost_fallacy`, `hot_hand_fallacy`, `availability_heuristic` first (known-miss biases from spec 002 diagnostics), then remaining 33. One hypothesis per bias.
- [x] T017 [US3] Add hypothesis load to `src/main.py` lifespan handler alongside NLI model: `app.state.hypotheses = load_hypotheses(config.HYPOTHESES_PATH)`; wire into `NLIUnionStrategy` constructor

**Checkpoint**: `GET /health` returns healthy with `hypotheses_version: "v1"` in response. Sanity ritual passes with real hypotheses.

---

## Phase 6: User Story 4 — Union-Boost Combiner (Priority: P2)

**Goal**: Three-gate OR combiner correctly admits biases, normalization is over full 38-bias vector, `admitted` is ordered by combined score.

**Independent Test**: NLI-only hit (nli=0.95, vec=0.0) admitted at `NLI_GATE=0.80`. Vector-only hit (nli=0.3, vec=0.8) admitted at `VEC_GATE=0.35`. Combined-only hit (both signals below gates, combined=0.65) admitted at `COMBINED_THRESHOLD=0.60`. All-reject → empty admitted list.

- [x] T018 [US4] Create `src/nli/combiner.py` — `CombinerOutput` dataclass: `admitted: list[str]` (ordered by `combined_scores[id]` descending), `admitted_by: dict[str, list[str]]` (`{bias_id: ["NLI"|"VECTOR"|"COMBINED"]}` — which gate(s) admitted each bias), `nli_scores: dict[str, float]`, `vector_scores: dict[str, float]`, `combined_scores: dict[str, float]`
- [x] T019 [US4] Implement `combine(nli_scores: dict[str, float], vector_scores_raw: dict[str, float], config) -> CombinerOutput` in `src/nli/combiner.py`: (1) min-max normalize `vector_scores_raw` over the full 38-bias vector; (2) compute `combined(b) = W_NLI * nli(b) + W_VEC * vec_norm(b)` for all 38; (3) admit bias if `nli(b) >= NLI_GATE` OR `vec_norm(b) >= VEC_GATE` OR `combined(b) >= COMBINED_THRESHOLD`; (4) sort admitted by combined score descending; (5) return `CombinerOutput`
- [x] T020 [US4] Wire combiner into `src/selection/nli_union.py` `select()`: after concurrent NLI+vector results, call `combine()`; return `CombinerOutput.combined_scores` for admitted biases (top-K applied downstream in retriever)
- [x] T021 [US4] Update `src/retriever.py` top-K application to operate on `CombinerOutput.admitted` list order when `SELECTION_STRATEGY=nli_union`

**Checkpoint**: End-to-end request with `SELECTION_STRATEGY=nli_union` returns results with `nli_scores`, `vector_scores`, `combined_scores` populated. Three gate paths independently verified by hand on known stories.

---

## Phase 7: User Story 5 — Eval Battery (Priority: P2)

**Goal**: T-eval-1, T-eval-2, T-eval-3 runnable; per-failure diagnostics capture signal breakdown.

**Independent Test**: `python evaluations/run_evaluation.py --strategy nli_only` completes and saves a run JSON. `python scripts/tune_threshold.py --sweep-weights` produces a results table across the w_nli × threshold grid.

- [ ] T022 [P] [US5] Extend `evaluations/run_evaluation.py` with `--strategy` flag accepting `nli_only` (`W_VEC=0.0, W_NLI=1.0`), `vector_only`, `nli_union`; add per-failure diagnostics fields to run JSON: `nli_scores`, `vector_scores`, `combined_scores`, `admitted_by`, `missed_by` (signals that failed to admit each expected bias); snapshot full hypothesis text into run JSON alongside `hypotheses_version` (not just the version string — enables historical reproduction if the file is later overwritten)
- [ ] T023 [P] [US5] Extend `scripts/tune_threshold.py` with `--sweep-weights` flag: iterate `W_NLI ∈ {0.5, 0.7, 0.9}` × `NLI_GATE ∈ {0.70, 0.75, 0.80}` × `COMBINED_THRESHOLD ∈ {0.50, 0.55, 0.60, 0.65}`; report `neg_empty_rate`, `pos_recall@5`, `adv_recall@5`, `edge_recall@5` per config
- [ ] T024 [US5] Add `hypotheses_version` to eval run JSON output in `evaluations/run_evaluation.py`
- [ ] T025 [US5] Run T-eval-1 (`--strategy nli_only`): record results in `evaluations/runs/`; compare to Jul 3 baseline. **Must run before T-eval-2.**
- [ ] T026 [US5] Run T-eval-2 (`--sweep-weights`): identify best config meeting `neg_empty_rate ≥ 0.90`; record winning `W_NLI`, `NLI_GATE`, `COMBINED_THRESHOLD`
- [ ] T027 [US5] Run T-eval-3 (sentence-level, offline only): on best T-eval-2 config, enable `SENTENCE_MODE=true` and run eval; record quality delta and latency for a 15-sentence story; **do not set as production default**
- [ ] T028 [US5] If SC-001 (pos Recall@5 ≥ 0.85) not met after T026: iterate hypothesis v2 for failing biases only (multi-hypothesis max-over-phrasings); re-run T-eval-2; one round max

**Checkpoint**: T-eval-1 results recorded. Best T-eval-2 config identified. If gates pass → Phase 8. If gates fail after T028 → fallback path (biassemble-core ADR required before proceeding).

---

## Phase 8: Deployment & Merge (Priority: P3)

**Purpose**: Core timeout config, Docker bake-in, assessment regression check, ADR closure.

- [ ] T029 Set `RAG_TIMEOUT_MS=5000` in `biassemble-core` Vercel env and local `.env` — required before end-to-end testing (NLI latency is incompatible with default 500ms)
- [x] T030 Add model bake-in to `Dockerfile`: `RUN python -c "from transformers import pipeline; pipeline('zero-shot-classification', model='MoritzLaurer/deberta-v3-base-zeroshot-v2.0')"` — prohibits runtime download at cold start
- [ ] T031 Run `biassemble-core` assessment regression check (`pnpm eval`) against winning engine config with `RAG_TIMEOUT_MS=5000`; verify no FP rate or evidence_grounded_rate regression vs pre-spec baseline
- [ ] T032 Update `adr/002-nli-zero-shot-shortlist.md` status to `CLOSED — MERGED` (or `CLOSED — PARKED`) with final gate numbers and winning config

**Checkpoint**: All SC-001–SC-005 pass. ADR closed.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1 — Abstraction)**: Depends on Phase 2
- **Phase 4 (US2 — NLI Module)**: Depends on Phase 2; can run after T009 (skeleton exists)
- **Phase 5 (US3 — Hypotheses)**: T015 [P] with Phase 4; T016 [P] with Phase 4; T017 depends on T011+T015
- **Phase 6 (US4 — Combiner)**: Depends on Phase 4 + Phase 5 complete
- **Phase 7 (US5 — Eval)**: T022 [P] and T023 [P] depend on Phase 2 only; T025–T028 depend on Phase 6 complete
- **Phase 8 (Deploy)**: Depends on Phase 7 gate pass

### Parallel Opportunities

**Phase 2**: T004 [P] T005 [P] T006 → T007 (sequential within phase)

**Phase 4 + 5 overlap** (after T009 skeleton):
```
T011 (classifier.py)  ← parallel →  T015 (hypothesis_loader.py)
T014 (NLIResult)                     T016 (hypotheses/v1.yaml — author all 38)
T012 (lifespan)
T013 (concurrent exec)
     ↓
T017 (wire hypotheses into lifespan)
```

**Phase 7**: T022 and T023 can run in parallel immediately after Phase 2 (eval harness changes don't require NLI to work).

---

## Implementation Strategy

### MVP (US1 + US2 + US3 — T-eval-1 gate)

1. Phase 1 + Phase 2 → foundation + backward-compat verified
2. Phase 3 → schema + strategy skeleton
3. Phase 4 + Phase 5 (parallel) → NLI inference + hypotheses authored
4. **STOP**: Run T-eval-1 (`--strategy nli_only`). If pos Recall@5 ≥ 0.85 with neg empty_rate ≥ 0.90 → skip Phase 6, go straight to Phase 8. NLI alone wins; set `W_VEC=0.0` in production config.
5. If T-eval-1 insufficient → Phase 6 (combiner) → Phase 7 (sweep)

### Full delivery

Phase 1 → 2 → 3 → (4 ∥ 5) → 6 → 7 → 8

---

## Notes

- T-eval-1 MUST run before T-eval-2 (FR-012 sequencing rule — clean measurement of NLI alone)
- `SENTENCE_MODE=true` (T027) is offline only — never deploy
- `hypothesis_template="{}"` and `multi_label=True` are hardcoded in `classifier.py` — not configurable env vars (silent failure if wrong)
- Hypothesis authoring (T016): write from taxonomy `## Indicators` sections only — never read eval stories while authoring
- If T-eval-2 sweep finds `W_VEC=0.0` optimal, leave vector search wired (b2b path still needs pgvector) but set `W_VEC=0` in the winning config
