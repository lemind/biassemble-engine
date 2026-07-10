from typing import Literal

from pydantic import BaseModel


class BiasResult(BaseModel):
    id: str
    name: str
    retrieval_score: float
    definition: str
    examples: str
    indicators: str
    false_positives: str
    related_biases: str
    source: Literal["vector", "llm", "both"] | None = None


class RetrieveResponse(BaseModel):
    biases: list[BiasResult]
    retrieved_chunks: int
    taxonomy_version: str
    embedding_model: str
    request_id: str
    # llm_union-only additive fields (contract v3) — absent/None for vector_only/nli_union.
    llm_model: str | None = None
    llm_latency_ms: float | None = None
    truncated_story: bool | None = None
    llm_scores: dict[str, float] | None = None
    vector_scores: dict[str, float] | None = None
