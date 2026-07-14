# Implementation Plan: CI Metrics Gate for Retrieval Quality

**Branch**: `004-metrics-gate` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/005-ci-metrics-gate/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Close the gap between "the eval harness computes real quality metrics" and "nothing ever checks them automatically." Three GitHub Actions workflows, one new script, and zero changes to the existing evaluation logic: (1) run the existing `pytest` suite on every push/PR — today nothing does; (2) on PRs touching retrieval-critical code, run the real evaluation against the PR's own code over live Supabase and block merge on a per-group regression vs. the last promoted baseline, using the exact tolerance/eligibility formula worked out in `adr/004-ci-metrics-gate.md` §4; (3) run the same comparison weekly against the deployed HF Space as a non-blocking drift monitor. The regression-comparison logic itself lives in one new pure-Python script (`scripts/check_regression.py`) shared by tiers 2 and 3, so the rule is defined once.

## Technical Context

**Language/Version**: Python 3.11 (matches `pyproject.toml` `requires-python = ">=3.11,<3.12"`)

**Primary Dependencies**: None new for the regression-checker itself — stdlib `json` + `argparse` only (no torch/sentence-transformers/asyncpg, deliberately, per spec.md's Key Entities: it consumes JSON another process already produced). The two eval-running workflows (tiers 2 and 3) depend on what `scripts/run_evaluation.py` / the deployed API already depend on — nothing new there either.

**Storage**: N/A for the new script (reads/writes JSON files and stdin/args only). No schema or database changes anywhere in this feature.

**Testing**: `pytest`, in a new `tests/test_check_regression.py` (decided in Phase 0 research — see research.md's test-placement decision) covering the tolerance/eligibility logic — same free/deterministic style as the 25 existing metric-function tests in `tests/test_evaluate.py`, so it's covered by Tier 1 itself.

**Target Platform**: GitHub Actions (`ubuntu-22.04` runners — matches the glibc constraint already established in `.github/workflows/build-llama-wheel.yml` for `vendor/wheels/llama_cpp_python-*.whl` compatibility).

**Project Type**: Single project — this feature adds CI/CD workflow files plus one new script to an existing FastAPI microservice repo; no new services, no new deployable unit.

**Performance Goals**: Not applicable in the traditional sense — this is a CI gate, not a runtime feature. The relevant constraint is CI turnaround: Tier 1 should finish in well under a minute (no network); Tier 2a is bounded by the existing eval harness's own runtime (already measured — see `evaluations/HISTORY.md`'s live-server timings, ~3-4 min for 13 scenarios including LLM generation).

**Constraints**: Tier 2a and 2b cannot run at all until `DATABASE_URL`, `RAG_API_KEY`, the HF Bearer token, and `ENGINE_URL` exist as GitHub Actions secrets/variables in this repo (per ADR §5 — none exist today). This plan produces the workflow files that consume them; provisioning the secrets themselves is a manual, human, out-of-band step this plan cannot do and does not attempt to do.

**Scale/Scope**: Four scenario groups, 2–5 scenarios each today (13 total) — the regression-checker's tolerance/eligibility formula is designed to keep working as those numbers grow (per ADR §4/§9), not re-tuned per group size.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unfilled template (`[PROJECT_NAME] Constitution`, all principle sections are literal placeholders) — this project has never ratified a constitution. There is nothing to gate against. Noting this explicitly rather than silently skipping the section: **no constitution gates apply to this or any other feature in this repo until one is written** (`/speckit-constitution` would be the way to fix that, but it's out of scope for this feature).

## Project Structure

### Documentation (this feature)

```text
specs/005-ci-metrics-gate/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   └── check-regression-cli.md
└── tasks.md              # Phase 2 output (/speckit-tasks command — NOT created by /speckit-plan)
```

### Source Code (repository root)

This feature adds to the existing single-project layout — no new top-level directories, no Option 2/3 structure:

```text
.github/workflows/
├── build-llama-wheel.yml       # existing, unchanged
├── pytest.yml                  # NEW — Tier 1
├── retrieval-gate.yml          # NEW — Tier 2a
└── production-drift.yml        # NEW — Tier 2b

scripts/
├── run_evaluation.py           # existing, unchanged — Tier 2a/2b's evaluation runner
└── check_regression.py         # NEW — shared regression/eligibility checker (stdlib only)

src/evaluation/
└── evaluate.py                 # existing, unchanged — GroupMetrics/compute_deltas already produce
                                 #   exactly the shape check_regression.py consumes

tests/
├── test_evaluate.py            # existing, unchanged
└── test_check_regression.py    # NEW — unit tests for check_regression.py's tolerance/eligibility logic

evaluations/baselines/          # existing, unchanged — check_regression.py reads baseline_*.json,
                                 #   does not write to this directory (promotion stays manual per FR-013)
```

**Structure Decision**: Single project (Option 1), consistent with the rest of `biassemble-engine`. Nothing here justifies a new project boundary — `check_regression.py` is a script next to the existing `scripts/run_evaluation.py`, not a new package, matching this repo's existing convention of flat, purpose-named scripts (`sync_space_vars.py`, `tune_threshold.py`, etc.).

## Complexity Tracking

*No constitution gates exist to violate (see Constitution Check above) — this section intentionally left empty.*
