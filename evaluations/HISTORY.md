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

### Spec 002 — three content interventions, zero positive movement (winter 2025)

Hypothesis: the knowledge base chunks weren't vocabulary-rich enough. Three rounds of fixes:

1. **Indicator rewrites (T005)** — rewrote indicator lists from passive taxonomy prose to first-person actor language ("I know how these go" style)
2. **Atomic chunking + domain examples** — split chunks finer, added profession-specific examples (medical, finance, legal)
3. **Story patterns** — generated 20+ short story snippets per bias via Gemini, reindexed (~760 chunks)

Post-T005 state (indicators + atomic chunks — this became the spec 003 baseline):

| Group | Recall@5 | empty_rate |
|-------|----------|------------|
| positive | 0.667 | — |
| negative | — | 100% |
| edge | **0.583** | — |
| adversarial | **0.333** | — |

Then the story-patterns branch was applied on top:

| Group | Change |
|-------|--------|
| positive | 0.667 → 0.667 (flat) |
| adversarial | 0.333 → **0.000** (regressed) |

Story-patterns branch parked unmerged. Spec 003 baseline = post-T005 state above.

Positive recall: 0.667 flat across all three interventions. Edge and adversarial moved with content work, but positive — the primary target — did not.

Conclusion (ADR-001): mechanism ceiling, not vocabulary gap. Single-vector embeddings encode topic. Tonal biases encode tone. Three weeks of content work, zero positive-recall movement — evidence that the problem is structural, not fixable by more examples.

### Spec 003 — NLI zero-shot (current, July 2026)

New mechanism: `MoritzLaurer/deberta-v3-base-zeroshot-v2.0` runs 38 hypothesis pairs per story, producing per-bias entailment scores. Combined with vector scores in a three-gate OR combiner. Vector search stays as a secondary signal.

**First weight sweep (T026)** — 36 configs, w_nli × nli_gate × combined_threshold:

| Config | pos R@5 | neg empty_rate | adv R@5 |
|--------|---------|----------------|---------|
| w_nli=0.5, nli_gate=0.70–0.85 | 0.792 | 40–60% | 0.333 |
| w_nli=0.5, nli_gate=0.90 | 0.792 | 80% | 0.167 |
| w_nli=0.5, nli_gate=0.95 | 0.792 | **100%** | 0.000 |
| w_nli=0.7–0.9, any gate | 0.583 | 40–60% | 0.333 |
| vector-only (deployed) | 0.667 | **100%** | 0.000 |

NLI at w_nli=0.5 produced +0.125 on positive recall vs baseline — the largest single movement in the project's history. But no config simultaneously achieved neg_empty=100% AND pos_r@5=0.792: raising the gate to 0.95 fixed negatives but dropped adversarial to 0.000. The combined_threshold axis had zero effect across all 36 rows — biases are admitted entirely via NLI or VEC gate, never by combined score alone.

**NLI-only diagnostics (T-eval-1)** — NLI alone, W_VEC=0:

| Group | Recall@5 | empty_rate |
|-------|----------|------------|
| positive | 0.583 | — |
| negative | — | **20%** |
| edge | 0.250 | — |
| adversarial | **0.333** | — |

NLI alone is weaker than vector on positives and edge, but recovers adversarial to 0.333 (matching the post-T005 baseline). Negative empty_rate collapses to 20% — 4 of 5 negatives leak. The culprit identified in the run JSON:

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

---

## llm_union — generative LLM + vector (2026-07-11, spec 004)

New `SELECTION_STRATEGY=llm_union`: a small local generative model and vector search run concurrently across all 38 biases, results unioned, each bias tagged `source: ["vector"] | ["llm"] | ["vector","llm"]`. Vector-only / nli_union unchanged.

**Model + prompt search (full detail in `specs/004-add-llm-model/research.md`):**
- **Model:** `Qwen2.5-1.5B` → **Gemma-3-4B-it (GGUF Q4_K_M, llama-cpp-python, CPU)**. Qwen-1.5B couldn't emit valid structured output or pick the right bias even from 8 options; Gemma-4B can. Still `cpu-basic`-sized, still LoRA-fine-tunable later.
- **Prompt:** ids-only bare list — the LLM is shown all 38 bias_ids (~330 tokens, no definitions, **not** a vector-narrowed subset) and returns a bare JSON array of ids. Fastest AND best-aligned format tested (~8s vs ~48s for full-catalog object schema). Scales to 200+ (ids stay short); full definitions would not.
- **No narrowing, no neutral-gate.** Both filter the LLM through vector's output, which destroys the LLM's whole value: on novel-domain stories vector returns *nothing*, so narrowing/​gating would blind the LLM exactly where it's needed. "Vector found nothing" = "not a domain vector covers," not "no bias." Neutral rejection is delegated downstream to biassemble-core's assessment LLM.

**llm_union config (Gemma-3-4B, ids-only, union@5) — LIVE SERVER eval, HF cpu-basic Space, 2026-07-11** (via `POST /evaluate`, `run_2026-07-11.json`):

| Group | Recall@5 | Precision@5 | empty_rate | Gate | Status |
|-------|----------|-------------|------------|------|--------|
| positive (N=4) | **0.562** | 0.400 | 0% | ≥ 0.85 | ✗ (fine-tune gap) |
| negative (N=5) | 0.200 | 0.200 | **20%** | ≥ 0.90 | ✗ by design¹ |
| edge (N=2) | **0.750** | 0.400 | 0% | ≥ 0.583 | ✓ |
| adversarial (N=2) | **0.333** | 0.200 | 0% | ≥ 0.333 | ✓ |

