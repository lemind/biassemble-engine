# Research: NLI Zero-Shot Bias Shortlist

All decisions resolved from ADR-002 and pre-spec investigation. No open unknowns.

---

## Model Selection

**Decision**: `MoritzLaurer/deberta-v3-base-zeroshot-v2.0`

**Rationale**: ~700MB on disk, CPU-friendly, consistently outperforms `bart-large-mnli` (~1.6GB) on zero-shot classification benchmarks. Trained specifically for zero-shot entailment usage (zeroshot-v2 model family). Cross-encoder NLI variants offer no batching advantage for this use case (38 fixed hypotheses, not ranking pairs).

**Calibration note**: NLI is mechanism-*closer* than embeddings, not mechanism-*correct*. It still depends on language patterns (wording, phrasing) rather than deep inference. A story saying "John ignored all evidence because he already trusted his first estimate" is easy; a paraphrased version with unusual vocabulary is harder. The eval gates are the sole arbiter — treat this as a falsifiable experiment, not a guaranteed fix.

**Alternatives considered**:
- `bart-large-mnli` — larger, older, lower benchmark scores. Reserved as the one permitted model-swap if T-eval-1 fails and we need to separate "bad model" from "bad hypotheses".
- Cross-encoder NLI variants — same underlying mechanism, no architectural advantage when all 38 hypotheses are evaluated per request.
- Small LLMs via structured output — heavier CPU inference, unneeded generative capacity.

**Commercial note**: `MoritzLaurer/deberta-v3-base-zeroshot-v2.0-c` exists (verified) — the `-c` variant is trained on commercially-licensed data only. Using the non-`-c` version for now (better quality, MIT-licensed model). Swap to `-c` via the `NLI_MODEL` env var if enterprise procurement ever requires it; the eval harness re-validates in ~1h.

**Falsifiability clause**: if T-eval-1 (NLI-only) results are poor, swap to `bart-large-mnli` before concluding the mechanism failed. Model and hypotheses are separate variables — do not iterate hypotheses while holding model constant if initial results are poor.

---

## HuggingFace Transformers Pipeline Usage

**Decision**: `pipeline("zero-shot-classification", model="...", device=-1)` with `multi_label=True` and `hypothesis_template="{}"`.

**Critical settings**:

- `multi_label=True` — default (`False`) softmaxes across all 38 labels so scores compete and sum to 1. A story can have three biases or none; independent per-bias entailment scoring is required.
- `hypothesis_template="{}"` — pipeline default is `"This example is {}."`, which mangles behavioral-sentence hypotheses into grammatical garbage ("This example is The narrator expresses strong certainty..."). Silent quality failure: won't error, will just score everything mushy.

**Install**:
```bash
uv add "transformers[sentencepiece]" torch --index pytorch-cpu
```
`sentencepiece` is required for DeBERTa's tokenizer; omitting it is the classic first error. CPU build of torch avoids ~2GB of unnecessary CUDA libraries.

**Model cache**: Downloads to `~/.cache/huggingface/hub/` on first use (~370–740MB). Override with `HF_HOME` env var. Loads to ~1–1.5GB RAM; load once at startup, never per-request.

**Docker**: Bake model into image at build time:
```dockerfile
RUN python -c "from transformers import pipeline; pipeline('zero-shot-classification', model='MoritzLaurer/deberta-v3-base-zeroshot-v2.0')"
```
Runtime download on cold start will timeout in a free-tier container.

---

## Latency & Concurrency

**Decision**: NLI and vector search run concurrently (asyncio + executor for blocking NLI call). Total latency = max(nli_latency, vec_latency).

**Rationale**: NLI 38-pair batch on CPU: 1–3s. Vector search: ~100–200ms. Sequential = 1.3–3.2s; concurrent = 1–3s. Concurrent is required to stay within a reasonable response window.

**biassemble-core hard constraint**: `RAG_TIMEOUT_MS` defaults to 500ms — incompatible with NLI. Must be raised to 5000ms. This is a named config change in this spec's delivery.

**Sentence-level variant**: 38 × sentence_count pairs. 15-sentence story ≈ 570 inferences ≈ 15–45s CPU. **Offline T-eval-3 only.** Production use would require a two-stage design (cheap filter → NLI on candidates). Do not expose as a production flag.

---

## Score Normalization

**Decision**: NLI entailment probabilities used raw (already 0–1, calibrated by the model). Vector cosine scores min-max normalized over the **full 38-bias vector** (not over a variable-size candidate set).

**Rationale**: Variable-candidate-set normalization is the specific bug to avoid: a bias scored 3rd out of 38 by NLI gets a different normalized value than the same bias scored 3rd out of 5 by vector search if you normalize per candidate set. Forcing both signals to score all 38 (vector emits 0.0 for absent biases) and normalizing over the fixed 38-item vector produces comparable scales.

---

## Union Semantics

**Decision**: Three-gate OR before combination.

```
bias passes if:
  nli(b) ≥ NLI_GATE      (default: 0.80)
  OR vec(b) ≥ VEC_GATE   (default: 0.35, same as current SIMILARITY_THRESHOLD)
  OR combined(b) ≥ COMBINED_THRESHOLD
combined(b) = W_NLI · nli(b) + W_VEC · vec_norm(b)
```

**Rationale**: Weighted-average-then-threshold is intersection wearing a union costume. A perfect NLI hit (1.0 × 0.7 = 0.70) can be killed by a 0.72 combined threshold if vector scored zero. Per-signal gates guarantee that a single strong signal always admits its bias regardless of the other signal's score. Combined score then orders survivors for top-K.

**Starting weights**: `W_NLI=0.7, W_VEC=0.3`. Swept in T-eval-2 over `{0.5, 0.7, 0.9}`.

---

## Hypothesis Authoring

**Decision**: One hypothesis per bias, actor-language, mechanism-shaped, authored from taxonomy Indicators sections only.

**Template examples**:
- Anchoring: "The narrator remains committed to an initial figure or belief and makes only minor adjustments despite significant contradicting evidence."
- Overconfidence: "The narrator expresses strong certainty about their own judgment or predictions and dismisses others' doubts or estimates."

**Authoring rules**:
- Actor-language ("The narrator..."), not analytical observer ("This text exhibits...").
- Tonal biases get tonal hypotheses (certainty markers, pragmatic moves).
- Disambiguate related biases in the wording — each hypothesis names its distinguishing mechanism.
- **Never read eval stories when authoring.** Hypothesis-to-eval leakage fakes the win.

**v2 lever**: Multi-hypothesis per bias (max 2–3, take max score) available for biases that fail eval after v1. Do not pre-optimize 38×3.

**Sanity ritual before writing all 38**: Load model, run Marta story against overconfidence hypothesis + sunk_cost hypothesis + "The narrator is afraid of spiders." Verify: high, high, floor. Ten minutes — confirms install, template, and multi_label simultaneously.

---

## Eval Extensions

**T-eval-1** (NLI-only): `W_VEC=0.0, NLI_GATE=0.80`. Run first. Clean measurement of what recognition alone buys.

**T-eval-2** (union-boost sweep): `W_NLI ∈ {0.5, 0.7, 0.9}` × threshold sweep. `tune_threshold.py` extended to combined scores. Negative empty_rate is the constraint (≥ 0.90); recall is the objective.

**T-eval-3** (sentence-level, offline): On best T-eval-2 config only. Records quality delta and latency. If sentence-level wins on quality, production design is a separate task — not a flag flip.

**Diagnostics**: Every run records per-failure: expected biases, retrieved biases, nli_scores, vector_scores, combined_scores, which signal(s) missed.
