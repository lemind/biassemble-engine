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


class RetrieveResponse(BaseModel):
    biases: list[BiasResult]
    retrieved_chunks: int
    taxonomy_version: str
    embedding_model: str
    request_id: str