¹ No neutral-gate at the engine (would blind novel domains); the engine over-generates candidates and core's assessment LLM makes the final neutral call. Engine `negative` empty-rate is expected to fail standalone.

Local dev runs earlier measured positive up to 0.729; the live-server number (0.562, `pos_004` = 0) is lower — small-model run-to-run variance (greedy but not bit-identical across llama.cpp build/CPU) on N=4 where one story = ±0.25. adversarial/edge/negative match local. Treat these as the honest deployed numbers; positive's gap to 0.85 is the fine-tune target either way.

**Novel-domain generalization** (5 stories far from indexed example text — space mission, deep-sea sub, wine tasting, archaeology, beekeeping): LLM caught **5/5**, vector **2/5**, **3 LLM-only saves** where vector returned nothing. This is the capability that motivated the strategy: vector search is blind on domains it hasn't indexed; the LLM reasons about the pattern regardless of surface vocabulary.

**Latency — LIVE cpu-basic (2026-07-11):** `llm_latency_ms ≈ 2.9s`, full request ~3.6s — vastly under the 60s `REQUEST_TIMEOUT_MS` and the <45s SC-002 target. The ids-only ~330-token prompt makes prefill cheap; cpu-basic is far faster than the earlier local full-catalog fears (48–60s). Bare-list output (no confidence/evidence) cut latency ~3× vs the object schema.

**Ranking note:** in the top-K union trim, `["vector","llm"]` > `["vector"]` > `["llm"]` — vector's confident hits are kept first; the LLM's extra guesses fill remaining slots. Ranking llm-only first silently dropped vector's correct hits on ordinary stories (caught in the confirmation run: positive 0.729 → 0.500). Returns up to `LLM_UNION_TOP_K`=10.

**Known limits:**
- pos_r@5=0.562 on the live server (N=4) — short of the 0.85 gate; deferred to the planned fine-tune (the provenance-logging in biassemble-core D015 is the training-data pump)
- All metrics on 13 scenarios — ±0.25 per positive/edge/adversarial story; directional, not precise
- Neutral hallucination (engine names biases on genuinely neutral stories) is accepted here and pushed to core — do not re-add a vector-based gate to "fix" it

---

## Blind-spot batch — in-field vs out-of-field domain axis (2026-07-13, staged, not yet promoted)

Ran 80 DeepSeek-generated stories (8 batches × 10, half in-field domains — legal/medical/financial/etc — half deliberately out-of-field — mycology/bonsai/paleontology/etc) through the live `llm_union` engine. Full results + per-story table: `evaluations/staging/blind_spot_eval_2026-07-13.json` / `..._SUMMARY.md`. **Staged only** — pending spot-check before promotion into `evaluations/<group>/`.

| Group | out-of-field avg recall | in-field avg recall |
|---|---|---|
| positive | 0.300 | 0.450 |
| adversarial | 0.700 | 0.800 |
| edge | 0.500 | 0.500 (tie — N too small to trust) |
| negative | 100% false-positive both buckets (re-confirms known no-neutral-gate limit, not a new finding) |

Out-of-field recall is lower than in-field in both `positive` and `adversarial` — first direct evidence of a domain-familiarity blind spot, not just an aggregate recall number. `positive`/`edge` (subtle reasoning-error biases) show a bigger in-field/out-of-field gap than `adversarial` (surface manipulation tactics like authority/bandwagon framing, which transfer across domains more easily).

Data-quality flag: one proposed label (`scarcity_bias` in `adv_005`, mycology/adversarial) is not in the 38-id catalog — excluded from scoring, needs a decision (map to an existing id or drop).

## Baseline promoted — 2026-07-14, first llm_union-era baseline

The previous promoted baseline (`baseline_2026-07-09.json`) predated `llm_union` becoming the production default (2026-07-11) — it was captured under an earlier, gated strategy. Building the CI regression gate (`specs/005-ci-metrics-gate`, `adr/004-ci-metrics-gate.md`) surfaced that mismatch directly: comparing a fresh live `llm_union` run against the stale baseline showed `negative`'s `empty_rate` "regressing" `1.000 → 0.200` — not a real regression, just the already-documented no-neutral-gate limitation (see the `llm_union` section above) finally being measured against a baseline that never had that limitation.

Promoted `evaluations/runs/run_2026-07-14.json` → `baseline_2026-07-14.json` (same eval run quoted in the table below) so future comparisons are against `llm_union`'s actual current behavior, not a pre-`llm_union` baseline.

| Group | Recall@5 | Precision@5 | empty_rate |
|---|---|---|---|
| positive (N=4) | 0.729 | 0.500 | 0% |
| negative (N=5) | 0.200 | 0.200 | 20% |
| edge (N=2) | 0.750 | 0.400 | 0% |
| adversarial (N=2) | 0.333 | 0.200 | 0% |

Side effect worth noting: under the new baseline, `negative`'s own tolerance (`1/5=0.200`) sits exactly at its baseline value (`0.200`), so the CI gate's per-`(group, metric)` eligibility rule automatically makes `negative` non-blocking — no hardcoded carve-out needed, it falls out of the same formula every other group uses.
