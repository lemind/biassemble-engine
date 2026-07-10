from dataclasses import dataclass

CHUNK_TYPE_DEFINITION = "semantic_definition"
CHUNK_TYPE_EXAMPLE = "semantic_example"
CHUNK_TYPE_INDICATOR = "semantic_indicator"
CHUNK_TYPE_FALSE_POSITIVE = "semantic_false_positive"
CHUNK_TYPE_RELATED = "semantic_related"
CHUNK_TYPE_STORY_PATTERN = "semantic_story_pattern"


@dataclass
class FullBiasDocument:
    name: str
    definition: str
    examples: str
    indicators: str
    false_positives: str
    related_biases: str


@dataclass
class CandidateChunk:
    bias_id: str
    chunk_type: str
    source_section: str
    source: str
    chunk_text: str
    full_document: FullBiasDocument
    retrieval_score: float


@dataclass
class RetrievedBias:
    bias_id: str
    name: str
    retrieval_score: float
    sources: list[str]
    matched_chunk_type: str
    matched_text: str
    definition: str
    examples: str
    indicators: str
    false_positives: str
    related_biases: str


@dataclass
class RetrievalMetadata:
    retrieval_id: str
    embedding_model: str
    taxonomy_version: str
    query_strategy: str
    query_length: int
    embedding_latency_ms: int
    search_latency_ms: int
    rerank_latency_ms: int
    total_latency_ms: int
    candidate_chunks: int
    surviving_chunks: int
    returned_biases: int
    top_retrieval_score: float | None
    avg_retrieval_score: float | None
    threshold_used: float
    # NLI fields — None for vector_only strategy
    selection_strategy: str | None = None
    hypotheses_version: str | None = None
    nli_latency_ms: float | None = None
    truncated_premise: bool | None = None
    nli_scores: dict[str, float] | None = None
    vector_scores: dict[str, float] | None = None
    combined_scores: dict[str, float] | None = None
