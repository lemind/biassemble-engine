# Skill: RAG Pipeline

## Flow

```
RetrieveRequest { story, story_analysis? }
      │
      ▼  query_builder.build()          → weighted query string
      │
      ▼  embedder.embed_query()         → query vector (list[float])
      │
      ▼  searcher.search(top_k)         → CandidateChunk[]
      │
      ▼  reranker.apply_threshold()     → filtered CandidateChunk[]
      │
      ▼  reranker.collapse(top_k)       → RetrievedBias[]
      │
      ▼  retriever.emit_metadata()      → RetrievalMetadata (logged, not returned)
      │
      ▼                                 → RetrieveResponse (BiasResult[] + meta)
```

## Internal Types

```python
# CandidateChunk — searcher output
bias_id: str
chunk_type: ChunkType        # enum — SEMANTIC_DEFINITION, SEMANTIC_EXAMPLE, etc.
source_section: str          # original markdown heading
chunk_text: str
full_document: dict
score: float                 # cosine similarity 0.0–1.0

# RetrievedBias — reranker output
bias_id: str
score: float                 # max chunk score across all chunks for this bias
matched_chunk_type: ChunkType
matched_text: str            # chunk that scored highest
definition / examples / indicators / false_positives / related_biases: str

# BiasResult — API DTO only
id / name / score / definition / examples / indicators / false_positives / related_biases
```

## Reranker Logic

1. Drop any `CandidateChunk` where `score < SIMILARITY_THRESHOLD`
2. Group remaining by `bias_id`
3. Score each bias by `max(chunk_scores)` — not mean
4. Sort descending, return top `RETURN_TOP_K`
5. Enrich from `full_document` — no second query needed

## RetrievalMetadata

Every request must emit `completed` log event with:
- `retrieval_id` (UUID) — correlates all events for one request
- All latencies: `embedding_latency_ms`, `search_latency_ms`, `rerank_latency_ms`, `total_latency_ms`
- `candidate_chunks`, `surviving_chunks`, `returned_biases`
- `top_score`, `avg_score`, `threshold_used`

**Not returned in API response. Log only.**

## API Response

```json
{
  "biases": [...],
  "retrieved_chunks": 12,
  "taxonomy_version": "v1",
  "embedding_model": "all-MiniLM-L6-v2"
}
```
