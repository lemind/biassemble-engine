# Phase 1 Data Model: Generative LLM Bias Selection

Feature: `004-add-llm-model`. **No database changes.** All changes are config, in-memory entities, and one additive response field.

## Config additions (`src/config.py`)

| Setting | Type | Default | Notes |
|---|---|---|---|
| `selection_strategy` | str | `vector_only` | **Now accepts `llm_union`** (in addition to existing `vector_only`, `nli_union`). Unknown value → startup/serve error (FR-004). |
| `llm_model_repo` | str | `Qwen/Qwen2.5-1.5B-Instruct-GGUF` | HF repo hosting the GGUF |
| `llm_gguf_file` | str | `qwen2.5-1.5b-instruct-q4_k_m.gguf` | quant file within the repo |
| `llm_context_tokens` | int | `4096` | model context window cap |
| `llm_max_output_tokens` | int | `512` | short JSON list |
| `llm_temperature` | float | `0.0` | greedy → reproducible (FR-011) |
| `llm_threads` | int | `2` | match cpu-basic vCPUs |
| `llm_log_raw` | bool | `false` | debug only — log the raw model output (too large for prod; on for prompt iteration, research R4) |

All via env (pydantic-settings), mirroring existing `nli_*` knobs. Existing settings unchanged. The response's top-level `llm_model` display string (contract v3) is derived from `llm_model_repo`/`llm_gguf_file` — it is not a separate config field.

## In-memory entities

### `BiasCandidate` (LLM output, internal)
Parsed from model JSON, one per named bias:
- `bias_id: str` — MUST be in the catalog, else dropped
- `confidence: float` — model-reported 0–1 (or a fixed prior if the model omits it)
- `evidence: str` — short quote/justification from the story

### `StrategyMetadata` (extend existing dataclass, `src/selection/base.py`)
Add fields (all optional, default `None`; existing strategies leave them unset):
- `llm_scores: dict[str, float] | None` — bias_id → llm confidence
- `sources: dict[str, str] | None` — bias_id → `"vector" | "llm" | "both"`
- `llm_latency_ms: float | None`
- `truncated_story: bool | None`

### `AdmittedBias` (conceptual, produced by the union combiner)
The combiner yields, per admitted bias: `bias_id`, `source ∈ {vector, llm, both}`, and the separate `llm_score` / `vec_score` (not blended onto one scale, research R5). Ordering is the **deterministic total sort** from research R5: `(source rank: both<llm<vector, llm_confidence desc, vec_score desc, bias_id asc)` → top-K. The sort must be fully specified down to `bias_id` so evals are reproducible (FR-011) and two implementations rank identically.

## Response schema change (`src/schemas/response.py`)

`BiasResult` gains ONE additive optional field:

```
source: Literal["vector", "llm", "both"] | None = None
```

- Populated only on the `llm_union` path.
- `None`/omitted for `vector_only` and `nli_union` → **byte-compatible** with today's responses (FR-005, FR-010).
- All existing fields (`id`, `name`, `retrieval_score`, `definition`, `examples`, `indicators`, `false_positives`, `related_biases`) unchanged.

## Provenance log record (per request, `llm_union` path)

Structured log line per admitted bias:
```
{"event": "bias_admitted", "request_id": ..., "bias_id": ...,
 "source": "vector|llm|both", "llm_score": <float|null>, "vec_score": <float|null>}
```
Plus one summary line: `{"event": "llm_selection_done", "llm_latency_ms": ..., "admitted": N, "from_llm": a, "from_vector": b, "from_both": c}`.

## Validation rules (from FRs)

- `bias_id` not in catalog → dropped (FR-007).
- Malformed model output → empty candidate list, request still succeeds (FR-007).
- Model load failure at startup → clear error, do not serve (FR-007).
- `selection_strategy` unknown → reject (FR-004).
- Same story → same admitted set (greedy, FR-011).
