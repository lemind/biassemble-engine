---

description: "Task list for Fine-Tune the llm_union Cartridge"
---

# Tasks: Fine-Tune the `llm_union` Cartridge

**Input**: Design documents from `specs/006-fine-tune-llm/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/sft-dataset-schema.md](./contracts/sft-dataset-schema.md), [contracts/finetune-manifest-schema.md](./contracts/finetune-manifest-schema.md), [quickstart.md](./quickstart.md) — all written and reviewed across two rounds this session: `/code-review high --domain llm` (10 findings, applied) and a manual human review (12 points, applied — including one deeper bug this task list's own review surfaced: an earlier draft would have silently merged the held-out group into the four existing scenario groups instead of scoring it separately). The documents linked above are the corrected, current versions — this task list reflects them, it does not re-derive or re-litigate them.

**Tests**: Included for the two genuinely CI-testable, deterministic pieces of this feature only (research.md's test-boundary decision) — catalog-membership validation and dataset coverage-checking. Story generation, labeling, human spot-check, and LoRA training are explicitly **not** unit-tested; they're validated by the existing, unmodified eval gate (`scripts/check_regression.py`) at the end, the same tool spec-005 already built for exactly this purpose.

**Organization**: Tasks are grouped by user story (spec.md: US1/US2 = P1, US3/US4 = P2) so each is independently completable and testable, per this repo's MVP-per-story convention.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1/US2/US3/US4)

## Path Conventions

Single project (per plan.md's Structure Decision) — `scripts/`, `tests/`, `evaluations/`, and one new top-level `training/` directory, all at repository root. One existing file gets a one-line change (`src/evaluation/evaluate.py`); no other `src/` changes.

---

## Phase 1: Setup

**Purpose**: Surface the one thing no task in this list can actually "complete" by writing code, and lock down the one precondition already verified this session so it isn't silently re-assumed later.

- [ ] T001 [P] Document required external credentials (a Gemini API key for synthetic labeling, plus whichever additional LLM provider keys are chosen for genuinely-different-provider story generation — ADR-005 §2/§5 deliberately does not lock in which providers) as a blocking prerequisite for US2 (quickstart.md Steps 3+). None of these exist in this repo today. Mirror the pattern `specs/005-ci-metrics-gate`'s T001 used for `DATABASE_URL`/`RAG_API_KEY`: a documented table (name/purpose/blocks-what), not a task any code change can mark complete — provisioning is a human, out-of-band step.
- [x] T002 [P] Verified precondition for US1: all 8 raw DeepSeek export files referenced by `evaluations/staging/blind_spot_eval_2026-07-13.json`'s `source_file` values (`6a25e8`, `7da4ba`, `7e1b94`, `8c4f45`, `99e66a`, `ace574`, `bb12d7 (1)`, `c5c14a`) are present on disk (`~/Downloads/deepseek_json_20260713_*.json`) and join back to the results file cleanly by `(group, domain)` list order — confirmed directly during planning (2026-07-16): batch `99e66a`'s index 0 (`group: negative, domain: astronomy`) matches results-file row `neg_006`/astronomy exactly, and this held for every row spot-checked. **This precondition can go stale silently** (the files are local and untracked) — T006 below re-checks presence as its own first action, not as a footnote on this already-closed task, since an executor scanning for open work will not re-read a checked-off item.

---

## Phase 2: Foundational (blocks US2/US3/US4 — does **not** block US1)

**Purpose**: The one shared, genuinely reusable piece (catalog validation, used by both labeling and dataset assembly) plus the one-line fix that must land before anything writes to `evaluations/sft/`.

**⚠️ Scope note, deliberately narrower than the template default**: US1 (Phase 3) needs none of this — `reconstruct_blind_spot_stories.py` writes to `evaluations/blind_spot/`, not `evaluations/sft/`, and never touches the bias catalog. This phase only blocks US2 onward.

- [x] T003 [P] Implemented `scripts/validate_bias_catalog.py`: `_SingleConnPool` + `_load_valid_bias_ids_once()` (same one-off-connection pattern `scripts/run_evaluation.py`'s `_load_catalog_once()` already uses, deliberately duplicated rather than shared — matches this repo's flat, independent-scripts convention, not an oversight), `load_valid_bias_ids()` sync entrypoint via `asyncio.run()`, and `validate_row(bias_ids, valid_ids) -> bool` (all-or-nothing membership check, no coercion). Sources `taxonomy_version` from `src/config.py`'s existing `Settings`, never hardcoded. **Verified against the live DB, not just imported**: `uv run python scripts/validate_bias_catalog.py` returns exactly 38 bias_ids matching the known catalog.
- [x] T004 [P] `tests/test_validate_bias_catalog.py` — 5 tests, all passing, fixture-only (no live DB call in the test itself): valid ids pass, out-of-catalog id rejects the whole row, human-readable name (`"Anchoring Bias"`) rejected, empty `bias_ids` valid, single invalid id rejects. Written and confirmed failing (`ModuleNotFoundError`, no implementation existed yet) before T003 made it pass, per this phase's test-first requirement.
- [x] T005 [P] One-line change to `src/evaluation/evaluate.py`'s `_SKIP_GROUPS`: added `"sft"`. Confirmed no existing test asserts the exact `_SKIP_GROUPS` set (would have caught a break here). Full suite `uv run pytest tests/ -v` → 138 passed (133 pre-existing + 5 new), 0 failures.

**Checkpoint**: Catalog validation is correct and reusable in isolation; `evaluations/sft/` is now actually protected from accidental scenario-loading, not just conventionally separated.

---

## Phase 3: User Story 1 - A held-out check exists that can't be gamed by the training data itself (Priority: P1) 🎯 MVP

**Goal**: The blind-spot batch is promoted into a real, scored, protected evaluation group *before* any training data exists — spec.md's ordering requirement, load-bearing not incidental.

**Independent Test**: Promote the batch, confirm it reports real Recall@5/Precision@5 today, and confirm the "never a training-data source" rule is enforced by construction (no script in this feature reads `evaluations/blind_spot/`), not merely documented.

**Depends on**: T002 (Phase 1) for the raw-file precondition. Nothing else — this story ships independent of Phase 2.

### Implementation for User Story 1

- [ ] T006 [US1] **First action: re-verify T002's precondition still holds** (all 8 raw files still present in `~/Downloads`, still local/untracked) — do not assume it silently carried forward from Phase 1. Then implement `scripts/reconstruct_blind_spot_stories.py` per data-model.md's `BlindSpotScenario` and research.md's join decision: read `evaluations/staging/blind_spot_eval_2026-07-13.json`, join each row to the matching raw DeepSeek export file (`~/Downloads/deepseek_json_20260713_*.json`) by `(group, domain)` list order, write one `evaluations/blind_spot/<scenario_id>.json` per row matching the existing scenario-file shape exactly (same fields `evaluations/positive/*.json` already uses). **Critical, verified directly against `src/evaluation/evaluate.py`: every output file's `"group"` field must be overwritten to the literal string `"blind_spot"`, not left as the batch's original positive/negative/edge/adversarial label** — `load_scenarios` reads `group` from each file's own JSON key (not the directory name), and aggregation keys on that same field, so reusing the original labels would silently merge these 80 scenarios into the *existing* four groups' metrics instead of creating a separately-scored group at all. Preserve the original label in a separate `original_subgroup` field for reference (the harness ignores unrecognized keys). Must fail loudly (not silently skip) if any of the 8 source files are missing. Must flag `adv_005`'s `scarcity_bias` label (confirmed not in the catalog, per `blind_spot_eval_2026-07-13_SUMMARY.md`) for resolution rather than carrying it forward silently.
- [ ] T007 [US1] Run T006 against the real data (quickstart.md Step 2) — produce all 80 `evaluations/blind_spot/*.json` files. Resolve `adv_005`'s invalid label: **drop only the invalid `scarcity_bias` entry from that row's `expected_bias_ids` list, keep the row and its remaining valid label (`bandwagon_effect`)** — dropping the whole scenario shrinks `blind_spot`'s count for no reason when only one label needs removing, and (since T006 makes `blind_spot` one unified ~80-scenario group rather than four separately-counted subgroups) there is no eligibility cliff either way, but keeping the row preserves more signal.
- [ ] T008 [US1] Human spot-check a sample of the reconstructed `evaluations/blind_spot/*.json` files — confirm the joined `story` text actually matches its scenario's `domain`/`expected_bias_ids` (i.e. the join didn't silently misalign), mirroring the existing "staged, pending spot-check" discipline this repo already applies to the same batch.
- [ ] T009 [US1] `uv run python scripts/run_evaluation.py --strategy llm_union` (no `--groups` flag — **verified this flag does not exist on this script's local CLI**; `main_sync`'s local path calls `load_scenarios(eval_dir)` with no group filter at all, `--groups` is only a query parameter on the *deployed* `/evaluate` HTTP endpoint, a different code path). The plain command scores every non-skipped group, which now includes `blind_spot` automatically once T006's output exists with the correct `"group": "blind_spot"` field — confirm the printed output shows a `blind_spot` row with a real Recall@5/Precision@5 result, no new eval code path (spec.md FR-013's foundation).
- [ ] T010 [US1] **Re-promote a baseline that includes a `blind_spot` entry**, using the script's existing `--promote` flag: `uv run python scripts/run_evaluation.py --strategy llm_union --promote`. Per research.md's verified finding: `check_regression.py`'s `compute_findings()` iterates the *baseline's* groups, not the run's — promoting the scenario group (T007) does not by itself make `check_regression.py` ever compare against it. This is the same manual, human promotion step this repo already requires for any baseline (spec-005's FR-013 boundary), done here specifically to include `blind_spot`. **US4 (Phase 6) cannot satisfy FR-013 until this task is done.**

**Checkpoint**: US1 fully functional independently — the held-out group exists, is scored, is protected by construction (no script reads it as training input), and is gate-ready. This alone is the precondition every other story depends on for validity, even though only US4 has a *code* dependency on it.

---

## Phase 4: User Story 2 - A training dataset good enough to attempt a fine-tune exists (Priority: P1)

**Goal**: A validated, spot-checked, coverage-complete SFT dataset combining the 28 real weak-supervision pairs with enough synthetic stories (≥300 valid rows, ≥340 generated as headroom) to clear every coverage rule.

**Independent Test**: Per spec.md — `evaluations/sft/sft_dataset.jsonl` exists, spans all four scenario-group shapes, meets the per-bias floor and ≥20% negative fraction, every label validated against the live catalog, and a human-reviewed sample passed spot-check.

**Depends on**: Phase 2 (T003 catalog validator, T005 `_SKIP_GROUPS` fix) for the dataset-writing precondition. **Phase 3 (US1) must be complete first** — `evaluations/blind_spot/` must exist before generation starts so T012/T015 can diff against it for contamination avoidance (spec.md User Story 1, Edge Cases). T001's credentials block T012/T013/T015 specifically (generation/labeling), not T011 (DB-only) or T016 (pure data assembly).

### Implementation for User Story 2

- [ ] T011 [P] [US2] Implement `scripts/reconstruct_weak_pairs.py` per data-model.md's `WeakSupervisionPair`: join `biassemble-core`'s `reasoning_traces.trace -> bias_hypotheses[].supporting_excerpts` to `retrieval_comparisons.final_list` via `run_id`, output `source: "real_weak"` rows. **No new database credential needed** — verified directly: `biassemble-engine`'s own `DATABASE_URL` and `biassemble-core`'s point at the same Supabase project (same pooler host and project ref), so this script queries `biassemble-core`'s tables through the engine's already-configured connection. **Queries must be schema-qualified (`core.reasoning_traces`, `core.retrieval_comparisons`), not bare table names** — these tables live in that project's `core` schema, not `public` (Supabase's default `search_path`), and an unqualified query fails with "relation does not exist" despite the connection itself being entirely correct. Run it — expect 28 rows (ADR-005 §1a); if the count differs materially, re-verify against a fresh direct query before trusting the script, per the ADR's own "decays fast" warning.
- [ ] T012 [US2] Implement `scripts/generate_sft_stories.py` — genuinely different providers/model families (not merely different tiers of the same family — e.g. two tiers of the same model share too much stylistic DNA to count as diverse), spread across positive/negative/edge/adversarial shapes, negative examples prompted as mundane/low-narrative-tension content (spec.md FR-007) rather than "write a story with no bias." Must diff generated story premises/domains against `evaluations/{positive,negative,edge,adversarial}/*.json` **and** `evaluations/blind_spot/*.json` (from Phase 3) to avoid deliberate topical overlap. Record `generator_model` and `generation_prompt_version` per row (data-model.md's `SyntheticStoryRecord`) — not optional metadata, this is what makes "why do examples from generator X train better than generator Y" answerable later instead of guesswork. **No separate `--pilot` mode** — a pilot batch is just this same CLI called with a small `--count` (~40, quickstart.md Step 3); don't add a distinct code path for it, since T015's full-volume run and T012's pilot run are the same script with a different count.
- [ ] T013 [US2] Implement `scripts/label_sft_stories.py` — one consistent teacher model, output matching `src/llm/prompt.py`'s exact bare-JSON-array shape, every `bias_ids` entry validated via T003's `validate_bias_catalog.py` (reject the whole row on any invalid id). Record `teacher_model` and `label_prompt_version` per row alongside the label, same provenance reasoning as T012. Label the pilot batch.
- [ ] T014 [US2] Human spot-check the pilot batch (quickstart.md Step 4) — record pass/fail rate. If the failure rate is high, fix generation/labeling prompts and regenerate the pilot before scaling; do not partially salvage a high-failure batch (spec.md Edge Cases).
- [ ] T015 [US2] Scale generation+labeling toward full volume. **The actual requirement is ≥300 valid, catalog-passing rows plus every coverage rule in contracts/sft-dataset-schema.md met — the exact number generated is an implementation detail, not a fixed target.** Generate a batch (start around 340 for headroom, since T003's catalog validation rejects whole rows outright with no partial-row salvage), run T016's coverage check, and **top up generation for specifically under-covered bias ids or scenario groups rather than re-running the whole batch** — repeat until the coverage report passes, rather than generating one fixed-size batch and hoping it clears every rule. Existing hand-authored `positive`/`edge`/`adversarial` scenarios average ~3.0 labels/story (verified directly) — a useful reference point for whether generated stories are carrying enough multi-label density to clear the ≥15-per-bias floor without needing 570 single-label stories, but check the actual coverage report rather than assuming this density transfers to synthetic content.
- [ ] T016 [US2] Implement `scripts/assemble_sft_dataset.py` per contracts/sft-dataset-schema.md: merge T011's weak-supervision pairs + T015's validated synthetic examples into `evaluations/sft/sft_dataset.jsonl`, tagged `source: "synthetic"|"real_weak"`, carrying through each row's provenance fields (`generator_model`/`generation_prompt_version`/`teacher_model`/`label_prompt_version`, `null` for `real_weak` rows) — do not strip them during the merge. Enforce all six validation rules from the contract (catalog membership via T003, group coverage, ≥15-per-bias floor, ≥20% negative fraction, ≥300 synthetic-row volume, no `evaluations/blind_spot/` overlap — enforced by construction, this script never reads that directory). **CLI has two modes**: a `--coverage-report-only` flag that writes `evaluations/sft/coverage_report.json` and exits without touching `sft_dataset.jsonl` (used by T015's iterate-until-passing loop to check a candidate batch before committing to it), and the default mode (requires `--output`) that writes both `coverage_report.json` **and** `sft_dataset.jsonl` — but only if every rule passes; on failure in default mode, write the report only, never a partial/incomplete dataset file. `coverage_report.json` (data-model.md's `CoverageReport`: `dataset_version`, `total_rows`, `counts_by_source`, `counts_by_group`, `per_bias_counts`, `negative_fraction`, `pass`) is a required output file in both modes, not console-only logging, so later analysis or a failed-attempt diagnosis never has to recompute these numbers from the raw dataset.
- [ ] T017 [US2] **Freeze and version the assembled dataset.** Once T016's `coverage_report.json` reports `"pass": true`, compute a content hash of `evaluations/sft/sft_dataset.jsonl` and record it as `dataset_version` (already referenced by `coverage_report.json` and later by `training/manifests/*.json`). From this point, treat the file as **immutable** — do not edit it in place for any reason. A later expansion (more weak-supervision pairs surfacing, a second synthetic batch) must produce a new file (e.g. `sft_dataset_v2.jsonl`) with its own coverage report and hash, never an overwrite. Without this, two candidates' manifests could both cite "the same" file path while its actual content silently differed between their two training runs, making `dataset_version` meaningless.
- [ ] T018 [P] [US2] `tests/test_assemble_sft_dataset.py` — deterministic unit tests for T016's coverage-checking logic only (per-bias floor, negative-fraction, group-spread, volume-floor arithmetic), using fixture data, not a live dataset — same free/deterministic style as `tests/test_check_regression.py`.

**Checkpoint**: US2 fully functional independently of Phase 5/6 — a validated, spot-checked, contamination-checked, frozen SFT dataset exists and could in principle be handed to any LoRA process, including one outside this feature.

---

## Phase 5: User Story 3 - A fine-tuned candidate is produced with reproducible provenance (Priority: P2)

**Goal**: A LoRA-trained, merged, quantized candidate GGUF plus a complete manifest, produced entirely on free-tier compute.

**Independent Test**: Per spec.md — running the documented procedure against T017's frozen dataset produces a runtime-loadable GGUF and a manifest recording dataset version, training config, and base model revision.

**Depends on**: Phase 4 (US2 — needs `evaluations/sft/sft_dataset.jsonl` frozen and validated, T017). External to this repo's own tooling (Colab/Kaggle GPU).

### Implementation for User Story 3

- [ ] T019 [US3] Write `training/lora_finetune.md` — the documented procedure (not a runnable script in this repo). Must explicitly specify: **the base model this feature's governing ADR pins as currently deployed — as of this writing, exactly `google/gemma-3-4b-it`'s HF bf16 checkpoint (never the GGUF, never a different-sized variant — spec.md FR-009); if the deployed cartridge changes in a later ADR, re-derive this from that ADR rather than assuming this pin still applies**; a validation split (~10-15% default) held out from `evaluations/sft/sft_dataset.jsonl` itself with per-epoch validation-loss tracking and best-checkpoint (not final-epoch) selection; **and, called out explicitly per this session's review findings, three training-loop correctness requirements that fail silently if missed (spec.md FR-019/FR-020/FR-021)**: (1) apply the base model's chat template with loss masked to the completion only, (2) serialize the `bias_ids` target as a real JSON array string matching `src/llm/prompt.py`'s parser — not a Python list repr, (3) target both attention (`q_proj`/`k_proj`/`v_proj`/`o_proj`) and MLP (`gate_proj`/`up_proj`/`down_proj`) projections, verified against the base model's actual module names, not accepted as an unverified library default. Also document the disk-mitigation default with the **correct ordering**: train → merge (the merge step reads the base checkpoint from the HF cache, so it must still be present) → clear the HF download cache → quantize directly from the merged checkpoint without a separate full bf16 save. Clearing the cache *before* merging (an earlier draft said this) deletes an input the merge step needs and forces a mid-procedure re-download — the opposite of the intended space saving. Additive peak usage across base+merged+GGUF can plausibly hit ~18GB (ADR-005 §5).
- [ ] T020 [US3] Execute T019's procedure on a free-tier GPU notebook against T017's frozen dataset: train, select best checkpoint by validation loss, merge the adapter, quantize to Q4_K_M GGUF via `llama.cpp`'s conversion tooling. **Verify `target_modules` actually resolved against the base model's real module names** — print the adapter's trained parameter count and confirm both attention and MLP projections are represented; an empty or attention-only match means the adapter trained on close to zero effective parameters despite completing without error. **Then, before proceeding to evaluation, run inference on ~20 random training samples as a smoke test** — a chat-template mismatch, a tokenizer issue, or a serialization bug can make training "succeed" (loss decreases) while the resulting model's actual outputs are garbage; catching this here costs minutes, catching it only after T022's full evaluation costs a wasted eval cycle and a harder-to-diagnose failure.
- [ ] T021 [US3] Write `training/manifests/<candidate_id>.json` per contracts/finetune-manifest-schema.md: dataset version (T017's content hash) + composition, LoRA hyperparameters including the **resolved** `target_modules` list actually trained, base model revision, exact quantization command. Leave `eval_result` for T022/T023 to populate — it is a **JSON array** (`list[RegressionFinding]`, not an object) produced with `[dataclasses.asdict(f) for f in compute_findings(...)]`; `json.dumps` on the raw dataclass list raises `TypeError` without that conversion.

**Checkpoint**: A candidate GGUF and a complete, reproducible manifest exist — nothing about this candidate's provenance requires re-deriving from memory or Slack archaeology.

---

## Phase 6: User Story 4 - The candidate only ships if it clears the existing quality bar (Priority: P2)

**Goal**: The candidate is evaluated with the existing, unmodified regression tooling and only promoted if it clears the hard `positive` Recall@5 ≥ 0.85 bar without regressing anything else.

**Independent Test**: Per spec.md — point the existing eval tooling at the candidate, confirm it's scored against both the standard groups and `blind_spot`, and confirm it's blocked from shipping when it misses the bar.

**Depends on**: Phase 5 (US3 — candidate + manifest must exist). **Phase 3's T010 (baseline re-promoted with `blind_spot`)** — without it, this phase's evaluation silently omits `blind_spot` from the comparison rather than erroring (research.md, data-model.md's `ShipGateResult`).

### Implementation for User Story 4

- [ ] T022 [US4] `LLM_MODEL_REPO=<candidate> LLM_GGUF_FILE=<candidate-gguf> uv run python scripts/run_evaluation.py --strategy llm_union` (env override, not committed config, per ADR-005 §6) — produce a trial run against the candidate. **Archive the raw per-scenario outputs, not just the aggregate metrics** — write `training/manifests/<candidate_id>_predictions.json` (or equivalent) capturing each scenario's retrieved `bias_ids` alongside the candidate's run. Aggregate `recall_at_k`/`precision_at_k` alone can't answer "which specific stories changed" when comparing this candidate against the baseline or a different candidate later — story-by-story comparison needs both runs' raw outputs, and re-running evaluation later to get them back is wasted compute for data this step already produced once. Then `python scripts/check_regression.py --run <trial-run> --baseline <latest-baseline>` — same unmodified CLI as any PR.
- [ ] T023 [US4] Verify the ship gate from T022's output: `positive`'s `recall_at_k` finding `>= 0.85`; no other eligible group regressed past its own tolerance; `positive`'s `precision_at_k` did not drop in the same run (no recall/precision trade-off); **confirm a `blind_spot` row is actually present in the findings** before treating its absence as "no regression" — its absence means "not compared," not "passed." Populate T021's manifest `eval_result` with `[dataclasses.asdict(f) for f in compute_findings(...)]` (a JSON array, not an object — see T021).

  **If the bar isn't cleared, triage before restarting Phase 4 — don't default to "it's a data problem":**
  1. Check T020's training loss curve — if it never meaningfully decreased, suspect T020's `target_modules` resolution first (a silent near-zero-effective-parameters adapter is indistinguishable from "the model just didn't learn" without checking this).
  2. Check T020's inference smoke test — malformed JSON or a Python-repr-looking string instead of a clean JSON array points at T019's serialization requirement (FR-020) being missed in the training loop, not a data volume/coverage problem.
  3. **Check the manifest's `base_model_revision` against what was actually quantized and what the runtime actually loaded** — a mismatch (trained against one HF revision, quantized from a different local copy, or the runtime loading yet another cached revision) produces a candidate that doesn't reflect the training run at all, and the manifest already has the field needed to catch this; check it before blaming data.
  4. Only once training, serialization, and revision are all confirmed correct and the gap persists: **iterate on data (Phase 4)**, not on `check_regression.py`'s tolerances (ADR-005 §6 point 3 — a hard gate, not a judgment call). Re-running the entire generation/labeling/training cycle to fix what turns out to be a one-line training-config bug wastes a full cycle for nothing.
- [ ] T024 [US4] **First, before touching any config**: `grep -rn "HACK(" src/` and re-validate every hit against the fine-tuned candidate, per `CLAUDE.md`'s existing model-swap convention (spec.md FR-022) — delete anything whose `REVISIT` condition fired with no supporting evidence, don't assume workarounds written for the previous base GGUF still apply unchanged. **Then**, once that audit is clean and T023 passed: update `config.py`'s defaults or `space-vars.env`'s `LLM_MODEL_REPO`/`LLM_GGUF_FILE` (one-line deploy config change, ADR-003 §10's swap contract). Redeploy. Confirm via the already-live `production-drift.yml` (specs/005-ci-metrics-gate, unmodified) that the next scheduled or manually-dispatched run shows no regression in production.

**Checkpoint**: All four user stories independently functional and, together, form the complete pipeline from "held-out check exists" through "candidate is live in production and monitored."

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T025 Final consolidated check: `uv run pytest tests/ -v` green (including T004/T018's new tests); confirm every new `scripts/*.py` file listed in plan.md's Project Structure exists and matches its contract; walk quickstart.md's Steps 0-8 in order and confirm each step's stated expectation actually holds against the real repo state, not just against this task list's checkboxes.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001 and T002 can both start immediately, in parallel.
- **Foundational (Phase 2)**: No dependency on Phase 1 or Phase 3 — T003/T004/T005 can start immediately. Blocks Phase 4 onward, not Phase 3.
- **US1 (Phase 3)**: Depends on T002 (Phase 1) only. **Can ship before Phase 2 exists at all** — mirrors spec-005's US1 independence.
- **US2 (Phase 4)**: Depends on Phase 2 (T003/T005) and **all of Phase 3** (contamination-avoidance requires `evaluations/blind_spot/` to exist before generation starts) — this is a real ordering dependency, not just a priority-number coincidence. T001 (external) blocks generation/labeling specifically, not the whole phase.
- **US3 (Phase 5)**: Depends on Phase 4 (US2's frozen dataset, T017) and external GPU access.
- **US4 (Phase 6)**: Depends on Phase 5 (candidate + manifest) and specifically **T010** (Phase 3) for the baseline re-promotion — without it, T023's gate silently under-checks.
- **Polish (Phase 7)**: Depends on however much of Phases 3-6 are in scope for a given delivery.

### Within Each Phase

- T003/T004/T005 (Phase 2) are `[P]` — different files, no shared state.
- T006 must complete before T007 (script before its execution); T007 before T008 (data before spot-check); T008 before T009 (trusted data before scoring); T009 before T010 (group must be scored before a baseline can meaningfully include it).
- T011 is `[P]` relative to T012/T013 (different data source, no shared files) but T016 needs both T011's and T015's output — sequence generation/labeling/assembly, not catalog reconstruction, is the real bottleneck.
- T012 → T013 → T014 → T015 is a real sequence (pilot generate → label → spot-check → scale) — T015 must not start before T014 passes, per spec.md's Edge Cases on not salvaging a high-failure batch. T015 itself is now an iterate-until-passing loop against T016's coverage check, not a single fixed-size generation run.
- T016 → T017 is strict: freezing requires a passing coverage report first.
- T018's `[P]` marker means it can be *drafted* alongside T016 (different files, and the coverage-rule contract in contracts/sft-dataset-schema.md is fixed independent of either task) — but T018 asserts against T016's actual function names/return shapes/exception types, which aren't fixed by the contract alone. In practice, write T018 against the contract first, then reconcile it once T016's implementation exists, the same two-person-split reasoning spec-005's tasks.md used for its own check_regression.py/test pair.
- T019 must be fully written (including the three training-loop correctness requirements) before T020 executes — a training run started before these are nailed down risks an undetectable, silent failure mode this session's review exists specifically to prevent.
- T022 → T023 → T024 is a strict sequence — each gates the next, per spec.md User Story 4.

### Parallel Opportunities

- T001 + T002 (Phase 1) — different concerns, no shared files.
- T003 + T004 + T005 (Phase 2) — different files.
- T011 (Phase 4) can run in parallel with T012/T013's pilot (different data source — biassemble-core DB vs. LLM generation).
- T018 can be *drafted* in parallel with T016 once the coverage-rule contract (contracts/sft-dataset-schema.md) is fixed, though see "Within Each Phase" above — reconciling against T016's actual implementation once it exists is still a real, necessary step, not skippable just because both started in parallel.

---

## Parallel Example: Phase 2 (Foundational)

```bash
Task: "Implement scripts/validate_bias_catalog.py per data-model.md's BiasCatalogSnapshot"
Task: "Write tests/test_validate_bias_catalog.py against fixture valid_ids"
Task: "Add 'sft' to src/evaluation/evaluate.py's _SKIP_GROUPS"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1's T002 (already verified) — T001 isn't needed for US1 at all.
2. Complete Phase 3 (US1): T006-T010.
3. **STOP and VALIDATE**: T009 — confirm `blind_spot` reports a real result; T010 — confirm the re-promoted baseline actually contains it.
4. This alone delivers spec.md SC-001 and is the precondition every later story's validity depends on, even though nothing downstream is required to exist yet.

### Incremental Delivery

1. Phase 3 (US1) → ship first, no external dependency beyond T002's already-verified precondition.
2. Phase 1's T001 (credentials) provisioned in parallel with Phase 2/3 — must land before Phase 4's generation/labeling tasks (T012/T013/T015) are runnable.
3. Phase 2 (Foundational) → Phase 4 (US2) → the actual training dataset (frozen at T017), the real bottleneck of this whole feature.
4. Phase 5 (US3) → a candidate + manifest exist.
5. Phase 6 (US4) → gated ship decision — the payoff of every prior phase.
6. Phase 7 → final cross-story check.

### Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps each task to spec.md's US1/US2/US3/US4 for traceability.
- T001 is the one task in this list whose "done" state is a human action outside any repo, not a commit — track it separately from code-review-style completion, same convention as spec-005's T001.
- T010 is easy to skip without anything erroring — flagged twice in this list (Phase 3 and Phase 6's "Depends on") specifically because the failure mode it prevents is silent, not because it's procedurally complex.
- T017's freeze step exists so `dataset_version` is a guarantee, not a snapshot that can silently go stale between two candidates' training runs — treat any temptation to "just add a few more rows" to an already-frozen `sft_dataset.jsonl` as a new version, not an edit.
- Avoid re-deriving the regression/tolerance formula anywhere in this feature's own scripts — every reference to it should point at `scripts/check_regression.py` as the single source of truth (imported directly, per T023), matching research.md's rationale for keeping it a separate, reused, unmodified script.
