# engine ADR-002 — Bias Shortlist via Zero-Shot NLI (Spec 003)
### Status: IN PROGRESS · Started: 2026-07-06 · SC-001 ✅ SC-002 ❌ SC-003 ❌ SC-004 ✅ SC-005 ⬜ · Updated: 2026-07-07
### This is a prompt-ADR + spec-kit plan: paste into any AI session running spec 003. The session's job is to execute THIS plan, keep the time-box, and refuse scope beyond §9.

---

You are working with me (solo developer) on `biassemble-engine` spec 003 under this accepted decision. Enforce the plan, the eval gates, and the one-week time-box. If I drift into taxonomy content work, model fine-tuning, or b2b pipeline changes, name the violation and return me to the current task.

## 1. Context (evidence, not opinion)

Spec 002 (taxonomy retrieval improvement) is closed with a measured result: three content interventions (indicator rewrites to actor-language, atomic chunking + domain examples, 20+ story patterns per bias) produced **zero movement on positive Recall@5 (0.667 flat, target 0.85)**. The story-patterns branch additionally regressed adversarial recall 0.333 → 0.000 and is parked unmerged. Diagnostics show misses concentrated in `overconfidence_bias` (3/4 scenarios) and one implicit `confirmation_bias` case — biases whose signal is **tonal/pragmatic** (certainty markers, implicit reasoning moves), not topical. Single-vector embeddings (`all-MiniLM-L6-v2`, story-level query) are topic-dominated and structurally blind to this signal class. Conclusion: mechanism ceiling, not vocabulary gap. The pre-agreed escalation branch (ADR-001 gap-plan conditional tail) is hereby triggered.

## 2. Decision

Add a **zero-shot NLI classifier as the primary bias-selection signal**, with vector search demoted to a secondary signal in a union-boost. Selection becomes recognition-based (entailment against per-bias hypotheses) — mechanism-*closer* than embeddings for tonal biases, not mechanism-correct. NLI still depends on language patterns; the eval gates are the sole arbiter of whether the improvement is real.

