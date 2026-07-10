# Phase 0 Research: Generative LLM Bias Selection

Feature: `004-add-llm-model` · Decision record: `adr/003-generative-llm-bias-selection.md`

All decisions below resolve the Technical Context. No open `NEEDS CLARIFICATION`.

## R1 — Why replace the NLI mechanism at all (evidence)

**Decision**: Add a generative-LLM strategy; do not keep NLI as the production default.

**Rationale**: Measured on the live Space 2026-07-10, holding everything constant except story length against the 82-hypothesis NLI batch: 9-word story 67.8s, 54-word 71.4s, 126-word 133.9s, 234-word **>200s → timeout**. Root cause is mechanism-shape: zero-shot NLI is O(N_labels) — one DeBERTa forward pass per bias hypothesis (~82), story duplicated as premise, `padding=True` pushing long stories to ~512-token O(n²) attention on 2 shared vCPUs. Real user stories (200+ words) exceed the engine's 280s internal timeout → `503` → core records `rag_result=null` → assessment silently roster-only. The feature never delivers.

**Alternatives considered**: (a) truncate premise / fewer hypotheses — reduces slope but not the ~68s floor (82 passes on 2 vCPU); (b) upgrade hardware — rejected, must stay free; (c) GPU — rejected, cost.

## R2 — Model choice

**Decision**: `Qwen2.5-1.5B-Instruct` as the default cartridge; fallback ladder `0.5B ↔ 1.5B ↔ 3B` decided by the SC-001 spike + SC-002 latency.

**Rationale**: Apache-2.0 and **ungated** (verified via HF API) — no token/license-approval friction on the Space, unlike `meta-llama/Llama-3.2-1B` (`gated=manual`). Official GGUF published (`Qwen2.5-1.5B-Instruct-GGUF` verified). Follows instructions well enough to name catalog biases zero-shot at 1.5B. The ladder stays in one ungated family for frictionless swaps: `Qwen2.5-0.5B-Instruct` (smaller/rougher/faster) ↔ `1.5B` (default) ↔ `Qwen2.5-3B-Instruct` (smarter/slower). Small enough to LoRA-fine-tune free later (the ADR-003 §10 flywheel).

