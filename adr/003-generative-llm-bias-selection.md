# engine ADR-003 — Generative LLM Bias Selection (Spec 004)

### Status: PROPOSED · Started: 2026-07-10 · Supersedes the "no generative LLM in engine" boundary of ADR-002 §2
### This is a prompt-ADR + spec-kit plan: paste into any AI session running spec 004. The session's job is to execute THIS plan, keep the validation-first gate, and refuse scope beyond §9.

---

You are working with me (solo, unemployed, pet project — free tier only) on `biassemble-engine` spec 004 under this accepted decision. Enforce the plan, the eval gates, and the free-hardware constraint. If I drift into fine-tuning, GPU, concurrency scaling, or biassemble-core changes, name the violation and return me to the current task.

## 1. Context (evidence, not opinion)

Spec 003 (zero-shot NLI, ADR-002) passes its eval gates but is **unusable in production on the free `cpu-basic` tier (2 shared vCPUs)**. Measured directly against the live HF Space on 2026-07-10, varying only story length against the same 82-hypothesis batch:

| Story length | HTTP | Wall time |
|---|---|---|
| 9 words | 200 | **67.8s** |
| 54 words | 200 | **71.4s** |
| 126 words | 200 | **133.9s** |
| 234 words (realistic) | **timeout** | **>200s → 503** |

Root cause is mechanism-shape, not tuning: **zero-shot NLI is O(N_labels) forward passes** — 82 hypotheses (≈38 biases × phrasings), each story duplicated as the premise, one DeBERTa-v3-base pass per pair. `padding=True` pads the batch to the longest pair, so a long story pushes the sequence to ~512 tokens and O(n²) attention makes it exceed the engine's 280s internal timeout. Result in production: real user stories (200+ words) return `503 request_timeout` → `biassemble-core` records `rag_result = null` → the assessment silently falls back to roster-only. **The retrieval feature never actually delivers.** Confirmed end-to-end in core logs (`status:"unavailable"`, `durationMs:280341`) on 2026-07-10.

Two floors are visible in the data: a **~68s fixed floor** (82 passes on 2 vCPU even for a 9-word story) and a **super-linear climb** with story length. No premise-truncation or hypothesis-tuning removes the floor — only fewer passes or a different mechanism does. 82 DeBERTa passes on 2 shared vCPUs is the wrong shape for this hardware, permanently.

The "no generative LLM in engine" boundary (ADR-002 §2) was chosen when NLI *looked* CPU-viable. That premise is now falsified by measurement. ADR-002 explicitly pre-authorized this exact escalation: *"the same `SelectionStrategy` slot later hosts (a) a fine-tuned small model … or (b) an LLM-shortlist."* This ADR triggers option (b) as a local model, not a remote call.

## 2. Decision

**The decision is the mechanism, not the model:** adopt a **generative, local-inference `SelectionStrategy`** that reads the story **once** and names the biases — one prefill + short generation instead of 82 classification passes. Keep NLI and vector strategies intact; selection stays **flag-controlled** via the existing `SELECTION_STRATEGY` env var. Vector search runs concurrently as a complementary signal (same union pattern as `nli_union`). The specific model is an implementation detail decided by the spike, not by this ADR.

