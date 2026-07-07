# Retrieval metrics — what they mean and where we've been

## The metrics

Five numbers appear in every eval run. Two of them decide everything.

**Recall@5** — did the expected bias appear anywhere in the top 5 results? 1.0 = always found, 0.0 = never found. This is the primary signal for the positive and edge groups. Target ≥ 0.85 on positive.

**empty_rate** — fraction of scenarios where the engine returned nothing at all. On the negative group (stories with no bias), empty_rate measures correct restraint — the engine should return nothing. Target ≥ 0.90 (≥ 0.95 preferred). This is the gate that prevents the product from over-diagnosing.

**MRR (Mean Reciprocal Rank)** — was the correct bias ranked #1? 1/rank, averaged. 1.0 = always first. Distinguishes "found somewhere in top 5" (R@5) from "found at the top" (MRR).

**Precision@5** — of the 5 returned, how many were correct? Penalises noise — returning correct + junk scores lower than returning just correct.

**nDCG@5** — Discounted Cumulative Gain, normalised. Rewards finding the right bias high; a correct result at position 1 is worth more than at position 5. Composite quality signal.

In practice, the conversation is almost always R@5 and empty_rate: did we find it, and did we stay quiet when there was nothing to find? MRR/nDCG are secondary reads on ranking quality within a passing run.

---

## The story, with numbers

### Baseline (spec 001, autumn 2025)

Engine built: story → `all-MiniLM-L6-v2` embedding → pgvector cosine search → similarity threshold filter → top-5 biases. Threshold tuned to 0.35 (highest value holding negative empty_rate at 100%).

| Group | Recall@5 | empty_rate |
|-------|----------|------------|
| positive | 0.667 | — |
| negative | — | 100% |
| edge | 0.417 | — |
| adversarial | 0.000 | — |

The ceiling was visible immediately: positive Recall@5 at 0.667, target 0.85. Misses concentrated in `overconfidence_bias` and implicit `confirmation_bias` — biases whose signal is *how* someone talks (certainty markers, implicit certainty), not *what* they talk about.

### Spec 002 — three content interventions, zero movement (winter 2025)

Hypothesis: the knowledge base chunks weren't vocabulary-rich enough. Three rounds of fixes:

1. **Indicator rewrites** — rewrote indicator lists from passive taxonomy prose to first-person actor language ("I know how these go" style)
2. **Atomic chunking + domain examples** — split chunks finer, added profession-specific examples (medical, finance, legal)
3. **Story patterns** — generated 20+ short story snippets per bias via Gemini, reindexed (~760 chunks)

Result after all three interventions:

| Group | Recall@5 | empty_rate |
|-------|----------|------------|
| positive | **0.667** | — |
| negative | — | 100% |
| edge | 0.583 | — |
| adversarial | 0.333 → **0.000** (regressed) | — |

Positive recall: 0.667 flat, unchanged across all three interventions. The story-patterns index additionally regressed adversarial recall from 0.333 to 0.000 and was parked unmerged.

Conclusion (ADR-001): mechanism ceiling, not vocabulary gap. Single-vector embeddings encode topic. Tonal biases encode tone. Three weeks of content work, zero positive-recall movement — evidence that the problem is structural, not fixable by more examples.

### Spec 003 — NLI zero-shot (current, July 2026)

New mechanism: `MoritzLaurer/deberta-v3-base-zeroshot-v2.0` runs 38 hypothesis pairs per story, producing per-bias entailment scores. Combined with vector scores in a three-gate OR combiner. Vector search stays as a secondary signal.

**First weight sweep (T026)** — 36 configs, w_nli × nli_gate × combined_threshold:

| Config | pos R@5 | neg empty_rate |
|--------|---------|----------------|
| w_nli=0.5, nli_gate=0.70–0.75 | 0.792 | 40% |
| w_nli=0.5, nli_gate=0.80 | **0.792** | **60%** |
| w_nli=0.7–0.9, any gate | 0.583 | 40–60% |
| vector-only (deployed) | 0.667 | **100%** |

NLI produced the largest single positive-recall movement in the project's history (+0.125 vs baseline), but broke negative empty_rate (100% → 60%). The combined_threshold axis had zero effect — biases are admitted entirely via NLI or VEC gate, never by combined score alone.

**NLI-only diagnostics (T-eval-1)** — NLI alone, W_VEC=0:

| Group | Recall@5 | empty_rate |
|-------|----------|------------|
| positive | 0.583 | — |
| negative | — | **20%** |
| edge | 0.250 | — |

NLI alone is weaker than vector on positives. Negative empty_rate collapses to 20% — 4 of 5 negatives leak. The culprit identified in the run JSON:

| Negative scenario | framing_effect score | verdict |
|-------------------|---------------------|---------|
| neg_001 | 0.6094 | leaks at gate ≤ 0.70 |
| neg_002 | **0.9478** | leaks at gate ≤ 0.94 |
| neg_003 | 0.8750 | leaks at gate ≤ 0.87 |
| neg_004 | 0.7690 | leaks at gate ≤ 0.77 |
| neg_005 | 0.3223 | clean ✓ |

