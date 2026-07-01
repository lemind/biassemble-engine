TABLE = "bias_embeddings"

# Upsert one chunk row. ON CONFLICT DO NOTHING skips rows that are already indexed
# under the same (taxonomy_version, bias_id, chunk_type, chunk_hash) — so re-running
# the indexer on unchanged content is always safe and idempotent.
UPSERT_CHUNK = f"""
    INSERT INTO {TABLE} (
        bias_id, chunk_type, source_section, chunk_text, chunk_hash,
        full_document, embedding, source, metadata,
        taxonomy_version, embedding_model, chunk_index, indexed_at
    ) VALUES (
        $1, $2, $3, $4, $5,
        $6::jsonb, $7::vector, $8, $9::jsonb,
        $10, $11, $12, NOW()
    )
    ON CONFLICT (taxonomy_version, bias_id, chunk_type, chunk_hash) DO NOTHING
"""

# Cosine similarity search using pgvector's <=> operator (lower = more similar).
# Returns the top-K chunks for the current taxonomy_version, ordered nearest-first.
SEARCH_CHUNKS = f"""
    SELECT
        bias_id,
        chunk_type,
        source_section,
        source,
        chunk_text,
        full_document,
        1 - (embedding <=> $1::vector) AS retrieval_score
    FROM {TABLE}
    WHERE taxonomy_version = $2
    ORDER BY embedding <=> $1::vector
    LIMIT $3
"""

# T020: health row count + stats GROUP BY — added when /health and /stats are wired
# COUNT_BY_VERSION = ...
# STATS_BY_CHUNK_TYPE = ...