- **Candidate model (pending the spike, NOT decided here):** `Qwen2.5-1.5B-Instruct` is the *starting candidate cartridge* — Apache-2.0, **ungated** (no token/approval friction on the Space, unlike Llama-3.2), official GGUF published, fits `cpu-basic` (16GB RAM; Q4 ≈ ~1GB), small enough to LoRA-fine-tune free later (§10). Run as **GGUF `Q4_K_M` via `llama.cpp` (`llama-cpp-python`)**: CPU generation is memory-bandwidth-bound, so Q4 streams ~4× less weight data per token (~4× faster) and llama.cpp's SIMD int-kernels beat PyTorch's generic float CPU path; proven on free `cpu-basic` (a live 3B Q4 Space runs on that tier today). **Which model actually ships is decided by §7's spike + gates, on the ladder in research.md** — this ADR commits only to "a small local generative model," not to Qwen. All model-specific detail lives in `specs/004-add-llm-model/research.md`.
- **Falsifiability / validation-first (NON-NEGOTIABLE):** before any strategy/combiner/API wiring, a **spike must confirm the model finds biases at all** — feed 2–3 known-bias stories, verify it names plausible biases from the catalog. If a 1.5B model can't do this even roughly zero-shot, escalate model (0.5B ↔ 1.5B ↔ 3B) or defer to fine-tune-first. **Do not build integration on a model that doesn't work.** This is task 1, gating all others.
- **Crossing the "no generative LLM" boundary — deliberate and justified:** (a) it is **local inference, no external API, no data leaves the box** — the original boundary's spirit (privacy, cost, control) is preserved; a discriminative-vs-generative label was a proxy for those, and they still hold. (b) GGUF/CPU makes generation viable on free hardware (evidence above). (c) The future fine-tune path (§10) *requires* a generative cartridge in this slot. The boundary is amended, not ignored.
- **Both models stay:** DeBERTa remains the `nli_union` cartridge; `vector_only` remains. Nothing is deleted. A one-line env change reverts to NLI if this fails gates.

## 3. Architecture

```
story
  ├─► SelectionStrategy: LLM generative ─► {bias_id: score, source:"llm"} (read once)
  │     small local GGUF LLM (candidate: Qwen2.5-1.5B Q4) · prompt = story + catalog
  │     (id/name/indicators, from the catalog provider — not a hardcoded count)
  │     · structured JSON out · staged parse (generation→JSON→schema→catalog)
  └─► QueryStrategy: vector search ──────► {bias_id: max_chunk_cosine, source:"vector"}
                    │                        (concurrent, unchanged)
            UNION COMBINER (provenance-tagging)
  bias admitted if llm names it OR vec(b) ≥ vec_gate.
  per-bias `source` ∈ {"vector","llm","both"} — recorded on the result AND logged.
  llm score = model-reported confidence (or fixed prior if model gives none);
  vector score = existing max-chunk cosine. No cross-scale mixing (D-006 lesson from ADR-002).
```

New strategy value: `SELECTION_STRATEGY=llm_union`. Existing `vector_only` / `nli_union` untouched.

## 4. Provenance logging (the new observability requirement)

Every admitted bias is logged with **which method surfaced it**: `{"bias_id": ..., "source": "vector|llm|both", "llm_score": ..., "vec_score": ...}`. This is a hard requirement, not nice-to-have — it is (a) the demo story ("the LLM found X, vector found Y"), and (b) the raw material for evaluating whether the LLM actually adds recall over vector alone. Emit at info level per request, and carry `source` through to the API response (§6).

## 5. LLM mechanics

- **Runtime:** `llama-cpp-python`, model loaded once at app startup (like the DeBERTa pipeline today), held on `app.state`. Single-threaded generation; requests serialize on 2 vCPU — acceptable, because RAG is fire-and-forget async in core with graceful roster-only fallback under load (no user ever blocks on it).
- **Prompt:** story + compact catalog (bias `id`, `name`, `indicators`) → instruct the model to return **strict JSON**: `[{"bias_id","confidence","evidence"}]`, bias_ids constrained to the catalog. Reuse the repair-on-invalid-JSON discipline that already exists in core's parser philosophy.
- **Premise handling:** cap story tokens defensively (context window), but generative attention over one story is far cheaper than 82 NLI pairs — length is not the O(N_labels) problem it was.
- **Determinism for evals:** temperature 0 / greedy so eval runs are reproducible.

## 6. API & schema changes (additive only)

- Response `BiasResult` gains `source: "vector" | "llm" | "both"` (optional; absent on `vector_only`/`nli_union` paths for back-compat).
- New `SELECTION_STRATEGY=llm_union` accepted; unknown values still error.
- No breaking changes to existing fields. `biassemble-core` needs **zero** changes to keep working (it already tolerates the response shape).

## 7. Eval plan (the gates that decide merge)

Pre-gate (task 1, blocks everything): **smoke test** — 2–3 known-bias stories, model names plausible catalog biases. Binary go/no-go.

