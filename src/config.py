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
    log_level: str = "INFO"
    psql_search: bool = False
    engine_url: str | None = None


settings = Settings()
