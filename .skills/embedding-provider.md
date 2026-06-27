# Skill: EmbeddingProvider

## Pattern

Mirrors `biassemble-core`'s `LLMProvider` / `GeminiProvider`. Swap implementations without touching retrieval.

## Interface

```python
from abc import ABC, abstractmethod

class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch embed — for indexing."""
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Single embed — for retrieval."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...
```

## SentenceTransformerProvider

- Only implementation in v1
- Load model **once at construction** — never reload per request
- Located at `src/providers/sentence_transformer.py`
- Default model: `all-MiniLM-L6-v2` (384 dimensions)

## Rules

- `embedder.py` accepts `EmbeddingProvider` — never imports `sentence_transformers` directly
- Model is injected, not instantiated inside `embedder.py`
- To swap model: implement new `EmbeddingProvider`, change `EMBEDDING_MODEL` config

## Future Providers (out of scope for v1)

BGE, E5, OpenAI, Voyage AI — all fit the same interface without changing retrieval logic.
