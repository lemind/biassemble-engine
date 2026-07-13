FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Shared HF cache under /app so a model baked at build time (as root) is found at
# runtime (as appuser) — /app is chowned to appuser below. Without this, downloads
# land in /root/.cache at build but appuser looks in /home/appuser/.cache → cache
# miss → the "bake" re-downloads at startup, defeating its purpose.
ENV HF_HOME=/app/.cache/huggingface

# No C/C++ build tools needed: llama-cpp-python is installed from a prebuilt manylinux
# wheel vendored in vendor/wheels/ (built once in GitHub Actions — see uv.lock's path
# source + .github/workflows/build-llama-wheel.yml). Compiling it here from source
# OOM-killed HF's build machine (40+ min, never completed); the wheel installs in
# seconds. Copy the wheel BEFORE uv sync so the lock's path source resolves.
COPY vendor/wheels/ ./vendor/wheels/

# Install deps first — this layer is cached until pyproject.toml / uv.lock / the wheel changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source after deps — only invalidates cache when source changes
COPY src/ ./src/
COPY hypotheses/ ./hypotheses/
COPY evaluations/positive ./evaluations/positive
COPY evaluations/negative ./evaluations/negative
COPY evaluations/adversarial ./evaluations/adversarial
COPY evaluations/edge ./evaluations/edge

# NLI (nli_union) is no longer the default strategy — llm_union (Gemma) is. Its model
# is kept selectable via NLI_MODEL, but NOT pre-baked (saves ~700MB). If you switch the
# Space back to SELECTION_STRATEGY=nli_union, uncomment the bake below to avoid a
# cold-start download timeout.
ARG NLI_MODEL=MoritzLaurer/deberta-v3-base-zeroshot-v2.0
ENV NLI_MODEL=${NLI_MODEL}
# RUN uv run python -c "from transformers import pipeline; pipeline('zero-shot-classification', model='${NLI_MODEL}')"

# Bake the generative LLM (Gemma-3-4B GGUF) into the image — same reason the NLI bake
# existed: prevents a ~2.5GB runtime download on cold start (app.py's model load is
# fatal-on-fail, so a download timeout would abort startup). ENV keeps the build-time
# download target and the runtime default in sync; Space env vars override.
ARG LLM_MODEL_REPO=bartowski/google_gemma-3-4b-it-GGUF
ARG LLM_GGUF_FILE=google_gemma-3-4b-it-Q4_K_M.gguf
ENV LLM_MODEL_REPO=${LLM_MODEL_REPO}
ENV LLM_GGUF_FILE=${LLM_GGUF_FILE}
RUN uv run python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='${LLM_MODEL_REPO}', filename='${LLM_GGUF_FILE}')"

# Deploy defaults: llm_union, with a request timeout large enough for CPU LLM inference.
# The LLM takes seconds — the old 450ms default would 503 every request. Space env
# vars override these.
ENV SELECTION_STRATEGY=llm_union
ENV REQUEST_TIMEOUT_MS=120000

RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

ENV PYTHONPATH=/app

EXPOSE 7860
CMD ["sh", "-c", "uv run uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
