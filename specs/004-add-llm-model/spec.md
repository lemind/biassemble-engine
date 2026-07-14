# Feature Specification: Generative LLM Bias Selection

**Feature Branch**: `004-add-llm-model`

**Created**: 2026-07-10

**Status**: Draft

**ADR**: `adr/003-generative-llm-bias-selection.md`

**Input**: User description: "Add a flag-selectable selection strategy that uses a small local generative language model to read a story once and name the cognitive biases it exhibits, running alongside the existing vector search. Keep the existing NLI and vector-only strategies intact. Record and log which method surfaced each bias. Validation-first: confirm the model finds biases at all before building integration. Must run on the existing free CPU hardware and complete a realistic story within the retrieval timeout."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — The engine finds biases with a model that reads the story once (Priority: P1) 🎯 MVP

As the **biassemble system**, when a story is submitted for retrieval, the engine identifies the cognitive biases the story exhibits using a language model that reads the whole story **once** and names the biases — instead of the current approach that scores each of ~38 biases separately and times out on real stories.

**Why this priority**: This is the entire point. The current retrieval mechanism fails in production — realistic stories exceed the timeout and return nothing, so downstream assessment always falls back to a generic bias roster. A model that reads once and names biases is both faster and the thing worth demonstrating ("the engine reasons about the biases in your story").

**Independent Test** (this is the validation-first gate — it must pass before any further work): feed 2–3 stories that clearly exhibit known biases; confirm the engine names plausible biases drawn from the catalog for each. Binary go/no-go. If it cannot find biases even roughly, stop and reconsider the model before building anything else.

**Acceptance Scenarios**:

1. **Given** a story that clearly exhibits overconfidence bias, **When** it is submitted for retrieval, **Then** the engine returns overconfidence bias (and optionally other plausible catalog biases) rather than an empty or timed-out result.
2. **Given** a realistic ~200-word story, **When** it is submitted, **Then** the engine returns a completed bias result within the retrieval timeout (median under 45s, per SC-002) — where the previous mechanism returned a timeout error.
3. **Given** a neutral story with no real psychological content, **When** it is submitted, **Then** the engine returns few or no biases (it does not hallucinate biases into every story).

---

### User Story 2 — Operator can choose the selection method without losing the old ones (Priority: P2)

As the **operator/developer**, I can switch the engine's bias-selection method to the new language-model approach via a single configuration flag, and switch back to the existing methods at any time, because all methods remain available.

**Why this priority**: Reversibility is the safety net. The new approach is unproven against the eval gates; keeping the existing NLI and vector-only methods selectable means a one-line revert if it fails, and lets the two approaches be compared on the same eval set.

**Independent Test**: set the selection flag to each of its values in turn (existing vector-only, existing NLI, new language-model) and confirm each produces a valid bias result; confirm an unknown flag value is rejected.

**Acceptance Scenarios**:

1. **Given** the selection flag is set to the new language-model method, **When** a story is submitted, **Then** biases are selected by the language model (plus the concurrent vector signal).
2. **Given** the selection flag is set to either existing method, **When** a story is submitted, **Then** behavior is exactly as before this feature — nothing about the existing methods changed.
3. **Given** the selection flag is set to an unrecognized value, **When** the engine starts or serves a request, **Then** it fails clearly rather than silently guessing.

---

### User Story 3 — Every bias says which method found it (Priority: P3)

As a **developer evaluating and demonstrating the engine**, for each bias the engine returns, I can see which method surfaced it — the vector search, the language model, or both — in the response and in the logs.

**Why this priority**: This is the observability that (a) makes the demo honest and compelling ("the model caught this one that keyword search missed") and (b) provides the raw data to judge whether the language model actually adds recall over vector search alone. It depends on US1/US2 existing but adds distinct value.

**Independent Test**: submit a story, inspect the result and logs, and confirm every returned bias carries a source label of vector, language-model, or both, consistent between response and logs.

**Acceptance Scenarios**:

1. **Given** a bias found only by the vector signal, **When** results are returned, **Then** its source is recorded as vector.
2. **Given** a bias named only by the language model, **When** results are returned, **Then** its source is recorded as language-model.
3. **Given** a bias found by both signals, **When** results are returned, **Then** its source is recorded as both.
4. **Given** any completed request, **When** the logs are inspected, **Then** each admitted bias appears with its source and per-signal scores.

---

### Edge Cases