**Alternatives considered**: Llama-3.2-1B (gated → deploy friction); SmolLM2-360M (too weak zero-shot pre-fine-tune); Phi-3.5-mini 3.8B (smarter but slower, and a family switch — held only as a last-resort escalation if the Qwen ladder can't clear the gates).

## R3 — Runtime: GGUF via llama.cpp vs raw transformers

**Decision**: `llama-cpp-python` loading a `Q4_K_M` GGUF. Keep raw `transformers` as a documented fallback if the wheel fails to build on the Space.

**Rationale**: CPU generation is memory-bandwidth-bound → tokens/sec ≈ RAM-bandwidth ÷ model-bytes. Q4 stores weights at 4-bit → ~4× less data streamed per token → ~4× faster than fp16 transformers, plus llama.cpp's SIMD int-kernels vs PyTorch's generic float CPU path. Pattern is proven on the exact free tier: a live 3B Q4 Space runs on `cpu-basic` today, and HF ships an official `llama-cpp-python` Space template. Q4_K_M of 1.5B ≈ ~1GB, trivially inside 16GB.

**Risk + mitigation**: `llama-cpp-python` compiles C++ at install; on rare Space images the build can fail. Mitigation: pin a version with prebuilt CPU wheels; fallback to `transformers` (slower but proven-loadable, since DeBERTa already loads via transformers today). Recorded as a Phase-2 spike sub-check.

## R4 — Prompt & output contract

**Decision**: Prompt = system instruction + compact catalog (`bias_id`, `name`, `indicators` only) + the story. The catalog is **injected from the existing catalog/roster provider, never hardcoded** — a future 70-bias taxonomy changes nothing in the prompt builder. Model returns **strict JSON**: `[{"bias_id", "confidence", "evidence"}]`, `bias_id` constrained to the catalog. Greedy decoding (temperature 0) for reproducibility (FR-011).

**Parsing is an explicit staged pipeline, each stage logged separately** (invaluable for prompt debugging later):
```
raw model text
  → [1] JSON extraction   (pull the JSON span out of any surrounding prose)
  → [2] schema validation (each item has bias_id + confidence; coerce/repair)
  → [3] catalog validation (drop bias_ids not in the catalog)
  → candidate list        (empty on any total failure — never raises, FR-007)
```
Each stage emits a structured log with counts (extracted N, schema-valid M, catalog-valid K). The **raw model output** is logged only behind a debug flag (`llm_log_raw`) — off in production (too large), on for prompt iteration.

**Rationale**: Passing only `indicators` keeps the prompt short → faster prefill, less drowning for a small model. The staged pipeline separates *generation* from *validation* so a failure is attributable to a specific stage, not a mystery empty list. Constraining to catalog ids keeps output aligned with the fixed taxonomy and the eval harness.

**Alternatives considered**: free-text output (harder to parse/eval); function-calling/grammars (llama.cpp GBNF grammar is a nice-to-have optimization, deferred — start with prompt + staged parse).

## R5 — Combiner: llm ∪ vector, and score scales

**Decision**: A bias is admitted if the **LLM names it** OR `vector_score(b) ≥ vec_gate` (existing gate). Per-bias `source` = `both` if in both signals, `llm`/`vector` if in one. Do **not** mix the two scores onto one scale: report `llm_confidence` and `vec_score` separately.

**Ranking is deterministic and total** (so two implementations produce identical order — no "llm else vector" ambiguity on ties). Sort admitted biases by, in order:
```
1. source rank:  both (0) < llm (1) < vector (2)     — dual-signal first
2. llm_confidence descending                          — (0.0 when source == vector)
3. vec_score descending                               — (0.0 when source == llm)
4. bias_id ascending                                  — final deterministic tiebreak
```
Then take top-K (existing `return_top_k`).

**Rationale**: Union preserves the whole point of the second signal — the LLM must surface biases vector misses (spec US1/US3), and vice-versa. The "don't cross-scale incommensurable scores" lesson is inherited from ADR-002 (the set-size min-max bug). A fully specified sort key (down to `bias_id`) removes implementation-dependent ordering, which matters for reproducible evals (FR-011) and stable Recall@5.

**Alternatives considered**: weighted blend like `nli_union`'s `w_nli·nli + w_vec·vec` — deferred; LLM confidence from a small model isn't calibrated, so a raw blend would be noise. Revisit post-fine-tune.

## R6 — Provenance / source semantics

**Decision**: `source ∈ {vector, llm, both}` per admitted bias, carried on `BiasResult.source` (optional; `None`/absent for `vector_only` and `nli_union` paths) and logged per request with `llm_score` + `vec_score`.

**Rationale**: Additive → back-compatible (FR-005/FR-010). Required for the demo narrative and for measuring LLM-added recall (ADR-003 §4). Existing strategies leave it absent so their responses are byte-compatible.

## R7 — Latency budget (how <45s is plausible)

**Decision**: Target budget on `cpu-basic`: model prefill (story + short catalog, greedy) + generation of a short JSON list. Vector search runs concurrently (~0.5s, off the critical path). Spike measures the real number; if 1.5B misses <45s, drop to 0.5B.

**Rationale**: Unlike NLI's 82 passes, this is one prefill + short decode. Q4 1.5B on 2 vCPU generating ~50–150 tokens is seconds-to-low-tens-of-seconds. The floor that killed NLI (82×) is gone. SC-002 is the gate; R2's ladder is the lever.

## Resolved unknowns

| Unknown | Resolution |
|---|---|
| Which model | Qwen2.5-1.5B-Instruct (ungated, Apache-2.0, GGUF); ladder 0.5B↔1.5B↔3B |
| Which runtime | llama-cpp-python Q4_K_M; **built from source** (see Spike result); transformers fallback |
| Prompt/output shape | **chat template required** (instruct model) — `create_chat_completion`, NOT raw text completion; system + catalog(indicators) + story → strict JSON, greedy, catalog-constrained |
| llm↔vector combination | union admit; separate scores; source tagging; no cross-scale blend |
| Meets <45s? | plausible locally (warm ~12s w/ full catalog); **cpu-basic unconfirmed — T020 gate**; levers: prompt-prefix cache, trim catalog, 0.5B |
| Install risk | **materialized** — only prebuilt linux wheel is musl (fails on glibc); build from source + Dockerfile build tools |

## Spike result (T003/T004 — 2026-07-10) — **GO** ✅

Ran `scripts/spike_llm_bias.py` locally (glibc): Qwen2.5-1.5B-Instruct Q4_K_M via source-built llama-cpp-python, 38-bias catalog from `knowledge/*.md`, greedy.

**Functional — GO.** With the **chat template** (`create_chat_completion`), valid in-catalog JSON on all four stories:
- overconfidence story → `confirmation_bias` (plausible catalog bias, valid JSON — arguably should be `overconfidence_bias`; precision is an SC-005/006 concern, not the gate)
- sunk-cost story → `sunk_cost_fallacy` ✅ exact
- confirmation story → `confirmation_bias` ✅ exact
- neutral story → `[]` ✅ **no hallucination**

The model finds biases, constrains to the catalog, includes evidence, and stays empty on neutral input. Gate ("finds biases at all") passes.

**Critical prompt finding**: raw text completion (`llm(prompt)`) produced garbage (`{"bias_id": ""}` / `{}`) — Qwen is an *instruct* model and MUST be prompted via its chat template. First integration decision: use `create_chat_completion`, not raw completion. Parser must still tolerate a stray object-vs-array and non-catalog ids (staged parse, R4).

**Latency** (local, faster than cpu-basic): model load 0.7s; warm ~12s/story (11.7–16.2s); cold first call ~65s (long-catalog prefill). Warm is dominated by prefill of the catalog prompt, not decode. **cpu-basic will be slower — unconfirmed, gated at T020.** Levers if it misses <45s: (a) llama.cpp prompt-prefix caching (the catalog prefix is identical every call — big win), (b) trim catalog further, (c) 0.5B rung. Do not treat 12s local as the cpu-basic number.

**Catalog size caveat (compare like-for-like at T020):** the 12s figure is for **38 biases × ≤3 indicators each** (`scripts/spike_llm_bias.py`'s `inds[:3]` trim), not the full indicator lists in `knowledge/*.md` (which run up to 10 per file, per `STYLE_GUIDE.md`). If T006's real `build_prompt` sends more than 3 indicators/bias, the prompt is longer and warm latency will exceed 12s — T020 must profile against the **actual** prompt `build_prompt` sends, not re-use this number. Confirm the indicator count used at integration time and note it alongside the T020 result.

**⚠️ This caveat materialized — real number, not speculation (Phase 3 integration check, 2026-07-10):** with the REAL DB-sourced catalog (`load_catalog`, same `_INDICATORS_PER_BIAS = 3` cap as the spike) and the REAL `LLMGenerator`, end-to-end `LLMUnionStrategy.select()` measured **48–60s locally** — 3–5× the spike's 12s, at the *same* indicator cap. Root cause: DB-sourced indicator text is verbose (real bullets from `knowledge/*.md`, e.g. "Decides something feels safe because it feels good, without checking the actual risk data" — a full sentence per indicator), producing **2573 user-message tokens** (measured directly via the model's tokenizer) vs whatever shorter text the spike's ad-hoc parsing happened to produce. This is comfortably under `n_ctx=4096` (no truncation/context-overflow — verified: 2666 prompt tokens + 512 output budget = 3178, well inside 4096), so it is a genuine prefill-speed cost, not a context bug. **T020 must treat 45–60s+ as the realistic local baseline, not 12s** — cpu-basic will likely be slower still. This makes the (a) prompt-prefix caching and (c) 0.5B-rung levers materially more likely to be *required*, not just contingency.

**Also observed (Phase 3 integration check):** the model is prompt-sensitive under greedy (temperature=0) decoding — the verbatim spike story correctly produced `confirmation_bias` again, but a lightly paraphrased version of the same story (contractions expanded, one clause shortened) produced `[]` (no bias named; degraded gracefully to vector-only signal, no crash — FR-007 held). Not a code defect — inherent small-model brittleness. Relevant to T019: expect real variance in the precision/recall eval, not just a clean pass/fail.

**Runtime finding (deployment-critical)**: the only prebuilt linux `llama-cpp-python` wheel (abetlen `cpu` index, `linux_x86_64`) is **musl-linked** (`libc.musl-x86_64.so.1 => not found`) and will not load on the glibc base image; PyPI ships sdist only. → **build from source.** Applied: dropped the abetlen index from `pyproject.toml`, added `build-essential cmake` to the `Dockerfile`, re-locked to the PyPI sdist. Verified building on glibc (~2m) and loading + running the GGUF.

**Model rung**: 1.5B passes functionally. Keep 0.5B as the latency fallback for T020 if cpu-basic warm exceeds the budget.
