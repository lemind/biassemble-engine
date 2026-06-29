CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS bias_embeddings (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    bias_id          TEXT        NOT NULL,
    chunk_type       TEXT        NOT NULL,
    source_section   TEXT        NOT NULL,
    chunk_text       TEXT        NOT NULL,
    chunk_hash       TEXT        NOT NULL,
    full_document    JSONB       NOT NULL,
    embedding        vector(384) NOT NULL,
    source           TEXT        NOT NULL,
    metadata         JSONB       NOT NULL DEFAULT '{}',
    taxonomy_version TEXT        NOT NULL,
    embedding_model  TEXT        NOT NULL,
    chunk_index      INTEGER     NOT NULL,
    indexed_at       TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Deduplication: re-indexing the same content under the same version is a no-op
CREATE UNIQUE INDEX IF NOT EXISTS bias_embeddings_dedup_idx
    ON bias_embeddings (taxonomy_version, bias_id, chunk_type, chunk_hash);

CREATE INDEX IF NOT EXISTS bias_embeddings_bias_id_idx
    ON bias_embeddings (bias_id);

CREATE INDEX IF NOT EXISTS bias_embeddings_source_idx
    ON bias_embeddings (source);

CREATE INDEX IF NOT EXISTS bias_embeddings_taxonomy_version_idx
    ON bias_embeddings (taxonomy_version);

-- GIN enables JSONB filtering: WHERE metadata->>'source_file' = 'confirmation_bias.md'
CREATE INDEX IF NOT EXISTS bias_embeddings_metadata_idx
    ON bias_embeddings USING GIN (metadata);

-- No vector index at v1: pgvector exact scan is accurate and faster than IVFFlat at <= 300 rows.
-- IVFFlat requires lists * 30 rows for good recall — lists=10 on 150 rows silently degrades quality.
-- Add: CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops) WITH (lists=12)
-- only after row count exceeds 300.
