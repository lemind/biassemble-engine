import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path

import asyncpg

from src.config import settings
from src.db.queries import UPSERT_CHUNK, fmt_vector
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


_UPSERT_TIMEOUT = 30  # seconds per attempt
_UPSERT_RETRIES = 3


async def _upsert(
    embedded: list[EmbeddedChunk],
    pool: asyncpg.Pool,
    taxonomy_version: str,
    model_name: str,
) -> int:
    """Bulk-insert all chunks via executemany with timeout and retries.

    Falls back message if all retries fail — use scripts/generate_seed_sql.py
    to produce a SQL file you can apply via the Supabase SQL editor instead.
    """
    rows: list[tuple] = [
        (
            ec.chunk.bias_id,
            ec.chunk.chunk_type,
            ec.chunk.source_section,
            ec.chunk.chunk_text,
            ec.chunk.chunk_hash,
            json.dumps(asdict(ec.chunk.full_document)),
            fmt_vector(ec.embedding),
            ec.chunk.source,
            json.dumps(ec.chunk.metadata),
            taxonomy_version,
            model_name,
            ec.chunk.chunk_index,
        )
        for ec in embedded
    ]

    # Snapshot row count before any attempt so retries after a partial timeout
    # don't double-count rows inserted by a previous attempt.
    async with pool.acquire() as conn:
        before = await conn.fetchval(
            "SELECT COUNT(*) FROM bias_embeddings WHERE taxonomy_version = $1",
            taxonomy_version,
        )

    for attempt in range(1, _UPSERT_RETRIES + 1):
        try:
            t0 = time.monotonic()
            print(f"indexer: upsert attempt {attempt}/{_UPSERT_RETRIES} ({len(rows)} rows)...")
            async with asyncio.timeout(_UPSERT_TIMEOUT):
                async with pool.acquire() as conn:
                    await conn.executemany(UPSERT_CHUNK, rows)
            elapsed = int((time.monotonic() - t0) * 1000)
            print(f"indexer: upsert done in {elapsed}ms")
            break
        except (asyncio.TimeoutError, Exception) as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            print(f"indexer: attempt {attempt} failed after {elapsed}ms — {type(exc).__name__}: {exc}")
            if attempt == _UPSERT_RETRIES:
                print(
                    "\nAll upsert attempts failed. Run the SQL fallback instead:\n"
                    "  python scripts/generate_seed_sql.py\n"
                    "Then paste artifacts/seed_embeddings.sql into the Supabase SQL editor."
                )
                raise
            print(f"indexer: retrying in 2s...")
            await asyncio.sleep(2)

    async with pool.acquire() as conn:
        after = await conn.fetchval(
            "SELECT COUNT(*) FROM bias_embeddings WHERE taxonomy_version = $1",
            taxonomy_version,
        )
    return int(after - before)


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
