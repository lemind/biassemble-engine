# Feature Specification: NLI Zero-Shot Bias Shortlist

**Feature Branch**: `003-nli-zero-shot-shortlist`

**Created**: 2026-07-06

**Status**: Draft

**ADR**: [engine ADR-002](../../adr/002-nli-zero-shot-shortlist.md)

## User Scenarios & Testing *(mandatory)*

### User Story 1 — SelectionStrategy Abstraction (Priority: P1)

A `SelectionStrategy` abstraction is introduced parallel to the existing `QueryStrategy`. The NLI classifier is plugged in as the first implementation. Config flags control which strategy is active (`SELECTION_STRATEGY`), the NLI/vector weights (`W_NLI`, `W_VEC`), the per-signal gate thresholds (`NLI_GATE`, `VEC_GATE`), and the sentence-level mode (`SENTENCE_MODE`). All existing vector-only behavior is preserved when `SELECTION_STRATEGY=vector_only`.

**Why this priority**: The abstraction is the durable artifact. ADR-002 explicitly states "design the interface, not the model" — the same slot will later host a fine-tuned model trained on audit labels.

**Independent Test**: With `SELECTION_STRATEGY=vector_only`, the endpoint behaves identically to pre-spec behavior. With `SELECTION_STRATEGY=nli_union`, a request returns results enriched with `nli_scores`, `vector_scores`, and `combined_scores` in the response metadata.

**Acceptance Scenarios**:

1. **Given** `SELECTION_STRATEGY=vector_only`, **When** `/retrieve-biases` is called, **Then** response is identical to pre-spec baseline (no new fields required, backward compat).
2. **Given** `SELECTION_STRATEGY=nli_union`, **When** `/retrieve-biases` is called, **Then** response metadata includes `selection_strategy`, `nli_scores`, `vector_scores`, `combined_scores`, `hypotheses_version`, `nli_latency_ms`, `truncated_premise`.
3. **Given** config flags `W_NLI=1.0 W_VEC=0.0 NLI_GATE=0.80`, **When** `/retrieve-biases` is called, **Then** selection is driven by NLI scores alone (T-eval-1 configuration).

---

### User Story 2 — NLI Inference Module (Priority: P1)

The NLI model (`deberta-v3-base-zeroshot-v2.0`) is loaded once at FastAPI startup via the lifespan handler, not per-request. Given a story and 38 hypotheses, it returns `{bias_id: entailment_score}` for all 38 biases. The model runs concurrently with vector search. Stories longer than 512 tokens are truncated and `truncated_premise: true` is set in the response.

**Why this priority**: Required before hypotheses can be evaluated — no NLI module means no T-eval-1.

**Independent Test**: On startup, model loads without error. A request with a 10-word story returns 38 scores between 0 and 1 within 3s. A request with a >512-token story returns `truncated_premise: true`. With the server killed and restarted, the model reloads from local disk (no re-download).

**Acceptance Scenarios**:

1. **Given** server startup, **When** lifespan handler runs, **Then** NLI model is loaded and warm — no per-request model load.
2. **Given** a story ≤512 tokens, **When** NLI inference runs, **Then** 38 entailment scores are returned, all in [0,1], within 3s CPU time.
3. **Given** a story >512 tokens, **When** NLI inference runs, **Then** story is truncated, inference completes, `truncated_premise: true` in response.
4. **Given** NLI and vector search both configured, **When** a request arrives, **Then** both run concurrently (latency = max, not sum).

---

### User Story 3 — Hypotheses v1 (Priority: P1)

`hypotheses/v1.yaml` contains one actor-language, mechanism-shaped hypothesis per bias (38 total). Hypotheses are authored from taxonomy Indicators sections only — without reading eval stories. The file is versioned; eval runs record `hypotheses_version`.

**Why this priority**: Hypothesis quality is the primary quality lever for this spec. The wrong `hypothesis_template` or poor hypothesis phrasing would give mushy scores without error — an undetected silent failure.

**Independent Test (sanity ritual)**: Load the model, run `evaluations/positive/marcus_novatech.json` (pos_001 — Marcus and the NovaTech shares; expected biases: anchoring, sunk_cost) against three hypotheses — overconfidence, sunk_cost, and one deliberately absurd ("The narrator is afraid of spiders"). Scores must be: high, high, floor. Verifies install, template, and multi_label simultaneously.

**Acceptance Scenarios**:

1. **Given** `hypotheses/v1.yaml` loaded, **When** `evaluations/positive/marcus_novatech.json` is scored, **Then** `anchoring_bias` and `sunk_cost_fallacy` score high; an absurd hypothesis scores near zero.
2. **Given** `hypothesis_template="{}"` set (NOT the default "This example is {}"), **When** a complete behavioral hypothesis sentence is passed, **Then** model receives the sentence as-is without grammatical mangling.
3. **Given** `multi_label=True` set, **When** a story with three biases is scored, **Then** all three can score high independently without competing via softmax.

---

### User Story 4 — Union-Boost Combiner (Priority: P2)

