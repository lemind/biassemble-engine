# Contract: POST /retrieve-biases (v2 additions)

**Extends**: `specs/001-rag-retrieval/contracts/retrieve-biases.md` (v1 — unchanged)

**Breaking changes**: none. All additions are optional fields absent when `SELECTION_STRATEGY=vector_only`.

---

## Response 200 — additional fields when `SELECTION_STRATEGY=nli_union`

```json
{
  "biases": [...],
  "retrieved_chunks": 12,
  "taxonomy_version": "2026-07-06.1",
  "embedding_model": "all-MiniLM-L6-v2",
  "request_id": "b3d2a1c0-...",

  "selection_strategy": "nli_union",
  "hypotheses_version": "v1",
  "nli_latency_ms": 1840.3,
  "truncated_premise": false,
  "nli_scores": {
    "confirmation_bias": 0.921,
    "overconfidence_bias": 0.874,
    "anchoring_bias": 0.103
  },
  "vector_scores": {
    "confirmation_bias": 0.782,
    "overconfidence_bias": 0.201,
    "anchoring_bias": 0.643
  },
  "combined_scores": {
    "confirmation_bias": 0.880,
    "overconfidence_bias": 0.672,
    "anchoring_bias": 0.264
  }
}
```

`nli_scores`, `vector_scores`, `combined_scores` contain only the returned `biases` entries, not all 38.

---

## Updated Caller Contract (biassemble-core)

- **Timeout**: raised from 500ms → **5000ms** (`RAG_TIMEOUT_MS=5000`). Required — NLI inference takes 1–3s CPU. This is a named config change shipped with spec 003.
- All other caller behavior unchanged (fallback on timeout/error, Bearer auth, no code changes to biassemble-core for this spec).

---

## Backward Compatibility

When `SELECTION_STRATEGY=vector_only` (the default), the response is byte-for-byte identical to v1. The new fields are absent. Existing biassemble-core code requires no changes regardless of which strategy is active — it reads only `biases`, `taxonomy_version`, and `request_id`.
