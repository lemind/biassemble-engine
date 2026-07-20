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
# blind_spot (spec-006/ADR-006's primary ship-gate group, promoted 2026-07-17) was
# missing here until 2026-07-19 — the deployed Space's own /evaluate endpoint had no
# scenario files to score it with, so neither a live remote eval nor
# production-drift.yml could ever see it, independent of any baseline/branch state.
COPY evaluations/blind_spot ./evaluations/blind_spot

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
# HACK(hf-spaces-build-secrets): OBSERVED 2026-07-19 — build failed with a 401 the moment
# space-vars.env's LLM_MODEL_REPO became a private repo (Leminds/gemma3-4b-bias-lora-candidate-*,
# spec-006/ADR-005). HF Spaces passes Space "Variables" through as Docker build-args (which is
# why LLM_MODEL_REPO above resolves to the private repo at all) but Secrets (HF_TOKEN) are
# injected ONLY into the running container, never into the build — this RUN had no credential
# to present to a private repo. Bake is disabled; src/llm/generator.py:47 already downloads the
# GGUF at runtime startup, where HF_TOKEN *is* available, at the cost of a slower cold start.
# See adr/005-fine-tune-engine-llm.md.
# REVISIT: re-enable this RUN if LLM_MODEL_REPO ever reverts to a public repo, or if HF Spaces
# adds build-time secret injection for Docker Spaces.
# RUN uv run python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='${LLM_MODEL_REPO}', filename='${LLM_GGUF_FILE}')"

# Fallback defaults ONLY — for a non-Space docker run (local/CI) with nothing else
# set. On the actual deployed HF Space, these two ALWAYS lose to the Space's
# "Variables" (Docker -e beats a baked-in ENV) — the real, authoritative values live
# in space-vars.env (git-tracked) and are pushed with `uv run scripts/sync_space_vars.py`.
# Keep these two in sync with space-vars.env by hand; they're a safety net, not the
# source of truth. (SELECTION_STRATEGY=vector_only's 450ms default 503s every
# request under llm_union — that's why these exist at all.)
ENV SELECTION_STRATEGY=llm_union
ENV REQUEST_TIMEOUT_MS=120000

RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

ENV PYTHONPATH=/app

EXPOSE 7860
CMD ["sh", "-c", "uv run uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
