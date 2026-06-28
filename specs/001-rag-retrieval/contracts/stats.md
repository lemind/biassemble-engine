# Contract: GET /stats

**Version**: v1 | **Auth**: None

---

## Request

```
GET /stats
```

No authentication required. Returns a detailed snapshot of what is currently deployed and indexed. Distinct from `/health` — health answers "is the service alive?", stats answers "what exactly is running?"

---

## Response 200

```json
{
  "taxonomy_version": "2026-06-27",
  "embedding_model": "all-MiniLM-L6-v2",
  "embedding_dimension": 384,
  "indexed_rows": 150,
  "chunk_count_by_type": {
    "semantic_definition": 30,
    "semantic_example": 30,
    "semantic_indicator": 30,
    "semantic_false_positive": 30,
    "semantic_related": 30
  },
  "rows_per_taxonomy_version": {
    "2026-06-27": 150,
    "2026-06-15": 145
  },
  "sources": {
    "taxonomy": 150
  },
  "built_at": "2026-06-27T10:00:00Z",
  "git_sha": "a3f9c12"
}
```

---

## Field Semantics

| Field | Source | Meaning |
|-------|--------|---------|
| `taxonomy_version` | config | Active knowledge version |
| `embedding_model` | config | Active embedding model name |
| `embedding_dimension` | provider | Actual dimension from loaded model |
| `indexed_rows` | DB count | Total rows for current taxonomy_version |
| `chunk_count_by_type` | DB group-by | Rows per `chunk_type` — uneven distribution indicates missing sections |
| `rows_per_taxonomy_version` | DB group-by | Rows per `taxonomy_version` — shows all versions in DB, not just active one. Useful during migrations: old version rows visible until explicitly deleted. |
| `sources` | DB group-by | Rows per `source` value — shows contribution per knowledge source |
| `built_at` | DB max | `MAX(indexed_at)` for current taxonomy_version |
| `git_sha` | env var `GIT_SHA` | Commit SHA of deployed code. Set at build time. `null` if not provided. |

---

## When to use

- After a deploy: confirm the right taxonomy_version and model are active
- After re-indexing: confirm `indexed_rows` updated and `built_at` is recent
- Debugging retrieval regressions: compare `chunk_count_by_type` across versions to spot missing sections
- Monitoring: `sources` breakdown becomes meaningful when Wikipedia or Book sources are added
