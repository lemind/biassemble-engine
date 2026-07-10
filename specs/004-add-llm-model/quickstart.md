# Quickstart: Generative LLM Bias Selection

Feature `004-add-llm-model`. **Do the spike first (Step 1). Do not build anything else until it's green.**

## Step 1 — Validation spike (the SC-001 go/no-go gate)

Goal: prove the model names biases at all before writing any integration.

```bash
# in the engine repo, existing venv
pip install "llama-cpp-python==<pinned>" huggingface_hub

# throwaway script — scripts/spike_llm_bias.py
#   1. download Qwen2.5-1.5B-Instruct-GGUF (q4_k_m) via huggingface_hub
#   2. build prompt: system + catalog(bias_id,name,indicators) + story
#   3. greedy generate; print raw output + parsed JSON + wall time
#   4. run on 2–3 known-bias stories (overconfidence, sunk-cost, confirmation)
python scripts/spike_llm_bias.py
```

**Pass criteria (binary):**
- For each known-bias story, the model names the expected catalog bias (among others is fine).
- Neutral story → few/no biases.
- Wall time for a ~200-word story is in the ballpark of <45s on cpu-basic (measure; if far over, drop to `0.5B` and re-run).

**If it fails**: escalate the model (0.5B ↔ 1.5B ↔ 3B) or stop and reconsider — do **not** proceed to Step 2. (ADR-003 §2 falsifiability clause.)

## Step 2 — Run the strategy locally

```bash
export SELECTION_STRATEGY=llm_union
export LLM_MODEL_REPO=Qwen/Qwen2.5-1.5B-Instruct-GGUF
export LLM_GGUF_FILE=qwen2.5-1.5b-instruct-q4_k_m.gguf
uvicorn src.api.app:app --port 7860

curl -s -X POST localhost:7860/retrieve-biases \
  -H 'Content-Type: application/json' -H "X-RAG-Key: $RAG_API_KEY" \
  -d '{"story":"<a ~200-word story that shows overconfidence>"}' | jq
```

Expect: `biases[]` each with a `source` of `vector|llm|both`; top-level `llm_*` fields; a `bias_admitted` log line per bias with its source.

## Step 3 — Verify the flag keeps the old strategies intact

```bash
SELECTION_STRATEGY=vector_only  uvicorn ...   # unchanged behavior, no `source` field
SELECTION_STRATEGY=nli_union    uvicorn ...   # unchanged behavior (DeBERTa path)
SELECTION_STRATEGY=bogus        uvicorn ...   # must error, not default silently
```

## Step 4 — Eval gates

```bash
python -m src.evaluation.evaluate --strategy llm_union   # SC-001..006
```
Gates: positive Recall@5 ≥ 0.85, negative empty-rate ≥ 0.90, adversarial ≥ 0.333, edge ≥ 0.583, existing strategies unchanged, **and p50 latency < 45s on cpu-basic (SC-002)**.

## Step 5 — Deploy

Set `SELECTION_STRATEGY=llm_union` + `LLM_*` vars on the HF Space (same mechanism as the existing `NLI_*`/`REQUEST_TIMEOUT_MS` variables). Space auto-restarts; confirm the model loads and a real story completes under the timeout with `source`-tagged biases in the response.
