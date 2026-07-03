TABLE = "bias_embeddings"


def fmt_vector(embedding: list[float]) -> str:
    """Serialize a float list to pgvector wire format: '[0.1,0.2,...]'."""
    return "[" + ",".join(str(x) for x in embedding) + "]"

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

# Note: the vector similarity query is built dynamically in searcher.py with the
# embedding interpolated as a literal. asyncpg's type introspection for the 'vector'
# extension type causes extra DB round-trips that time out through the local proxy.

HEALTH_STATS = f"""
    SELECT COUNT(*)::int AS rows_indexed, MAX(indexed_at) AS last_indexed_at
    FROM {TABLE}
    WHERE taxonomy_version = $1
"""

STATS_BY_CHUNK_TYPE = f"""
    SELECT chunk_type, COUNT(*)::int AS cnt
    FROM {TABLE}
    WHERE taxonomy_version = $1
    GROUP BY chunk_type
"""

STATS_BY_SOURCE = f"""
    SELECT source, COUNT(*)::int AS cnt
    FROM {TABLE}
    WHERE taxonomy_version = $1
    GROUP BY source
"""

STATS_BY_VERSION = f"""
    SELECT taxonomy_version, COUNT(*)::int AS cnt
    FROM {TABLE}
    GROUP BY taxonomy_version
"""

# One definition chunk per bias — used to build the fallback roster at startup.
# DISTINCT ON picks the first row per bias_id ordered by chunk_index so the result
# is deterministic even if multiple definition chunks exist.
ROSTER_QUERY = f"""
    SELECT DISTINCT ON (bias_id)
        bias_id,
        full_document->>'name'       AS name,
        full_document->>'definition' AS definition
    FROM {TABLE}
    WHERE taxonomy_version = $1
      AND chunk_type = 'semantic_definition'
    ORDER BY bias_id, chunk_index
"""
