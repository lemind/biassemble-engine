# Contract: GET /health

**Version**: v1 | **Auth**: None

---

## Request

```
GET /health
```

No authentication required. Must respond in under 50ms under normal conditions.

---

## Response 200

```json
{
  "status": "ok",
  "model_loaded": true,
  "embedding_model": "all-MiniLM-L6-v2",
  "embedding_dimension": 384,
  "provider_dimension": 384,
  "taxonomy_version": "2026-06-27",
  "rows_indexed": 150,
  "last_indexed_at": "2026-06-27T10:00:00Z",
  "database_connected": true
}
```

---

## Field Semantics

| Field | Meaning |
|-------|---------|
| `status` | `"ok"` always if service is running (even when DB is down) |
| `model_loaded` | `true` if embedding model loaded successfully at startup |
| `embedding_model` | Model name from config |
| `embedding_dimension` | Expected dimension from `settings.embedding_dimension` |
| `provider_dimension` | Actual dimension reported by the loaded model. If `provider_dimension ≠ embedding_dimension`, startup crashes — but this field lets you see the mismatch instantly in logs before the crash. |
| `taxonomy_version` | Version currently in use from config |
| `rows_indexed` | `COUNT(*)` from `bias_embeddings` for current taxonomy_version. `0` means index not populated. |
| `last_indexed_at` | `MAX(indexed_at)` for current taxonomy_version. Stale value = knowledge not updated after authoring change. |
| `database_connected` | `true` if DB pool is reachable. `false` does NOT cause a 5xx — service remains alive. |

---

## Degraded States

| Condition | `status` | `database_connected` | `rows_indexed` |
|-----------|----------|----------------------|----------------|
| Fully healthy | `"ok"` | `true` | > 0 |
| DB unreachable | `"ok"` | `false` | `null` |
| Index not populated | `"ok"` | `true` | `0` |
| Model not loaded | Service won't start — this state is unreachable |

`database_connected: false` is not a 5xx. The health endpoint remains responsive so Railway health checks pass and the service is not restarted unnecessarily. Retrieval requests will return `503` until the DB reconnects.
