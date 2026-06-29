from sentence_transformers import SentenceTransformer

from src.providers.base import EmbeddingProvider


class SentenceTransformerProvider(EmbeddingProvider):
    def __init__(self, model_name: str) -> None:
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    def embed_query(self, text: str) -> list[float]:
        embedding = self._model.encode(text, convert_to_numpy=True)
        return embedding.tolist()  # type: ignore[union-attr]

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise RuntimeError(f"Model {self._model_name!r} did not report embedding dimension")
        return dim
