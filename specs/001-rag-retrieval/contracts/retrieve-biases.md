# Contract: POST /retrieve-biases

**Version**: v1 | **Auth**: Bearer token

---

## Request

```
POST /retrieve-biases
Authorization: Bearer {RAG_API_KEY}
Content-Type: application/json
```

```json
{
  "story": "string (required)",
  "request_id": "string (optional — UUID from caller for cross-service correlation)",
  "story_analysis": {
    "themes": ["string"],
    "beliefs": ["string"],
    "claims": ["string"]
  }
}
```

`story_analysis` is optional. `request_id` is optional — if provided by biassemble-core, it is echoed in the response and included in all structured log events for this request, enabling end-to-end tracing across services. If absent, the service generates its own `retrieval_id`.

---

## Response 200

```json
{
  "biases": [
    {
      "id": "confirmation_bias",
      "name": "Confirmation Bias",
      "retrieval_score": 0.87,
      "definition": "...",
      "examples": "...",
      "indicators": "...",
      "false_positives": "...",
      "related_biases": "..."
    }
  ],
  "retrieved_chunks": 12,
  "taxonomy_version": "v1",
  "embedding_model": "all-MiniLM-L6-v2",
  "request_id": "b3d2a1c0-..."
}
```

`biases` may be an empty array — this means retrieval ran successfully and no chunks exceeded the similarity threshold. It is NOT an error.

`retrieved_chunks` is the count before threshold filtering. Useful for debugging (e.g., `retrieved_chunks: 20, biases: []` means chunks were found but all scored below threshold).

---

## Error Responses

| Status | Body | When |
|--------|------|------|
| `401` | `{"error": "unauthorized"}` | Missing or invalid `Authorization` header |
| `422` | Pydantic validation error | Malformed request body |
| `503` | `{"error": "database_unavailable"}` | DB unreachable at request time |
| `503` | `{"error": "index_not_found", "taxonomy_version": "v1"}` | No rows in DB for configured taxonomy_version |
| `500` | `{"error": "retrieval_failed", "detail": "..."}` | Unexpected error during retrieval |

**Critical distinction**: `503` errors must never be confused with an empty `biases` array. `biases: []` means "retrieval worked, nothing relevant found." `503` means "retrieval could not run."

---

## Caller Contract (biassemble-core)

- Timeout: 500ms. If exceeded, fall back to static taxonomy. Never surface RAG errors to the user.
- Call site: `assessment.service.ts` before building the assessment prompt
- Auth: `Authorization: Bearer {RAG_API_KEY}` — shared secret via env var in both services
- On any 4xx/5xx or timeout: use full static bias catalog as fallback context, log the failure
