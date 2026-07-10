import structlog
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

log = structlog.get_logger()


class LLMGenerator:
    """Wraps llama-cpp-python for the spec-004 generative bias-selection strategy.

    Loads the GGUF once at construction (mirrors NLIClassifier's one-time model load).
    Raises on load failure — the caller (app startup) treats that as fatal, same as
    the NLI branch (FR-007).

    DEVIATION from tasks.md T005's literal `generate(prompt) -> str`: the spike
    (T003/T004, see research.md "Spike result") proved Qwen2.5-Instruct is an
    *instruct* model — raw text completion produced garbage; it requires the chat
    template. `generate()` therefore takes (system, user) and calls
    `create_chat_completion`, not a raw prompt string.
    """

    def __init__(
        self,
        model_repo: str,
        gguf_file: str,
        context_tokens: int,
        threads: int,
        max_output_tokens: int,
        temperature: float,
    ) -> None:
        self.context_tokens = context_tokens
        self.max_output_tokens = max_output_tokens
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        try:
            model_path = hf_hub_download(repo_id=model_repo, filename=gguf_file)
            self._llm = Llama(
                model_path=model_path,
                n_ctx=context_tokens,
                n_threads=threads,
                verbose=False,
            )
        except Exception as exc:
            raise RuntimeError(f"LLM model load failed — aborting startup: {exc}") from exc

    def generate(self, system: str, user: str) -> str:
        """Run one chat-completion turn. Raises on inference failure — the caller
        (llm_union's executor dispatch) is responsible for catching and degrading."""
        out = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=self._max_output_tokens,
            temperature=self._temperature,
        )
        return out["choices"][0]["message"]["content"] or ""

    def count_tokens(self, text: str) -> int:
        return len(self._llm.tokenize(text.encode("utf-8"), add_bos=False))

    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        tokens = self._llm.tokenize(text.encode("utf-8"), add_bos=False)
        if len(tokens) <= max_tokens:
            return text
        return self._llm.detokenize(tokens[:max_tokens]).decode("utf-8", errors="ignore")
