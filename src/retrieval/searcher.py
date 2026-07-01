import asyncio
import csv
import io
import json
import re

import asyncpg

_SAFE_VERSION = re.compile(r"^[\w.\-]+$")

from src.config import settings
from src.db.queries import TABLE, fmt_vector
from src.schemas.internal import CandidateChunk, FullBiasDocument


def _row_to_candidate(row: asyncpg.Record) -> CandidateChunk:
    doc_data: dict = row["full_document"]
    full_doc = FullBiasDocument(
        name=doc_data["name"],
        definition=doc_data["definition"],
        examples=doc_data["examples"],
        indicators=doc_data["indicators"],
        false_positives=doc_data["false_positives"],
        related_biases=doc_data["related_biases"],
    )
    return CandidateChunk(
        bias_id=row["bias_id"],
        chunk_type=row["chunk_type"],
        source_section=row["source_section"],
        source=row["source"],
        chunk_text=row["chunk_text"],
        full_document=full_doc,
        retrieval_score=float(row["retrieval_score"]),
    )


def _row_to_candidate_csv(row: dict) -> CandidateChunk:
    doc_data = json.loads(row["full_document"])
    full_doc = FullBiasDocument(
        name=doc_data["name"],
        definition=doc_data["definition"],
        examples=doc_data["examples"],
        indicators=doc_data["indicators"],
        false_positives=doc_data["false_positives"],
        related_biases=doc_data["related_biases"],
    )
    return CandidateChunk(
        bias_id=row["bias_id"],
        chunk_type=row["chunk_type"],
        source_section=row["source_section"],
        source=row["source"],
        chunk_text=row["chunk_text"],
        full_document=full_doc,
        retrieval_score=float(row["retrieval_score"]),
    )


def _build_search_query(vec: str, taxonomy_version: str, top_k: int) -> str:
    if not _SAFE_VERSION.match(taxonomy_version):
        raise ValueError(f"unsafe taxonomy_version: {taxonomy_version!r}")
    # Vector is inlined as a literal — asyncpg's type introspection for the
    # 'vector' extension OID triggers a second DB round-trip that the proxy drops.
    # Inlining avoids parameterized vector types entirely.
    return (
        f"SELECT bias_id, chunk_type, source_section, source, chunk_text, full_document,"
        f" 1 - (embedding <=> '{vec}'::vector) AS retrieval_score"
        f" FROM {TABLE}"
        f" WHERE taxonomy_version = '{taxonomy_version}'"
        f" ORDER BY embedding <=> '{vec}'::vector"
        f" LIMIT {top_k};"
    )


async def _search_psql(embedding: list[float], taxonomy_version: str, top_k: int) -> list[CandidateChunk]:
    """Run vector search via asyncio psql subprocess (CSV output).

    Used when PSQL_SEARCH=true — works around asyncpg's vector type introspection
    hanging through a SOCKS proxy. psql uses libpq text protocol with no OID
    introspection. asyncio.create_subprocess_exec avoids thread-pool issues with
    blocking subprocess.run inside run_in_executor.
    """
    vec = fmt_vector(embedding)
    sql = _build_search_query(vec, taxonomy_version, top_k)
    proc = await asyncio.create_subprocess_exec(
        "psql", settings.database_url, "--no-psqlrc", "--csv", "-c", sql,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("psql search timed out after 30s")
    if proc.returncode != 0:
        raise RuntimeError(f"psql search failed: {stderr.decode().strip()}")
    rows = list(csv.DictReader(io.StringIO(stdout.decode())))
    return [_row_to_candidate_csv(r) for r in rows]


async def _search_asyncpg(
    embedding: list[float],
    pool: asyncpg.Pool | None,
    taxonomy_version: str,
    top_k: int,
) -> list[CandidateChunk]:
    assert pool is not None, "pool must not be None when psql_search=False"
    vec = fmt_vector(embedding)
    query = _build_search_query(vec, taxonomy_version, top_k)
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return [_row_to_candidate(r) for r in rows]


async def search_chunks(
    embedding: list[float],
    pool: asyncpg.Pool | None,
    taxonomy_version: str,
    top_k: int,
) -> list[CandidateChunk]:
    """Run a cosine similarity search against the bias_embeddings table.

    Returns up to top_k CandidateChunks ordered by retrieval_score descending.
    Uses psql subprocess when settings.psql_search=True (local dev with SOCKS proxy),
    asyncpg otherwise (production).
    """
    if settings.psql_search:
        return await _search_psql(embedding, taxonomy_version, top_k)
    return await _search_asyncpg(embedding, pool, taxonomy_version, top_k)
