import json

import asyncpg

from src.db.queries import SEARCH_CHUNKS
from src.schemas.internal import CandidateChunk, FullBiasDocument


def _fmt_vector(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


def _row_to_candidate(row: asyncpg.Record) -> CandidateChunk:
    # full_document is stored as JSONB; asyncpg returns it as a JSON string.
    doc_data = json.loads(row["full_document"]) if isinstance(row["full_document"], str) else row["full_document"]
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


async def search_chunks(
    embedding: list[float],
    pool: asyncpg.Pool,
    taxonomy_version: str,
    top_k: int,
) -> list[CandidateChunk]:
    """Run a cosine similarity search against the bias_embeddings table.

    Returns up to top_k CandidateChunks ordered by retrieval_score descending.
    The <=> operator in pgvector returns cosine distance (0=identical, 2=opposite),
    so retrieval_score = 1 - distance maps it back to a similarity in [-1, 1].
    """
    vector_str = _fmt_vector(embedding)
    async with pool.acquire() as conn:
        rows = await conn.fetch(SEARCH_CHUNKS, vector_str, taxonomy_version, top_k)
    return [_row_to_candidate(r) for r in rows]
