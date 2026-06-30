import json
from dataclasses import asdict
from pathlib import Path

import asyncpg

from src.config import settings
from src.db.queries import UPSERT_CHUNK
from src.indexing.chunk_builder import BiasChunk, build_chunks
from src.indexing.embedder import EmbeddedChunk, embed_chunks
from src.indexing.normalizer import normalize
from src.indexing.sources.base import KnowledgeSource
from src.providers.base import EmbeddingProvider

ARTIFACTS_DIR = Path("artifacts")


async def run_indexing(
    source: KnowledgeSource,
    provider: EmbeddingProvider,
    pool: asyncpg.Pool,
) -> int:
    """Full indexing pipeline: load → normalize → chunk → embed → upsert.

    Returns the number of rows actually inserted. Rows that already exist under
    the same (taxonomy_version, bias_id, chunk_type, chunk_hash) are skipped —
    so re-running on unchanged content is safe.
    """
    taxonomy_version = settings.taxonomy_version

    raw_docs = source.load()
    print(f"indexer: {len(raw_docs)} raw documents from '{source.name}'")

    normalized = normalize(raw_docs)
    chunks = build_chunks(normalized, taxonomy_version)
    _write_chunks_artifact(chunks)

    embedded = embed_chunks(chunks, provider, settings.index_batch_size)
    _write_embeddings_artifact(embedded)

    rows_inserted = await _upsert(embedded, pool, taxonomy_version, provider.model_name)
    skipped = len(embedded) - rows_inserted
    print(f"indexer: {rows_inserted} inserted, {skipped} skipped (already indexed)")
    return rows_inserted


async def _upsert(
    embedded: list[EmbeddedChunk],
    pool: asyncpg.Pool,
    taxonomy_version: str,
    model_name: str,
) -> int:
    """Insert each chunk row; ON CONFLICT DO NOTHING returns 'INSERT 0 0' for skips."""
    rows_inserted = 0
    async with pool.acquire() as conn:
        for ec in embedded:
            c = ec.chunk
            result = await conn.execute(
                UPSERT_CHUNK,
                c.bias_id,
                c.chunk_type,
                c.source_section,
                c.chunk_text,
                c.chunk_hash,
                json.dumps(asdict(c.full_document)),  # JSONB
                _fmt_vector(ec.embedding),             # pgvector string format
                c.source,
                json.dumps(c.metadata),               # JSONB
                taxonomy_version,
                model_name,
                c.chunk_index,
            )
            # asyncpg returns the command tag as a string: "INSERT 0 1" or "INSERT 0 0"
            if result.endswith(" 1"):
                rows_inserted += 1
    return rows_inserted


def _fmt_vector(embedding: list[float]) -> str:
    """Serialize a float list to pgvector wire format: '[0.1,0.2,...]'."""
    return "[" + ",".join(str(x) for x in embedding) + "]"


def _write_chunks_artifact(chunks: list[BiasChunk]) -> None:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    data = [
        {
            "bias_id": c.bias_id,
            "chunk_type": c.chunk_type,
            "source_section": c.source_section,
            "chunk_text": c.chunk_text[:200],
            "chunk_hash": c.chunk_hash,
            "chunk_index": c.chunk_index,
        }
        for c in chunks
    ]
    (ARTIFACTS_DIR / "chunks.json").write_text(json.dumps(data, indent=2))
    print(f"indexer: wrote artifacts/chunks.json ({len(chunks)} chunks)")


def _write_embeddings_artifact(embedded: list[EmbeddedChunk]) -> None:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    data = [
        {
            "bias_id": ec.chunk.bias_id,
            "chunk_type": ec.chunk.chunk_type,
            "chunk_hash": ec.chunk.chunk_hash,
            "embedding_dim": len(ec.embedding),
            "embedding_preview": ec.embedding[:5],  # first 5 dims for sanity check
        }
        for ec in embedded
    ]
    (ARTIFACTS_DIR / "embeddings.json").write_text(json.dumps(data, indent=2))
    print(f"indexer: wrote artifacts/embeddings.json ({len(embedded)} embeddings)")
