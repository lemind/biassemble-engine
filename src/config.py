from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    rag_api_key: str
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    taxonomy_version: str = "2026-06-28"
    search_top_k: int = 20
    return_top_k: int = 5
    similarity_threshold: float = 0.45
    query_strategy: str = "repeated_story"
    rerank_strategy: str = "max"
    index_batch_size: int = 32
    request_timeout_ms: int = 450
    evaluate_timeout_s: int = 1800
    log_level: str = "INFO"
    psql_search: bool = False
    engine_url: str | None = None

    selection_strategy: str = "vector_only"
    nli_model: str = "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
    w_nli: float = 0.7
    w_vec: float = 0.3
    nli_gate: float = 0.80
    vec_gate: float = 0.35
    combined_threshold: float = 0.60
    sentence_mode: bool = False
    hypotheses_path: str = "hypotheses/v1.yaml"


settings = Settings()