- **Model:** `MoritzLaurer/deberta-v3-base-zeroshot-v2.0` (start with base: CPU-friendly, free tier). Rationale: smaller (~700MB) and consistently outperforms `bart-large-mnli` (~1.6GB) on zero-shot classification benchmarks; cross-encoder NLI variants offer no batching advantage here; small LLMs via structured output add heavier/slower CPU inference with unneeded generative capacity. Escalate to `-large` only if base fails eval gates AND profiling shows quality (not speed) is the binding constraint. Multilingual variant out of scope.
- **Falsifiability clause:** if T-eval-1 results are poor, ONE alternative model swap (`bart-large-mnli` as the established baseline) is in scope before concluding the mechanism failed — hypotheses and model are separate variables. Do not repeat spec-002's error of iterating content while never questioning the model.
- **Placement:** inside `biassemble-engine`, behind a new `SelectionStrategy` abstraction parallel to `QueryStrategy`. The engine's "no generative LLM" boundary is preserved — NLI is a discriminative model, local inference, no API calls.
- **Interface is permanent, model is a cartridge:** the same `SelectionStrategy` slot later hosts (a) a fine-tuned small model trained on audit-business override labels once a few hundred story→bias pairs exist (the moat dataset's second use), or (b) an LLM-shortlist in core if NLI fails gates this week. Design the interface, not the model, as the durable artifact.

## 3. Architecture

```
story
  ├─► SelectionStrategy: NLI zero-shot ──► {bias_id: entailment_score} × 38
  │     (38 hypothesis pairs, batched; concurrent with vector search)
  └─► QueryStrategy: vector search ─────► {bias_id: max_chunk_cosine} × 38
                    │                      (0.0 for biases absent from top-40)
            UNION-BOOST COMBINER
  Score normalization: NLI entailment probabilities used raw (already 0–1);
  vector cosines min-max normalized over the full 38-bias vector.
  Both signals score the full 38-bias set — no per-candidate-set min-max
  (set-size-dependent scaling is the bug; forcing both to 38 dissolves it).

  Union semantics enforced BEFORE combination:
    bias passes if nli(b) ≥ nli_gate (start 0.80)
               OR vec(b) ≥ vec_gate (current 0.35)
               OR combined(b) ≥ combined_threshold
  combined(b) = w_nli · nli(b) + w_vec · vec_norm(b)
  (start w_nli=0.7 / w_vec=0.3; sweep in T6)
  Combined score orders survivors for top-K; per-signal gates guarantee
  a single strong signal always admits its bias regardless of the other.
                    │
            top-K (existing gate)
                    │
            fetch full_document by bias_id (existing)
                    │
            response (existing schema + new fields, §6)
```

Vector search is NOT removed: (a) union robustness — NLI is closed-world over hypothesis phrasings, vector search catches what a badly-phrased hypothesis misses; (b) eval continuity — the baseline signal stays measurable; (c) the pgvector infrastructure serves the b2b corpus-retrieval path regardless (product ADR-002, untouched here).

## 4. Hypothesis authoring (the new prompt-engineering surface — most of the quality lives here)

One hypothesis per bias in a versioned file `hypotheses/v1.yaml`: `{bias_id, hypothesis, version}`.

Authoring rules (derived from spec-002 lessons — same principles, new surface):
- **Actor-language, mechanism-shaped:** "The narrator remains committed to an initial figure or belief and makes only minor adjustments despite significant contradicting evidence" — not "This text exhibits anchoring bias."
- **Tonal biases get tonal hypotheses:** overconfidence = "The narrator expresses strong certainty about their own judgment or predictions and dismisses others' doubts or estimates" — targeting certainty pragmatics, the exact signal embeddings missed.
- **Disambiguate related biases in the wording** (confirmation vs cherry-picking vs anchoring): each hypothesis names its distinguishing mechanism, mirroring the taxonomy's Related Biases sections.
- One hypothesis per bias in v1. Multi-hypothesis-per-bias (max over 2–3 phrasings) is a v2 lever ONLY for biases that fail eval — do not pre-optimize 38×3.
- Hypotheses file is versioned like the taxonomy: eval runs record `hypotheses_version`.

## 5. NLI mechanics

- Input pair per bias: premise = story (NLI models handle ~512 tokens; truncate at model limit, log truncation), hypothesis = per-bias text. 38 pairs, batched inference (single forward pass batch of 38 fits CPU memory at base size).
- Score = P(entailment) from the entailment/neutral/contradiction head (zeroshot-v2 models are trained for exactly this usage).
- Latency budget: ≤ 3s CPU per story for the full 38-batch at base size. NLI and vector search execute **concurrently** — latency is max(nli, vec), not sum. Profile in T2; if exceeded, batch-size tuning and ONNX/quantization are in scope, model upsizing is not.
- **HARD CONSTRAINT — biassemble-core timeout:** `RAG_TIMEOUT_MS` defaults to 500ms, incompatible with NLI latency. Both parts required: (a) concurrent execution above keeps total latency ≤ 3s; (b) core's timeout must be raised to 5000ms for this call — this is a named biassemble-core config change shipped with this spec, and the assessment-level regression check (T8) must run against the raised timeout.
- **Sentence-level variant (flagged, offline eval only):** premise = each story sentence, score(b) = max over sentences. Rationale: isolates tonal markers from topic dominance. Order-of-magnitude warning: sentence-level = 38 × sentence-count pairs (a 15-sentence story ≈ 570 inferences, ~15–45s CPU) — acceptable only for offline T-eval-3 comparison, not production. If it wins on quality, production use requires a two-stage design (cheap sentence filter → NLI on candidates) as a separate task, not a flag flip.

## 6. API & schema changes (additive only)

- `RetrievalMetadata` gains: `selection_strategy`, `nli_scores` (per returned bias), `vector_scores`, `combined_scores`, `hypotheses_version`, `nli_latency_ms`, `truncated_premise: bool`.
- Response shape to core unchanged otherwise (full documents + scores) — biassemble-core requires no code changes for this spec beyond the timeout config. Assessment-level regression check (T8) still mandatory before merge.
- `biases: []` discipline unchanged: empty means "both signals ran, nothing above threshold"; model-load failure = 5xx, never empty.

## 7. Eval plan (the gates that decide merge — same iron rules)

Baseline for all comparisons: Jul 3 post-T005 state (positive 0.667, negative 1.000, edge 0.583, adversarial 0.333) at its taxonomy version. The parked story-patterns index is NOT the baseline.

- **T-eval-1, NLI-only:** SelectionStrategy alone (w_vec=0). Answers "what does recognition buy" cleanly.
- **T-eval-2, union-boost sweep:** w_nli ∈ {0.5, 0.7, 0.9} × nli_gate × combined_threshold sweep. Negative-group empty_rate is the constraint (≥ 0.90), recall the objective.
- **T-eval-3, sentence-level flag** on the best T-eval-2 config (offline only — see §5 latency note).
- **Diagnostics on every run** (per-failure: which signal missed, scores, rank).

**Merge gates (all must hold at one configuration):**
- positive Recall@5 ≥ 0.85
- negative empty_rate ≥ 0.90
- adversarial Recall@5 ≥ 0.333 (no regression vs baseline; improvement expected)
- edge Recall@5 ≥ 0.583 (no regression)
- assessment-level regression check in core: pass (run against RAG_TIMEOUT_MS=5000)
- eval dataset untouched (read-only, as always); hypotheses authored without reading eval stories' text (author from taxonomy sections only — hypothesis-to-eval leakage would fake the win)

**Failure protocol:** if no configuration passes after hypothesis iteration on failing biases (one v2 round max), this ADR's fallback activates. Fallback activation is not a config change: moving selection out of the engine violates the current service boundary and requires a biassemble-core ADR. Writing that ADR is the first task of the fallback path, not an afterthought. If the fallback also fails gates, accept best-achieved config, document the ceiling, close the spec — the b2b pipeline does not wait on this number.

## 8. Task list (spec-kit format)

- **T1** SelectionStrategy abstraction + config plumbing (flags: strategy, weights, nli_gate, vec_gate, sentence_mode) — 0.5d
- **T2** NLI inference module: model load, batching, concurrent execution with vector search, latency profiling, truncation logging — 0.5d
- **T3** hypotheses/v1.yaml: author all 38 (start from Indicators sections; extra care on the 5 known-miss scenarios' biases and their Related-Biases neighbors) — 1d
- **T4** union-boost combiner + score normalization (NLI raw; vector min-max over 38; per-signal gates before combination) — 0.5d
- **T5** metadata/schema additions + structlog fields — 0.25d
- **T6** eval battery T-eval-1..3 + threshold/weight/gate sweep + diagnostics review — 1d
- **T7** hypothesis v2 iteration on failing biases only (if gates unmet) + re-eval — 0.5d
- **T8** core assessment regression check (RAG_TIMEOUT_MS=5000) + merge/close decision + ADR status update — 0.25d

Total ≈ 4.5 focused days. **Hard time-box: spec closes (merged or documented-and-parked) within 7 calendar days of start.**

## 9. Out of scope (refuse these in-session)

Fine-tuning any model (blocked until audit labels exist — revisit when ~300+ labeled pairs accumulated) · taxonomy content edits (spec 002 is closed; story-patterns branch stays parked) · multi-hypothesis for all biases preemptively · reranker/cross-encoder · b2b corpus retrieval (product ADR-002) · replacing pgvector · touching the eval dataset · Gemini-shortlist BEFORE the NLI fails gates (it's the fallback, not a parallel track).

## 10. Consequences

- **Positive:** mechanism-appropriate selection for tonal biases; free/local/CPU; permanent cartridge interface enabling the future self-trained model; vector infra retained for b2b; the retrieval saga gets a hard ending this week.
- **Negative/accepted:** +1 model in the engine image (~700MB base) and +1–3s latency per story (mitigated by concurrent execution); a new versioned artifact to maintain (hypotheses); NLI calibration is unstudied on this domain — mitigated by the eval gates being the sole arbiter.
- **After this spec, regardless of outcome:** run the Marta golden story through the merged config and verify anchoring appears in the retrieved/selected biases (closing a known miss from the product-line master plan), then build the b2b extract/verify golden sets — the audit pipeline this engine ultimately serves.

---

## 11. Execution log

**State as of 2026-07-07** — `nli_union`, `deberta-v3-base-zeroshot-v2.0`, `hypotheses/v1.yaml`, best sweep config.

| Gate | Target | Actual | |
|---|---|---|---|
| SC-001 positive Recall@5 | ≥ 0.85 | **0.875** | ✅ PASS (+0.208 vs vector-only baseline 0.667) |
| SC-002 negative empty_rate | ≥ 0.90 | **0.600** | ❌ FAIL (`overconfidence_bias` fires on neg_002/neg_003) |
| SC-003 adversarial Recall@5 | ≥ 0.333 | **0.000** | ❌ FAIL (regressed vs baseline 0.333 — NLI reads surface framing literally) |
| SC-004 edge Recall@5 | ≥ 0.583 | **0.583** | ✅ PASS (flat vs baseline) |
| SC-005 core regression | pass | ⬜ | pending Phase 8 |

**Bugs found and fixed during eval battery:**

- **4→3 bias drop (T033):** NLI-only admitted biases with no vector candidate chunk were silently dropped by the reranker's candidate filter. Fix: fetch one `semantic_definition` chunk per missing bias from DB and hydrate with the combined score before reranking. Deployed; confirmed live by `nli_only_admits_hydrated` log event on HF Space (adm_ids=["in_group_bias"] on pos_002).
- **Remote eval timeout (T034):** HF Space proxy hard-kills HTTP connections at ~90 s regardless of heartbeats or streaming headers. Fix: replaced synchronous/streaming `/evaluate` with async job queue — `POST /evaluate` returns 202 + `job_id` immediately; `GET /evaluate/{job_id}` polls with 5-retry + 120 s timeout. `scripts/run_evaluation.py` updated for polling client.

**Falsifiability clause update (§2):** §2 names `bart-large-mnli` as the one alternative model swap if base DeBERTa fails gates. Updated candidate: `cross-encoder/nli-MiniLM2-L6-H768` — ~4× faster on CPU (smaller model), may generalise differently on adversarial stories. If one hypothesis-v2 iteration (T035/T036) does not close SC-002/SC-003, T037 compares MiniLM2-L6-H768 vs current DeBERTa in place of bart-large-mnli.

**Remaining work:** T035 (hypothesis v2 for `overconfidence_bias`, SC-002), T036 (adversarial analysis for confirmation_bias / framing_effect / affect_heuristic, SC-003), T037 conditional model swap, T038 re-eval → then Phase 8 (T029/T031/T032 → close).