The combiner merges NLI and vector scores. Both signals score the full 38-bias set (vector emits 0.0 for biases absent from top-40). NLI scores used raw (already 0–1); vector cosines min-max normalized over the 38-bias vector. Union semantics: a bias passes selection if `nli(b) ≥ NLI_GATE` OR `vec(b) ≥ VEC_GATE` OR `combined(b) ≥ COMBINED_THRESHOLD`. Survivors are ordered by combined score for top-K.

**Why this priority**: The normalization and union logic must be correct before any eval sweep is meaningful — wrong normalization produces incomparable scales, wrong union produces intersection behavior.

**Independent Test**: A bias with `nli=0.95, vec=0.0` (NLI-only hit) passes selection when `NLI_GATE=0.80`. A bias with `nli=0.3, vec=0.8` (vector-only hit) passes when `VEC_GATE=0.35`. A bias with both signals below their gates but `combined=0.65` passes when `COMBINED_THRESHOLD=0.60`.

**Acceptance Scenarios**:

1. **Given** a bias with high NLI score and zero vector score, **When** combiner runs with `NLI_GATE=0.80`, **Then** bias is admitted regardless of combined score.
2. **Given** a bias with zero NLI score and high vector score, **When** combiner runs with `VEC_GATE=0.35`, **Then** bias is admitted regardless of combined score.
3. **Given** both signals score the full 38-bias set, **When** vector min-max normalization runs, **Then** it divides by 38-bias range, not by variable candidate-set size.
4. **Given** no bias clears any gate, **When** all combined scores fall below `COMBINED_THRESHOLD`, **Then** `biases: []` and roster fallback fires (existing behavior, unchanged).

---

### User Story 5 — Eval Battery (Priority: P2)

T-eval-1 (NLI-only), T-eval-2 (union-boost weight/threshold sweep), and T-eval-3 (sentence-level offline comparison) are run against the Jul 3 baseline. Per-failure diagnostics record which signal missed, raw scores, and rank. Results are saved to `evaluations/runs/`.

**Why this priority**: Gates drive the merge decision. Without the sweep, weight and threshold choices are guesswork.

**Independent Test**: `run_evaluation.py --strategy nli_only` produces a run JSON with group metrics matching T-eval-1 spec. `tune_threshold.py --sweep-weights` produces a results table covering the w_nli ∈ {0.5, 0.7, 0.9} × threshold grid.

**Acceptance Scenarios**:

1. **Given** T-eval-1 run, **When** results are measured, **Then** positive Recall@5 and negative empty_rate are reported against the Jul 3 baseline.
2. **Given** T-eval-2 sweep, **When** all weight/threshold combinations are evaluated, **Then** the best configuration is identified and its gate values recorded.
3. **Given** T-eval-3, **When** sentence-level mode is compared to best T-eval-2 config, **Then** quality difference is measured; latency at 15-sentence story is reported.
4. **Given** any run, **When** a scenario fails, **Then** diagnostic record includes: expected biases, retrieved biases, nli_scores, vector_scores, combined_scores, which signal(s) missed.

---

### Edge Cases