**Numbering note:** the SC-00N labels below follow the spec-003 gate tradition and do **not** match spec-004's SC numbers. Mapping: ADR SC-001..005 (recall/regression) = **spec SC-005** (recall gates, as a group) + **spec SC-004** (regression); ADR SC-006 (precision) = **spec SC-006**; ADR SC-007 (latency) = **spec SC-002**. tasks.md uses spec numbering throughout — defer to it.

Merge gates (same SC discipline as spec-003, re-run on the new strategy):
- SC-001 positive Recall@5 ≥ 0.85
- SC-002 negative empty_rate ≥ 0.90
- SC-003 adversarial Recall@5 ≥ 0.333
- SC-004 edge Recall@5 ≥ 0.583
- SC-005 core regression: pass
- **SC-006 (NEW) precision guard:** the new strategy's false-positive rate MUST NOT exceed the NLI baseline's by more than a small margin (target ≤ +5pp). A generative model can lift recall while inventing plausible-but-wrong biases; recall gates alone would hide that. Precision is a first-class gate, not an afterthought.
- **SC-007 (NEW) latency:** the strategy MUST complete a realistic (~200-word) story **within core's RAG timeout budget** on `cpu-basic`; **target p50 < 45s**. Distinguish the requirement (completes within budget) from the engineering target (45s) — 45s is an estimate to beat, the timeout is the hard bound. This is the dimension spec-003 silently failed.

## 8. Task list (spec-kit format — detail lives in tasks.md)

1. **Spike (gating):** load Qwen GGUF via llama-cpp-python, run 2–3 stories, confirm bias detection + measure latency. Go/no-go.
2. Add `llm_generative` selection behind `SelectionStrategy`; prompt + strict-JSON parse.
3. Union combiner with per-bias `source` tagging.
4. Provenance logging (§4) + API `source` field (§6).
5. `SELECTION_STRATEGY=llm_union` wiring; keep NLI/vector cartridges.
6. Eval run against SC-001..006; latency profile on cpu-basic.

## 9. Out of scope (refuse these in-session)

- Fine-tuning the model (future — needs the §10 dataset first).
- Removing NLI or vector strategies (both stay, flag-selectable).
- GPU / paid hardware / multi-replica / concurrency scaling.
- Any change to `biassemble-core` (it already works unchanged).
- Prompt-tuning beyond what's needed to pass gates (don't repeat spec-002's iterate-forever error).
- **Explanation/reasoning quality is a non-goal.** The model's *only* responsibility is candidate bias **selection** (which bias_ids apply + a rough confidence). Any evidence string it emits is a debugging aid, not a product-quality explanation — reasoning/explanation quality belongs to `biassemble-core`'s assessment LLM, not here. Do not evaluate or tune this model for prose quality.

## 10. Consequences

- Engine gains a third selectable strategy; the generative-LLM boundary is crossed **locally** and documented.
- Per-request latency for realistic stories goes from **>280s (fails, 503)** to a target **<45s (completes)** — the feature actually delivers for the first time.
- Provenance logging + `source` field give the demo narrative and the recall-attribution data.
- **The fine-tune flywheel is unlocked:** `biassemble-core` already pays Gemini to label every real story; those `(story → biases)` pairs are a free SFT dataset. Distill Gemini → this small cartridge → swap the GGUF, engine code unchanged. Picking a small ungated model now is what makes that step cheap. (Ensuring core *stores* those pairs from day one is a core-side follow-up, noted, out of scope here.) **Interface contract for the swap:** the cartridge slot exposes exactly `story → [{bias_id, confidence}]` (+ optional evidence). No model-, tokenizer-, or GGUF-specific assumptions may leak past the `LLMGenerator`/prompt boundary — the future fine-tuned model must drop into that same signature with zero call-site changes.
- Cost stays **$0** (free `cpu-basic`, ungated Apache-2.0 model, local inference).

## 11. Execution log

- 2026-07-10 — Proposed. Latency evidence gathered from live Space; model/runtime verified available and ungated; free-tier GGUF pattern confirmed running on `cpu-basic`.
