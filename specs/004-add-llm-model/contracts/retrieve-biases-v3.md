# Contract: POST /retrieve-biases (v3 additions)

**Extends**: `specs/001-rag-retrieval/contracts/retrieve-biases.md` (v1) and `specs/003-nli-zero-shot-shortlist/contracts/retrieve-biases-v2.md` (v2). Both unchanged.

**Breaking changes**: none. All additions are optional fields, absent unless `SELECTION_STRATEGY=llm_union`.

---

## Request — unchanged

```json
{ "story": "..." }
```

## Config — new accepted value

`SELECTION_STRATEGY` now accepts **`llm_union`** in addition to `vector_only` and `nli_union`. Any unrecognized value is rejected (startup or request error) — never silently defaulted.

## Response 200 — per-bias `source` (all strategies may include; populated on `llm_union`)

Each entry in `biases[]` MAY carry an additive optional field:

```json
{
  "id": "overconfidence_bias",
  "name": "Overconfidence Bias",
  "retrieval_score": 0.83,
  "definition": "...",
  "examples": "...",
  "indicators": "...",
  "false_positives": "...",
  "related_biases": "...",
  "source": "llm"
}
```

- `source ∈ {"vector", "llm", "both"}` — which signal surfaced the bias.
- **Absent / `null`** on `vector_only` and `nli_union` responses → byte-compatible with v1/v2 clients.

## Response 200 — additional top-level fields when `SELECTION_STRATEGY=llm_union`

```json
{
  "biases": [ /* ...each with "source" */ ],
  "retrieved_chunks": 12,
  "taxonomy_version": "2026-07-06.1",
  "embedding_model": "all-MiniLM-L6-v2",
  "request_id": "b3d2a1c0-...",

  "selection_strategy": "llm_union",
  "llm_model": "Qwen2.5-1.5B-Instruct",
  "llm_latency_ms": 18234.1,
  "truncated_story": false,
  "llm_scores":    { "overconfidence_bias": 0.88, "optimism_bias": 0.71 },
  "vector_scores": { "overconfidence_bias": 0.20, "sunk_cost_fallacy": 0.44 }
}
```

- Mirrors the shape v2 introduced for `nli_union` (`nli_scores`/`nli_latency_ms`), swapping in `llm_*`.
- Scores are reported **separately**, not blended (research R5).

## Error behavior — unchanged contract, new internal causes

- Malformed model output → treated as "no biases named by LLM"; request still `200` with vector-only admissions (and empty if none). Never `5xx` for parse failure (FR-007).
- Model failed to load at startup → engine does not serve `llm_union` and reports the failure (health/logs), consistent with how `nli_union` aborts startup on model-load failure today.
- `request_timeout` (503) semantics unchanged — but the whole point of this strategy is to complete well under the timeout for realistic stories (SC-002).

## Consumer impact

`biassemble-core` requires **zero changes**. It already tolerates the response shape; `source` and `llm_*` are additive and optional. Core may later read `source` for its own analytics, but is not required to.