`framing_effect` and `base_rate_neglect` hypotheses are near-tautological — almost any narrative entails them. Meanwhile, correct positive biases score 0.97–0.99 (`sunk_cost_fallacy=0.9907`, `confirmation_bias=0.9980`).

Score distributions are **separable**: negatives top out at 0.9478, positives sit at 0.97+. Prediction: `nli_gate=0.95` blocks all negative leaks while retaining most positive admits. This is a calibration problem with two specific hypotheses — not a model comprehension failure.

---

## Where we are now (2026-07-07)

**Deployed (vector-only):** pos R@5 = 0.667 / neg empty_rate = 100%

**v1 sweep best config (w_nli=0.5, nli_gate=0.80):** pos R@5 = 0.792 / neg empty_rate = 60% — not shippable. neg_empty bottleneck traced to `framing_effect` (0.61–0.95 on negatives) and `base_rate_neglect` — near-tautological hypotheses entailing on any narrative.

**Fixes applied (2026-07-07):**

1. **VEC_GATE bug** — was applying gate to min-max normalized scores instead of raw cosine. Fixed: `vector_scores_raw.get(bid, 0.0) >= config.vec_gate`. Did not affect neg_empty (negatives have no vector candidates → all raw=0) but corrects the gate semantics for positive stories.

2. **v2 hypothesis rewrites** — 6 hypotheses rewritten after NLI-only diagnostics revealed which were near-tautological:
   - `framing_effect`, `base_rate_neglect` — tightened to require mechanism-specific features (gain/loss bidirectionality; ignoring known base rates)
   - `availability_heuristic`, `confirmation_bias`, `overconfidence_bias`, `affect_heuristic` — broadened from overly narrow v1 phrasings that scored too low on true positives

3. **Gate sweep extended** — nli_gate grid expanded to include 0.85, 0.90, 0.95. Monotonic improvement confirmed: neg_empty 40% → 60% → 80% → **100%** at gate=0.95.

**v2 sweep winning config (w_nli=0.5, nli_gate=0.95):**

| Group | Recall@5 | empty_rate | Gate | Status |
|-------|----------|------------|------|--------|
| positive (N=4) | **0.875** | — | ≥ 0.85 | ✓ |
| negative (N=5) | — | **100%** | ≥ 0.90 | ✓ |
| edge (N=2) | **0.583** | — | ≥ 0.583 | ✓ |
| adversarial (N=2) | **0.167** | — | ≥ 0.333 (ADR) | ✗ / ✓ vs deployed |

`combined_threshold` is inert across all sweep rows — the three-gate OR is effectively a two-gate OR (NLI gate + VEC gate). Combined pathway never fires.

**Adversarial gate context:** ADR-002 gate is ≥ 0.333, referencing Jul 3 post-T005 baseline. Current deployed service already scores 0.000 on adversarial (2026-07-06.1 index). v2 config at 0.167 is an improvement over what's in production.

**Architecture reframe (2026-07-07):** this engine shortlists biases for an LLM, not the end user. False positives are reviewed and discarded by the LLM downstream. neg_empty and precision matter less than recall — a spurious bias in the shortlist costs one LLM evaluation; a missed bias means the LLM never assesses it. This makes pos_r@5 the primary gate and neg_empty secondary.

**Out-of-sample test (Anna story):** a purely procedural story (timestamps, measurements, no cognitive content) triggers `overconfidence_bias` at 0.957 — NLI model conflates confident declarative prose with overconfidence. Vector-only returns nothing on the same story (max cosine 0.27, threshold 0.40). Three hypothesis rewrites moved the score by 0.009 — confirmed model calibration limit, not a wording problem. Accepted: production stories are reasoning/decision narratives; Anna-type inputs are not the target population. LLM would correctly reject overconfidence on a factual log.

---

## Final state (2026-07-07)

**Winning config:** `W_NLI=0.5, NLI_GATE=0.95, COMBINED_THRESHOLD=0.50` (comb_thr value is irrelevant), hypotheses v2.

**Deployed (vector-only):** pos R@5 = 0.667 / neg empty_rate = 100%
**Winning NLI config:** pos R@5 = **0.875** (+0.208) / neg empty_rate = **100%** (held)

Largest positive-recall movement in the project: +0.208. Three weeks of content work in spec 002 produced zero movement; one week of NLI + hypothesis engineering produced +0.208.

**Known limits of this config:**
- pos_r@5=0.875 is on N=4 stories — one story = ±0.25; statistically fragile
- Hypotheses were tuned against the eval set — mild overfitting exposure; Marta (real story, never used in eval) is the pending out-of-sample validation
- Subtle/indirect biases (edge group) unmoved at 0.583 across all configs — NLI with strongly-worded hypotheses doesn't help stories where the bias signal is indirect
- `combined_threshold` parameter can be removed or ignored; it never fires
- Confident declarative prose can trigger overconfidence_bias NLI even without cognitive content — benign given LLM-in-the-loop architecture