- If `hypothesis_template` is left at the pipeline default (`"This example is {}"`), behavioral-sentence hypotheses produce grammatical garbage — silent quality failure. Must be `"{}"`.
- `multi_label=False` (softmax) is wrong for multi-bias stories — scores compete. Must be `True`.
- Model download happens on first import; subsequent calls load from `~/.cache/huggingface/hub/`. For production/Docker: bake model into image at build time. Never rely on runtime download in a deployed container — cold start will timeout.
- Sentence-level mode (T-eval-3) is offline only. A 15-sentence story produces ~570 NLI pairs (~15–45s CPU). Do not expose as a production flag without a two-stage design.
- `biassemble-core` `RAG_TIMEOUT_MS` must be raised to 5000ms before testing the end-to-end flow. The default 500ms is incompatible with NLI latency. This is a named config change shipped with this spec.
- Hypothesis-to-eval leakage: hypotheses must be authored from taxonomy Indicators sections only, never from reading the eval stories. Leakage would fake the win.
- If T-eval-1 NLI-alone passes all gates, set `W_VEC=0.0` — vector search stays in the pipeline for the b2b path but is excluded from bias selection.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A `SelectionStrategy` abstraction MUST be introduced with at least two implementations: `VectorOnlyStrategy` (current behavior) and `NLIUnionStrategy` (this spec). Active strategy is controlled by `SELECTION_STRATEGY` env var.
- **FR-002**: The NLI model MUST be loaded once at FastAPI startup via the lifespan handler. Per-request model loading is prohibited.
- **FR-003**: NLI inference and vector search MUST execute concurrently per request. Total latency MUST be max(nli_latency, vec_latency), not their sum.
- **FR-004**: `hypotheses/v1.yaml` MUST contain exactly one hypothesis per bias (38 entries), each authored in actor-language behavioral form, using `hypothesis_template="{}"` (not the pipeline default).
- **FR-005**: `multi_label=True` MUST be set. Softmax-style label competition is incorrect for multi-bias stories.
- **FR-006**: NLI scores 38 biases; vector search emits `max_chunk_cosine` per bias with 0.0 for biases absent from top-40. Both signals cover the full 38-bias set.
- **FR-007**: Vector cosine scores MUST be min-max normalized over the full 38-bias vector. NLI entailment probabilities are used raw. No per-candidate-set normalization.
- **FR-008**: Union semantics enforced BEFORE combination: bias passes if `nli(b) ≥ NLI_GATE` OR `vec(b) ≥ VEC_GATE` OR `combined(b) ≥ COMBINED_THRESHOLD`. Combined score orders survivors for top-K.
- **FR-009**: Stories exceeding the model's token limit MUST be truncated. `truncated_premise: true` MUST be set in the response when truncation occurs.
- **FR-010**: `RetrievalMetadata` MUST be extended with: `selection_strategy`, `nli_scores`, `vector_scores`, `combined_scores`, `hypotheses_version`, `nli_latency_ms`, `truncated_premise`. Existing response shape is otherwise unchanged — biassemble-core requires no code changes.
- **FR-011**: `biases: []` discipline unchanged. Empty means both signals ran and nothing cleared any gate. Model-load failure = 5xx, never empty.
- **FR-012**: The eval harness MUST support `--strategy nli_only` (T-eval-1) and a weight/threshold sweep mode (T-eval-2). T-eval-3 sentence-level is offline-only and MUST NOT be available as a production config. **Sequencing rule**: T-eval-1 MUST be run and its results recorded before T-eval-2 begins — NLI-only results are the clean measurement of what recognition alone buys.
- **FR-017**: The NLI model MUST be baked into the Docker image at build time (`RUN python -c "from transformers import pipeline; pipeline('zero-shot-classification', model='MoritzLaurer/deberta-v3-base-zeroshot-v2.0')"` in Dockerfile). Runtime download at container cold start is prohibited — free-tier containers will timeout before the ~700MB download completes.
- **FR-013**: Per-failure diagnostics MUST record: expected biases, retrieved biases, nli_scores, vector_scores, combined_scores, `admitted_by` (which gate admitted each returned bias), and which signal(s) missed for each failing scenario.
- **FR-014**: Every eval run JSON MUST record `hypotheses_version` AND the full hypothesis text for each bias at run time — not just the version string. Reproducing a historical run requires the exact hypothesis wording, not just a version tag that may have been overwritten.
- **FR-015**: The evaluation dataset MUST remain read-only. Hypotheses MUST be authored without reading eval story text.
- **FR-016**: `biassemble-core` `RAG_TIMEOUT_MS` MUST be set to 5000ms for end-to-end testing and production. This config change is part of this spec's delivery.

### Key Entities

- **SelectionStrategy**: Interface with `select(story: str) → dict[str, float]`. Returns `{bias_id: score}` for all 38 biases. Implementations: `VectorOnlyStrategy`, `NLIUnionStrategy`.
- **NLI inference module**: Wraps the HuggingFace `pipeline("zero-shot-classification")`. Loaded once at startup. Handles batching, truncation, and latency measurement.
- **hypotheses/v1.yaml**: Versioned file of 38 `{bias_id, hypothesis}` pairs. The primary quality lever of the spec.
- **Union-boost combiner**: Merges per-strategy scores using per-signal gates + weighted combination. Enforces union semantics before threshold.
- **Eval run**: Execution of all scenarios against a fixed config, producing group metrics + per-failure diagnostics. Saved to `evaluations/runs/`.

## Success Criteria *(mandatory)*

### Measurable Outcomes (merge gates — all must hold at one configuration)

- **SC-001**: positive Recall@5 ≥ 0.85
- **SC-002**: negative empty_rate ≥ 0.90
- **SC-003**: adversarial Recall@5 ≥ 0.333 (no regression vs Jul 3 baseline)
- **SC-004**: edge Recall@5 ≥ 0.583 (no regression vs Jul 3 baseline)
- **SC-005**: assessment-level regression check in biassemble-core passes (run with `RAG_TIMEOUT_MS=5000`)
- **SC-006**: eval dataset untouched; hypotheses authored without reading eval stories
### Failure path

If no configuration passes SC-001–SC-005 after one round of hypothesis v2 iteration (T7), the fallback activates: LLM-shortlist in biassemble-core. Fallback activation requires its own biassemble-core ADR — it is not a config change. If the fallback also fails gates, accept best-achieved config, document the ceiling, close the spec.

## Assumptions

- `deberta-v3-base-zeroshot-v2.0` is the model. One alternative swap (`bart-large-mnli`) is in scope if T-eval-1 results are poor — hypotheses and model are separate variables.
- The existing vector search pipeline (`QueryStrategy`, pgvector, `SIMILARITY_THRESHOLD`) is unchanged. This spec adds on top; it does not replace.
- Eval baseline is Jul 3 post-T005 state: positive 0.667 / negative 1.000 / edge 0.583 / adversarial 0.333, threshold 0.35. The parked story-patterns index is NOT the baseline.
- HuggingFace Space (deployed engine) has CPU-only inference.
- Hard time-box: 7 calendar days from start. Spec closes (merged or documented-and-parked) within that window.
