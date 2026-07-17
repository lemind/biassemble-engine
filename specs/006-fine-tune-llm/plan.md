# Implementation Plan: Fine-Tune the `llm_union` Cartridge

**Branch**: `006-fine-tune-llm` | **Date**: 2026-07-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/006-fine-tune-llm/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Close the gap between `llm_union`'s current `positive` Recall@5 (0.729, currently promoted baseline) and its target (0.85, ADR-003 §7 SC-001) by producing a LoRA-fine-tuned candidate GGUF and shipping it only if it clears the existing, already-built regression gate (specs/005-ci-metrics-gate). This is a data-and-training pipeline feature, not a service-code feature: it adds no new modules to `src/`, reuses the existing model-swap mechanism (`config.py`'s `llm_model_repo`/`llm_gguf_file`) unchanged, and reuses `scripts/check_regression.py`/`retrieval-gate.yml` unchanged. One small, necessary exception: `src/evaluation/evaluate.py`'s `_SKIP_GROUPS` gets one line added (`"sft"`) so the new training-data directory is never mistaken for a scenario group — see Project Structure below. What's new is (1) a held-out evaluation group promoted *before* any training data exists, (2) an SFT dataset assembled from 28 reconstructed real weak-supervision pairs plus ≥300 synthetic stories, both validated against the 38-id bias catalog and spot-checked, and (3) a LoRA training/quantization/manifest pipeline producing a candidate in the exact runtime format already deployed.

## Technical Context

**Language/Version**: Python 3.11 (matches `pyproject.toml` `requires-python = ">=3.11,<3.12"`) for all pipeline/dataset scripts. LoRA training itself runs on whatever free-tier notebook environment (Colab/Kaggle) is used to execute it — not this repo's own pinned interpreter, since it needs GPU access this repo's own runtime does not have.

