# Phase 0 Research: CI Metrics Gate for Retrieval Quality

No `[NEEDS CLARIFICATION]` markers were left in Technical Context — the architecture decisions were already made and reviewed in `adr/004-ci-metrics-gate.md` before spec.md was written. This document records the remaining *implementation-level* decisions Phase 0 needs to settle before Phase 1 design, each with rationale and the alternative rejected.

## Decision: Tier 1 needs no network, no DB, no mocks

**Decision**: `pytest` (whole suite) runs with zero external dependencies on GitHub Actions.

**Rationale**: Verified directly — `grep -rl "asyncpg\|DATABASE_URL\|create_pool" tests/` returns nothing, and there is no `conftest.py` anywhere in the repo. The 10 existing test files (`test_evaluate.py`, `test_retrieve_endpoint.py`, `test_llm_*.py`, etc.) are all either pure-function tests or use FastAPI's `TestClient` against an in-process app with dependencies overridden/mocked, not a live database. This confirms spec.md's SC-001 ("zero requiring a maintainer to manually trigger tests") and the ADR's "Tier 1 ... no network, no DB, no model download" claim are both accurate, not aspirational.

**Alternatives considered**: None needed — this was a factual check, not a design choice.

## Decision: `check_regression.py` is a new, dependency-free script, not a flag on `run_evaluation.py`

**Decision**: New file, `scripts/check_regression.py`, stdlib-only (`json`, `argparse`, `sys`, `dataclasses`), takes a run's `group_metrics` JSON + a baseline JSON as input (both already produced by `run_evaluation.py` / `evaluate.py`, no new producer needed) and exits non-zero with a human-readable breakdown when an eligible group regresses past tolerance.

**Rationale**: `scripts/run_evaluation.py` (and the `torch`/`asyncpg`/`llama-cpp-python`-dependent code it imports) exists to *produce* an evaluation run. The regression rule in ADR §4 is pure arithmetic over two already-produced JSON blobs — it has no reason to import torch. Keeping it a separate, dependency-free script means: (a) it's covered by Tier 1's fast/free pytest run, no eval infrastructure needed to test the *rule itself*; (b) Tier 2b (production drift monitor) can reuse it against a run fetched over HTTP from the deployed Space, without installing any ML dependency on that runner either — it only ever needs `httpx` + this script.

**Alternatives considered**: Adding `--check-baseline` flag to `run_evaluation.py` directly. Rejected — would force Tier 2b's HTTP-polling job to install the full ML stack just to run a comparison on JSON it already has, and would make the regression rule untestable without the eval infrastructure that Tier 1 deliberately avoids.

## Decision: test placement — new sibling file, not appended to `test_evaluate.py`

**Decision**: `tests/test_check_regression.py`, mirroring the existing 1:1 convention (`test_evaluate.py` ↔ `src/evaluation/evaluate.py`).

**Rationale**: `check_regression.py` is a distinct module from `evaluate.py` (different file, different dependency footprint, importable independently). `test_evaluate.py` already has 25 tests and a clear internal structure (recall/precision/MRR/nDCG/aggregation/deltas, each with its own `# ── section ──` comment block per the file's existing style); appending a sixth, unrelated concern (regression-tolerance/eligibility logic) to it would blur that structure rather than extend it.

**Alternatives considered**: Appending to `test_evaluate.py`. Rejected for the reason above — it's a readability/organization call, not a correctness one, but the existing file's own structure argues for a sibling file.

## Decision: Tier 2a installs `llama-cpp-python` via the prebuilt `vendor/wheels/*.whl`, not a from-source `uv sync`

**Decision**: The retrieval-gate workflow installs the committed wheel directly (`uv pip install vendor/wheels/llama_cpp_python-0.3.19-cp311-cp311-manylinux_2_34_x86_64.whl`) rather than letting a plain `uv sync` compile it from the `pyproject.toml` sdist pin.

**Rationale**: Both work — `.github/workflows/build-llama-wheel.yml`'s own comments establish that GitHub's `ubuntu-22.04` runners have ~16GB RAM, enough to compile `llama-cpp-python` from source without the OOM that forces the prebuilt-wheel workaround on HF's constrained Space build machine specifically (per that workflow's header comment, "compile succeeds here comfortably"). The prebuilt wheel is a pure speed optimization for *this* workflow: seconds to install vs. `pyproject.toml`'s own documented "~2m" local compile time, multiplied by every PR that touches retrieval-critical code. Using it also exercises the artifact `build-llama-wheel.yml` exists to produce, rather than leaving it unused by anything.

**Alternatives considered**: Plain `uv sync` (compile from source on every run). Rejected only on speed grounds, not correctness — noted here so a future maintainer knows the from-source path is a valid fallback if the committed wheel ever goes stale (e.g. a runner image glibc bump), not a hard dependency on the wheel existing.

## Decision: Tier 2a runs one evaluation per PR, against whichever strategy the PR's code defaults to — not all three strategies

**Decision**: One evaluation run per PR, using whatever `SELECTION_STRATEGY` the PR's own code resolves to by default (matching production, currently `llm_union` per `space-vars.env`) — not three separate `vector_only`/`nli_union`/`llm_union` runs. `adversarial`'s non-blocking status (ADR §4's eligibility rule) applies the same way regardless of which strategy produced the run.

**Rationale**: Spec.md's FR-003/FR-004 describe evaluating "a pull request's own code," singular — the eligibility/tolerance rule in ADR §4 already handles the one place (`adversarial`, currently) where a low-N/low-baseline group can't be meaningfully gated, regardless of which strategy produced it. Running all three strategies per PR would triple Tier 2a's runtime and DB load for a comparison spec.md never asked for; the spec's scope is "does *this PR's* retrieval quality regress," not "compare all three strategies against each other" (that comparison already exists, manually, in `evaluations/HISTORY.md`).

**Alternatives considered**: Running vector_only + nli_union + llm_union every time and gating on all three. Rejected as scope creep beyond what spec.md's user stories ask for — flagged here so it's a deliberate exclusion, not an oversight, and can be revisited if a future spec wants strategy-comparison in CI specifically.
