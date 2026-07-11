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
    # Which methods surfaced this bias, e.g. ["vector"], ["llm"], ["vector","llm"].
    # None/absent for vector_only/nli_union (back-compat). Array, not a "both" string,
    # so a consumer sees each contributing signal.
    source: list[Literal["vector", "llm"]] | None = None


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
