from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_SELECTION_STRATEGIES = {"vector_only", "nli_union", "llm_union"}


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

    # spec-004 (ADR-003): generative LLM bias selection (SELECTION_STRATEGY=llm_union).
    # Not wired anywhere yet — declared here per task T002. The model is a candidate
    # cartridge pending the spike (T003); see specs/004-add-llm-model/research.md.
    llm_model_repo: str = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
    llm_gguf_file: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    llm_context_tokens: int = 4096
    llm_max_output_tokens: int = 512
    llm_temperature: float = 0.0  # greedy → reproducible eval runs (FR-011)
    llm_threads: int = 2  # match cpu-basic vCPUs; override via LLM_THREADS env (e.g. 4 on cpu-upgrade)
    llm_log_raw: bool = False  # debug only — log raw model output (too large for prod)

    @field_validator("selection_strategy")
    @classmethod
    def _validate_selection_strategy(cls, v: str) -> str:
        if v not in VALID_SELECTION_STRATEGIES:
            raise ValueError(
                f"selection_strategy={v!r} is not one of {sorted(VALID_SELECTION_STRATEGIES)}"
            )
        return v


settings = Settings()