**Primary Dependencies**: stdlib `json`/`argparse`/`dataclasses`/`hashlib` for the dataset-assembly and catalog-validation scripts (same dependency-free style as `scripts/check_regression.py`, since these are also pure data-shape checks, not ML calls). `psycopg`/`asyncpg` (already a project dependency, per `scripts/run_evaluation.py`'s `PSQL_SEARCH` path) for the weak-supervision-pair reconstruction script's read-only query against `biassemble-core`'s Supabase. LLM API clients (Gemini for labeling, plus whichever additional providers are used for generation — provider choice is an implementation detail, ADR-005 §2) for the generation/labeling scripts — these are one-off/manual-run scripts, not part of the deployed service, so they are **not** added to `pyproject.toml`'s main dependency set; they run in an ad hoc environment (notebook or a throwaway venv) documented in quickstart.md. LoRA/QLoRA tooling (`unsloth` or `peft`+`bitsandbytes`) and `llama.cpp`'s GGUF conversion tooling for the training/quantization step — same reasoning, not a `biassemble-engine` runtime dependency.

**Storage**: JSONL files for the SFT dataset and per-candidate manifests (no new database tables — this feature does not touch `biassemble-core`'s schema, only reads from it). New `evaluations/<group>/*.json` scenario files for the promoted held-out group, matching the existing per-scenario shape.

**Testing**: `pytest`, extending `tests/` with unit tests for the two genuinely deterministic, pure-function pieces of this feature: catalog-id validation (reject out-of-catalog `bias_ids`) and dataset coverage-checking (per-bias floor, negative fraction, group spread). Everything else in this feature — story generation, labeling, human spot-check, LoRA training — is non-deterministic, human-supervised, and/or compute-heavy, and is explicitly **not** made to fit a CI unit-test shape; it is validated by the existing eval gate (research.md's test-boundary decision) at the end, the same way spec-005 already validates any other change to retrieval quality.

**Target Platform**: Dataset-assembly and catalog-validation scripts run locally / in CI (Linux, matches this repo's existing tooling). LoRA training and GGUF conversion run on free-tier GPU notebook platforms (Colab/Kaggle T4-class) — external to this repo's own CI/runtime, per the free-tier constraint (ADR-002/003, restated in ADR-005 §5).

**Project Type**: Single project — this feature adds scripts and data files to the existing `biassemble-engine` repo; no new service, no new deployable unit. The eventual output (a GGUF file + two config values) plugs into the existing FastAPI service unchanged.

**Performance Goals**: Not applicable in the runtime sense — this is an offline training pipeline, not a request-serving path. The relevant constraint is fitting every step inside free-tier compute/storage quotas (ADR-005 §5), not latency or throughput.

**Constraints**: Free-tier-only compute (no paid GPU spend, per ADR-005 §8). Disk: peak usage during the merge/quantize step is additive, not just the largest single artifact — the downloaded HF base checkpoint (~7-8GB), the merged bf16 checkpoint (~7-8GB), and the GGUF conversion output (~2.5GB) can coexist on disk simultaneously, a plausible ~18GB peak against free-tier platforms that may only offer ~12-15GB (ADR-005 §5). Default to clearing the HF download cache *after* the merge completes (the merge itself needs the base checkpoint from that cache; clearing it earlier forces a mid-procedure re-download) and *before* quantization, and quantizing directly from the merged checkpoint without a separate full bf16 save — the correct order is train → merge → clear HF cache → quantize, treated as the default, not a contingency for only if space is tight. The training-dataset generation/labeling scripts depend on external LLM API keys (Gemini, plus whichever additional generation providers are chosen) that are not currently configured anywhere in this repo's secrets — provisioning them is a manual, human, out-of-band step this plan documents as a prerequisite but does not perform. **Newly confirmed while writing this plan**: the promoted held-out group's raw story text is not recoverable from anything committed to this repo — `evaluations/staging/blind_spot_eval_2026-07-13.json` is an eval-*results* file (scenario_id/domain/expected_bias_ids/retrieved_bias_ids/verdict) with no `story` field at all. The actual story text for all 80 scenarios exists only in 8 raw DeepSeek export files currently sitting untracked on local disk (`~/Downloads/deepseek_json_20260713_*.json`), verified joinable back to the results file by matching `(group, domain)` in list order (confirmed directly: index 0 of the `99e66a` batch is `neg_006`/astronomy, matching exactly). This is a real, load-bearing prerequisite for User Story 1 — see research.md and the new `reconstruct_blind_spot_stories.py` task.

**Scale/Scope**: ≥300 synthetic stories + 28 reconstructed weak-supervision pairs feeding one LoRA training run producing one candidate GGUF per attempt; the held-out evaluation group adds 80 scenarios (pending the raw-story reconstruction above) to the existing ~13-scenario harness.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unfilled template (`[PROJECT_NAME] Constitution`, all principle sections are literal placeholders) — this project has never ratified a constitution, same finding as specs/005-ci-metrics-gate's plan. There is nothing to gate against. No constitution gates apply to this or any other feature in this repo until one is written.

## Project Structure

### Documentation (this feature)

```text
specs/006-fine-tune-llm/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   ├── sft-dataset-schema.md
│   └── finetune-manifest-schema.md
└── tasks.md              # Phase 2 output (/speckit-tasks command — NOT created by /speckit-plan)
```

### Source Code (repository root)

This feature adds to the existing single-project layout — no new top-level directories for source code, no Option 2/3 structure. New files live in `scripts/` (flat, purpose-named, matching this repo's existing convention — `run_evaluation.py`, `check_regression.py`, `generate_story_patterns.py`, etc. all already live there, not in subpackages), plus one new top-level `training/` directory for the notebook-executed LoRA step (justified below):

```text
scripts/
├── run_evaluation.py                 # existing, unchanged
├── check_regression.py               # existing, unchanged — reused as-is to gate the candidate
├── generate_story_patterns.py        # existing, unchanged — same generation pattern this feature's
│                                      #   story generator follows, per ADR-005 §1(d)
├── reconstruct_weak_pairs.py         # NEW — joins biassemble-core's reasoning_traces.supporting_excerpts
│                                      #   to retrieval_comparisons.final_list via run_id (28 pairs, §1a)
├── reconstruct_blind_spot_stories.py # NEW — joins the 8 raw DeepSeek batch files (currently only on
│                                      #   local disk, not in this repo) back to
│                                      #   evaluations/staging/blind_spot_eval_2026-07-13.json by
│                                      #   (group, domain) order, producing real evaluations/<group>/*.json
│                                      #   scenario files with story text — see research.md
├── generate_sft_stories.py           # NEW — synthetic story generation across multiple providers
├── label_sft_stories.py              # NEW — labels generated stories with the teacher model, validates
│                                      #   every bias_id via validate_bias_catalog.py, rejects unknown ids
├── assemble_sft_dataset.py           # NEW — merges weak-supervision pairs + validated synthetic examples
│                                      #   into one JSONL, checks coverage (per-bias floor, negative
│                                      #   fraction, group spread) before declaring the dataset ready
└── validate_bias_catalog.py          # NEW — shared catalog-membership check, imported by
                                       #   label_sft_stories.py and assemble_sft_dataset.py (single
                                       #   source of truth for "what's a valid bias_id")

src/evaluation/
└── evaluate.py                       # ONE LINE CHANGED — "sft" added to _SKIP_GROUPS, so
                                       #   evaluations/sft/ is never walked by load_scenarios
                                       #   (confirmed necessary by reading the actual glob logic,
                                       #   not assumed — see research.md)

training/                             # NEW top-level dir — notebook-executed, not part of the
│                                      #   deployed service; kept separate from scripts/ because these
│                                      #   run on external GPU platforms, not this repo's own runtime
│                                      #   (justification in Structure Decision below)
├── lora_finetune.md                  # documented procedure (not a runnable script in this repo —
│                                      #   executed as a notebook on Colab/Kaggle), referencing the
│                                      #   exact base model, LoRA config, validation-split/checkpoint
│                                      #   rule, and merge/quantize steps from ADR-005 §5
└── manifests/                        # one JSON manifest per fine-tuned candidate produced (§9's
                                       #   record — dataset version, LoRA hyperparameters (incl.
                                       #   resolved target_modules), base model revision, quantization
                                       #   command, eval result), plus a sibling
                                       #   <candidate_id>_predictions.json per candidate archiving
                                       #   raw per-scenario outputs from its trial evaluation run —
                                       #   aggregate recall/precision alone can't answer "which
                                       #   specific stories changed" later (tasks.md)

evaluations/
├── blind_spot/                       # NEW — the promoted held-out group (was only results in
│                                      #   evaluations/staging/, never scored as a real group before
│                                      #   this feature). Every file's "group" key MUST read
│                                      #   "blind_spot" literally, NOT the batch's original
│                                      #   positive/negative/edge/adversarial label — verified
│                                      #   against src/evaluation/evaluate.py: load_scenarios groups
│                                      #   by that JSON field, not the directory name, so reusing the
│                                      #   original labels would silently merge into the 4 existing
│                                      #   groups instead of forming a distinct one (research.md)
│   └── *.json                        # 80 scenario files, real story text (see
│                                      #   reconstruct_blind_spot_stories.py above)
├── staging/                          # existing — blind_spot_eval_2026-07-13.json stays here as the
│                                      #   original results record, not deleted; evaluations/blind_spot/
│                                      #   is the promoted, story-bearing version actually used for scoring
├── sft/                              # NEW — sft_dataset.jsonl (assembled training data,
│                                      #   IMMUTABLE once its coverage_report.json shows "pass": true
│                                      #   — later expansions get a new versioned file, never an
│                                      #   in-place edit, tasks.md T017) and coverage_report.json
│                                      #   (per-bias counts, negative fraction, group/source counts,
│                                      #   pass/fail — a required output file, not console-only);
│                                      #   deliberately NOT under
│                                      #   evaluations/{positive,negative,edge,adversarial,blind_spot}/
│                                      #   since it is training data, never scenario data. NOTE, checked
│                                      #   directly against src/evaluation/evaluate.py: `_SKIP_GROUPS` does
│                                      #   NOT yet include "sft", and `load_scenarios` globs `group_dir.glob
│                                      #   ("*.json")` — so a stray `.json` file placed in evaluations/sft/
│                                      #   (a coverage report, a manifest copy) WOULD be picked up as a
│                                      #   scenario and crash on missing scenario_id/story fields, the exact
│                                      #   class of bug the "staging" fix in spec-005 already hit once. Adding
│                                      #   "sft" to `_SKIP_GROUPS` is therefore a required one-line change in
│                                      #   this feature's own task list, not an already-existing protection —
│                                      #   see tasks.md

tests/
├── test_evaluate.py                  # existing, unchanged
├── test_check_regression.py          # existing, unchanged — reused as-is
├── test_validate_bias_catalog.py     # NEW — unit tests for catalog-membership validation
└── test_assemble_sft_dataset.py      # NEW — unit tests for coverage-checking logic (per-bias floor,
                                       #   negative fraction, group spread), same deterministic style
                                       #   as test_check_regression.py
```

**Structure Decision**: Single project (Option 1), consistent with the rest of `biassemble-engine`. New pipeline scripts are flat files in `scripts/`, matching this repo's existing convention (no new Python package/subdirectory under `scripts/`). One new top-level `training/` directory holds the LoRA procedure and per-candidate manifests specifically because that step runs outside this repo's own Python environment (external GPU notebook, no `pyproject.toml` dependency, no CI execution) — a real enough distinction from every other file in `scripts/` (which all run in this repo's own `uv`-managed environment) to justify a separate top-level directory rather than forcing a notebook procedure into a directory of runnable scripts. `evaluations/sft/` is deliberately a sibling of, not nested inside, the scenario-group directories — but sibling placement alone does not exclude it from `src/evaluation/evaluate.py`'s group-discovery mechanism (confirmed by reading `load_scenarios`: it walks every subdirectory of `evaluations/` not in `_SKIP_GROUPS`, and `"sft"` is not currently in that set). Adding `"sft"` to `_SKIP_GROUPS` is therefore an explicit, required task, not a side effect of directory placement — see research.md and tasks.md. Two catalog/coverage-checking functions are unit-testable and get `tests/test_*.py` siblings, following the precedent `scripts/check_regression.py` already set in specs/005-ci-metrics-gate.

## Complexity Tracking

*No constitution gates exist to violate (see Constitution Check above) — this section intentionally left empty.*