- **Story exceeds the model's input capacity**: the engine defensively caps input length and still returns a result (never hangs).
- **Model returns malformed or non-catalog output**: the engine tolerates invalid/loosely-formatted model output, keeps only valid catalog biases, and never crashes the request.
- **Model finds nothing**: an empty bias list is a valid result, not an error.
- **Concurrent requests on the constrained hardware**: requests serialize; because retrieval is consumed asynchronously with a graceful fallback downstream, a slow/queued request degrades to "no enrichment," never an error surfaced to an end user.
- **Model file missing/failed to load at startup**: the engine reports the failure clearly rather than serving broken results.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The engine MUST provide a new bias-selection method that uses a local generative language model to read a story once and return the cognitive biases it exhibits, with supporting evidence per bias.
- **FR-002**: The language-model method MUST run the existing vector search concurrently as a complementary signal and combine the two into the returned bias set.
- **FR-003**: The engine MUST keep the existing vector-only and NLI selection methods fully intact and selectable; this feature MUST NOT remove or alter their behavior.
- **FR-004**: The active selection method MUST be chosen by a single configuration flag, with an unrecognized value rejected rather than silently defaulted.
- **FR-005**: For every bias returned, the engine MUST record which signal surfaced it — vector, language-model, or both — and expose that as an additive, optional field on the result (absent for the existing methods, preserving backward compatibility).
- **FR-006**: The engine MUST log, per request, each admitted bias together with its source and its per-signal scores.
- **FR-007**: The language-model method MUST constrain returned biases to the existing catalog and tolerate malformed model output without failing the request. If the model fails to load at startup, the engine MUST report the failure clearly rather than serve broken or empty results as if valid.
- **FR-008**: Bias detection MUST be validated on 2–3 known-bias stories (a go/no-go gate) BEFORE any strategy, combiner, or API integration work proceeds.
- **FR-009**: The engine MUST run this method on the existing free hardware with no change in hardware tier or cost.
- **FR-010**: The response contract and existing configuration MUST change only additively — no breaking changes, and no change required in the downstream consumer to keep working.
- **FR-011**: For the same story, the language-model method MUST produce reproducible results across runs, so the eval gates (SC-005) can be verified reliably.

### Key Entities *(include if feature involves data)*

- **Selection method**: the strategy that turns a story into a scored set of candidate biases. Now one of three: vector-only, NLI, or language-model — chosen by flag.
- **Bias result**: a returned bias, now optionally carrying a **source** (vector / language-model / both) and its per-signal scores, in addition to its existing fields.
- **Bias catalog**: the existing fixed set of cognitive biases (id, name, indicators) the model is constrained to choose from.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** (go/no-go, gates all else): On 2–3 stories with a clearly present bias, the engine names that bias for each — demonstrated before integration work begins.
- **SC-002** (the gate the previous mechanism failed): A realistic (~200-word) story **completes within the downstream retrieval timeout budget** on the existing free hardware — the hard requirement. **Engineering target: median wall time under 45 seconds** (an estimate to beat, not the pass/fail bound). This is the dimension the previous mechanism silently failed by timing out.
- **SC-003**: 100% of returned biases carry a correct source attribution (vector / language-model / both), consistent between the response and the logs.
- **SC-004**: The existing vector-only and NLI methods remain selectable and produce identical results to before this feature (regression check passes).
- **SC-005**: Retrieval quality holds the existing recall gates on the new method — positive Recall@5 ≥ 0.85, negative empty-rate ≥ 0.90, adversarial Recall@5 ≥ 0.333, edge Recall@5 ≥ 0.583.
- **SC-006** (precision guard): The new method's false-positive rate MUST NOT exceed the NLI baseline's by more than ~5 percentage points. A generative model can raise recall while inventing plausible-but-wrong biases; recall gates alone would not catch that, so precision is gated explicitly.
- **SC-007**: No increase in hosting cost or hardware tier versus today.

## Assumptions

- **Model & runtime (candidate, decided by the SC-001 spike — not fixed here)**: a small, openly-licensed, ungated generative instruct model run as a CPU-quantized file (GGUF Q4 via llama.cpp). The starting candidate is Qwen2.5-1.5B-Instruct, but the actual model is chosen by the spike + gates from a ladder (see research.md); the requirement is "a small local generative model," not a specific one. The selection interface treats the model as a swappable cartridge (story → bias_ids + confidence), so both a different rung now and a fine-tuned model later drop into the same slot.
- **Scope of the model's job**: the model is responsible **only** for candidate bias selection (which bias_ids apply, with a rough confidence). It is NOT responsible for explanation or reasoning quality — that lives in the downstream assessment service.
- **Hardware**: the existing free CPU Space (2 shared vCPUs, 16 GB RAM). No GPU, no paid tier.
- **Concurrency**: single-request-at-a-time on this hardware is acceptable, because downstream retrieval is consumed asynchronously with a graceful roster-only fallback — no end user ever blocks on this engine.
- **Downstream consumer unchanged**: the calling service already tolerates the response shape; this feature requires zero changes there.
- **Determinism for evaluation**: the model is run greedily (temperature 0) so eval runs are reproducible.
- **Out of scope** (deferred, see ADR-003 §9): fine-tuning the model, GPU/paid hardware, concurrency scaling, removing the existing methods, and any change to the downstream consumer.
