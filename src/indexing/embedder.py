from dataclasses import dataclass

from src.indexing.chunk_builder import BiasChunk
from src.providers.base import EmbeddingProvider


@dataclass
class EmbeddedChunk:
    """A BiasChunk paired with its embedding vector, ready for DB insertion."""

    chunk: BiasChunk
    embedding: list[float]


def embed_chunks(
    chunks: list[BiasChunk],
    provider: EmbeddingProvider,
    batch_size: int,
) -> list[EmbeddedChunk]:
    """Embed all chunks in batches, returning each chunk paired with its vector.

    Batching keeps memory usage bounded — the model processes `batch_size` texts
    at a time rather than the entire corpus at once.
    """
    results: list[EmbeddedChunk] = []

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.chunk_text for c in batch]
        vectors = provider.embed_texts(texts)
        for chunk, vector in zip(batch, vectors):
            results.append(EmbeddedChunk(chunk=chunk, embedding=vector))

    print(f"embedder: {len(results)} chunks embedded with {provider.model_name}")
    return results
