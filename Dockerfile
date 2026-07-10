FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Build tools for compiling llama-cpp-python from source (spec-004): the only prebuilt
# linux wheel is musl-linked and won't load on this glibc image, and PyPI ships sdist
# only — so it must compile. cmake + a C/C++ toolchain are required at install time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

# Install deps first — this layer is cached until pyproject.toml or uv.lock changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source after deps — only invalidates cache when source changes
COPY src/ ./src/
COPY hypotheses/ ./hypotheses/
COPY evaluations/positive ./evaluations/positive
COPY evaluations/negative ./evaluations/negative
COPY evaluations/adversarial ./evaluations/adversarial
COPY evaluations/edge ./evaluations/edge

# Bake NLI model into image — prevents runtime download timeout on cold start.
# ENV keeps build-time ARG and runtime default in sync; HF Space env var overrides both.
ARG NLI_MODEL=MoritzLaurer/deberta-v3-base-zeroshot-v2.0
ENV NLI_MODEL=${NLI_MODEL}
RUN uv run python -c "from transformers import pipeline; pipeline('zero-shot-classification', model='${NLI_MODEL}')"

RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

ENV PYTHONPATH=/app

EXPOSE 7860
CMD ["sh", "-c", "uv run uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
