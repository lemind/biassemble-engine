# Phase 1 Data Model: Fine-Tune the `llm_union` Cartridge

No database schema changes anywhere (this feature only *reads* from `biassemble-core`'s existing tables, per ADR-005 §1a/§9). The entities below are new file-based data shapes this feature introduces, plus one existing shape it reuses unchanged.

## WeakSupervisionPair (new — produced by `scripts/reconstruct_weak_pairs.py`)

Reconstructed by joining `biassemble-core`'s `reasoning_traces.trace -> bias_hypotheses[].supporting_excerpts` to `retrieval_comparisons.final_list` via `run_id` (ADR-005 §1a). 28 rows expected against today's data.

| Field | Type | Notes |
|---|---|---|
| `run_id` | str | join key back to the source `biassemble-core` records, kept for traceability/debugging, never used by the training step itself |
| `story_excerpts` | list[str] | quoted fragments from `bias_hypotheses[].supporting_excerpts` — NOT a complete story; average 2.6 excerpts per row (ADR-005 §1a) |
| `bias_ids` | list[str] | from `retrieval_comparisons.final_list` — assessment-confirmed labels |
| `source` | str | always `"real_weak"` — never `"real"` (ADR-005 §2 explicitly rejects that label) and never `"synthetic"` |

## BlindSpotScenario (new — produced by `scripts/reconstruct_blind_spot_stories.py`)

The promoted held-out group's per-scenario shape, matching the existing `evaluations/{positive,negative,edge,adversarial}/*.json` convention exactly (same fields `src/evaluation/evaluate.py`'s scenario loader already expects) so no loader changes are needed.

| Field | Type | Notes |
|---|---|---|
| `scenario_id` | str | reused from the existing results file (`neg_006`, `adv_004`, etc.) — not regenerated |
| `group` | str | **must be the literal string `"blind_spot"`, not the batch's original per-story label** (see the load-bearing correction below) |
| `original_subgroup` | str | the batch's original `"positive"`\|`"negative"`\|`"edge"`\|`"adversarial"` label, preserved for the in-field/out-of-field analysis `blind_spot_eval_2026-07-13_SUMMARY.md` already did — an extra field the harness ignores (see below), not used for scoring |
| `story` | str | reconstructed from the matching raw DeepSeek export file (`~/Downloads/deepseek_json_20260713_*.json`, see research.md) by `(group, domain)` order-matched join (the join key uses the *original* subgroup label, before it's renamed to `"blind_spot"` for the output file) — this field does not exist in the source results file and is the entire point of this reconstruction step |
| `expected_bias_ids` | list[str] | carried over from the results file unchanged, except the one known-bad entry flagged in `blind_spot_eval_2026-07-13_SUMMARY.md` (`adv_005`'s `scarcity_bias`, not in the catalog) — must be resolved during reconstruction, not silently carried forward as an invalid id. **Prefer dropping only the invalid label from that row's list over dropping the whole row** — the row still has a second, valid expected id (`bandwagon_effect`) and dropping the entire scenario shrinks the group's `count` for no reason when only one label needs removing. |
| `domain` / `domain_familiarity` | str | carried over unchanged — preserved for possible future in-field/out-of-field analysis, not used by the scoring path itself |

**Load-bearing correction, found by reading `src/evaluation/evaluate.py` directly, not assumed**: `load_scenarios` builds each `Scenario.group` from the JSON file's own `"group"` key — **not** from the containing directory name — and `compute_group_metrics` aggregates with `groups.setdefault(r.group, []).append(r)`, keyed on that same field. If `BlindSpotScenario.group` reused the batch's original `"positive"`/`"negative"`/`"edge"`/`"adversarial"` labels (as an earlier draft of this document said), the 80 promoted scenarios would silently merge into the four *existing* scenario groups' own metrics — inflating their `count` and shifting their averages — rather than ever appearing as a distinct `blind_spot` group in `check_regression.py`'s table at all. That would defeat spec.md User Story 1 entirely (the held-out group would not exist as a separately-scored, separately-gated thing) without erroring anywhere. Every `BlindSpotScenario`'s `group` field must therefore be overwritten to the literal `"blind_spot"` during reconstruction, regardless of which of the four shapes a given story was originally generated as.

**Output location**: `evaluations/blind_spot/*.json`, one file per scenario, matching the naming convention of the existing scenario-group directories.

## SyntheticStoryRecord (new — produced by `scripts/generate_sft_stories.py`, consumed by `scripts/label_sft_stories.py`)

| Field | Type | Notes |
|---|---|---|
| `story` | str | generated text |
| `group` | str | which of positive/negative/edge/adversarial shape this generation targeted |
| `generator_model` | str | which provider/model produced this specific story (e.g. `"deepseek-chat"`, `"gemini-1.5-pro"`) — recorded per-row, not just asserted in prose, so generation diversity (ADR-005 §2) is auditable after the fact and any later "why do examples from generator X train better than generator Y" question is answerable from the data itself |
| `generation_prompt_version` | str | identifies which prompt template generated this story — a distinct axis from `generator_model` (the same model with a revised prompt is a different data-generating process), tracked separately so either can be attributed independently later |
| `domain` | str | tracked per FR-007/spec.md's diversity requirement |
| `style_tags` / `tone_tags` | list[str] | free-form tags recorded at generation time for the same diversity-tracking purpose — not a fixed enum, since the point is variety, not conformance to a taxonomy |

**Labeling adds two more provenance fields before this record becomes an `SftExample`**: `teacher_model` (which labeling model/version produced `bias_ids` — the one-consistent-teacher policy, ADR-005 §2, still names one teacher for this round, but recording it per-row rather than assuming it makes that policy checkable rather than assumed) and `label_prompt_version` (same reasoning as `generation_prompt_version`, for the labeling prompt). All four provenance fields (`generator_model`, `generation_prompt_version`, `teacher_model`, `label_prompt_version`) carry through into the corresponding `SftExample` row unchanged — `scripts/assemble_sft_dataset.py` must not strip them when merging.

## SftExample (new — the assembled training row, one line of `evaluations/sft/sft_dataset.jsonl`)

The actual training input, matching `src/llm/prompt.py`'s output contract exactly (ADR-005 §2's "target shape matches production exactly" decision).

| Field | Type | Notes |
|---|---|---|
| `story` | str | full story text (synthetic) or joined excerpts (weak-supervision) |
| `bias_ids` | list[str] | validated against the live catalog (see `BiasCatalogSnapshot` below) before this row is written — a row that fails validation never reaches this file |
| `source` | str | `"synthetic"` \| `"real_weak"` — always one of these two, per ADR-005 §2/§6, so contribution can be measured or excluded separately during validation |
| `spot_checked` | bool | `true` only after a human-reviewed sample confirms the batch this row belongs to passed review (FR-006) — this is a batch-level outcome recorded per-row for simplicity, not an individual per-row review |
| `generator_model` / `generation_prompt_version` | str, nullable | carried through from `SyntheticStoryRecord` for `source: "synthetic"` rows; `null` for `source: "real_weak"` rows (no generator — the story text is a real excerpt) |
| `teacher_model` / `label_prompt_version` | str, nullable | carried through from labeling for `source: "synthetic"` rows; `null` for `source: "real_weak"` rows (labels come from `retrieval_comparisons.final_list`, not a labeling pass) |

**Where chat-template application and target serialization happen**: `SftExample.bias_ids` is stored here as a plain JSON list (the natural JSONL representation) — the chat-template wrapping, prompt/completion loss-masking, and re-serializing `bias_ids` as the literal JSON-array-string target (`["anchoring_bias"]`, matching `src/llm/prompt.py`'s wire format exactly, not a Python list repr) are training-loop concerns applied when `training/lora_finetune.md`'s procedure consumes this file, not stored in the file itself (FR-019/FR-020). Getting this conversion right at training-loop time, not dataset-assembly time, is what `training/lora_finetune.md` must document explicitly — see tasks.md.

## CoverageReport (new — `evaluations/sft/coverage_report.json`, one per assembled dataset version)

Written by `scripts/assemble_sft_dataset.py` alongside `sft_dataset.jsonl` — not just printed to the console — so later analysis never has to re-derive these numbers from the raw dataset file.

| Field | Type | Notes |
|---|---|---|
| `dataset_version` | str | the same content hash `FinetuneManifest.dataset_version` records — ties a coverage report to the exact frozen dataset file it describes |
| `total_rows` | int | `synthetic` + `real_weak` combined |
| `counts_by_source` | dict | `{"synthetic": N, "real_weak": 28}` |
| `counts_by_group` | dict | `{"positive": N, "negative": N, "edge": N, "adversarial": N}` |
| `per_bias_counts` | dict | one entry per catalog bias id, count of rows whose `bias_ids` includes it — the direct evidence for or against the ≥15-per-bias floor (contracts/sft-dataset-schema.md) |
| `negative_fraction` | float | share of rows with `bias_ids: []` |
| `pass` | bool | whether every rule in contracts/sft-dataset-schema.md's validation list was met — `assemble_sft_dataset.py` refuses to write `sft_dataset.jsonl` as ready if this is `false` (only the report itself is written, so a failed attempt is diagnosable) |

## BiasCatalogSnapshot (new concept, no new persisted file — a read path, not a stored entity)

`scripts/validate_bias_catalog.py` does **not** hardcode a static list of 38 ids. `src/llm/prompt.py`'s `load_catalog(pool, taxonomy_version)` already sources the catalog from the database at request time (DB-sourced by design, "not hardcoded, not a re-parse of knowledge/*.md" per that function's own docstring) — the offline validation script reuses the exact same query path (read-only connection) so the dataset is validated against whatever the *current* taxonomy actually is, not a snapshot that could silently drift from production. This is the same `valid_ids: set[str]` shape `prompt.py`'s own `_validate_catalog`/`parse_biases` already use — reused, not reinvented.

## FinetuneManifest (new — one JSON file per candidate, `training/manifests/<candidate_id>.json`)

The reproducibility record ADR-005 §5 requires.

| Field | Type | Notes |
|---|---|---|
| `candidate_id` | str | unique identifier for this training run, used as the manifest filename and referenced in eval/promotion records |
| `dataset_version` | str | a content hash of `evaluations/sft/sft_dataset.jsonl` at training time — not a human-assigned version string, so it's impossible for a manifest to silently point at the wrong dataset revision |
| `dataset_composition` | dict | counts by `source` (`real_weak` vs `synthetic`) and by `group`, plus the per-bias coverage table — enough to answer "what did this candidate actually train on" without re-parsing the dataset file |
| `lora_hyperparameters` | dict | rank, alpha, learning rate, planned epochs, epochs actually run, validation-split fraction, **and `target_modules`: the resolved list of module names actually trained** (e.g. `["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"]`) — recorded as what was *resolved* against the base model's real module names, not merely what was requested in config, since a resolution mismatch is exactly the failure mode (near-zero effective trained parameters) this field exists to catch after the fact (ADR-005 §5) |
| `base_model_revision` | str | the exact `google/gemma-3-4b-it` HF commit/revision trained from |
| `quantization_command` | str | the exact `llama.cpp` conversion command used to produce the final GGUF, verbatim — enough to reproduce the quantization step exactly |
| `eval_result` | **list**, not dict | the full `check_regression.py` output against this candidate — a JSON **array** of finding objects (`compute_findings()` returns `list[RegressionFinding]`; there is no wrapping object). **Populated by importing `compute_findings()` from `scripts/check_regression.py`, then serializing with `[dataclasses.asdict(f) for f in findings]`** — `RegressionFinding` is a plain `@dataclass`, and `json.dumps()` on a raw list of dataclass instances raises `TypeError: Object of type RegressionFinding is not JSON serializable`; `dataclasses.asdict` is the required conversion step, not optional boilerplate. This keeps `check_regression.py`'s own CLI (text table + exit code) completely unchanged; the manifest-writer is simply another Python caller of the same function, same as any other reuse in this repo. |

## ShipGateResult (reused, not new — `specs/005-ci-metrics-gate/data-model.md`'s `RegressionFinding`)

Evaluating a fine-tuned candidate (User Story 4) produces exactly the same `RegressionFinding` list `check_regression.py` already produces for any PR, scored against the currently promoted baseline. This feature defines no new comparison/eligibility logic — the ship/no-ship decision is `positive`'s `recall_at_k` finding meeting the hard `>= 0.85` bar (ADR-005 §6 point 3, spec.md SC-004) plus no regression on any other group past its own existing eligibility rule (spec.md SC-005), read directly off that existing output.

**Load-bearing detail, verified against `compute_findings()`'s actual implementation**: it iterates over the *baseline's* groups (`for group, baseline_gm in baseline_group_metrics.items()`), not the run's — a group missing from the baseline produces zero findings for it, not an error. `blind_spot` only appears in `ShipGateResult` once a baseline has been *re-promoted* after `blind_spot` is promoted as a scenario group (User Story 1's Independent Test); promoting the scenario group alone does not retroactively add it to an already-promoted baseline. Until that re-promotion happens, `blind_spot`'s numbers must be read manually from the raw evaluation run, not assumed to be part of the automated gate.

## State / lifecycle notes

- **`evaluations/sft/sft_dataset.jsonl` is append-only *during construction* (pilot → scale, T003/T006 in the ADR's task list), then frozen once assembly passes validation.** The pilot batch's rows are not discarded when scaling to full volume, they're the first rows of the same in-progress file. But once `scripts/assemble_sft_dataset.py` reports `CoverageReport.pass: true` and a `dataset_version` hash is recorded, the file becomes **immutable** — any later expansion (more weak-supervision pairs surfacing, a second synthetic batch) produces a new versioned file (e.g. `sft_dataset_v2.jsonl`) rather than editing this one in place. Without this, two candidates' manifests could both cite "`evaluations/sft/sft_dataset.jsonl`" while the file's actual content silently differed between their two training runs, making `dataset_version` a lie rather than a guarantee. Freezing is a distinct, explicit step (tasks.md) immediately after assembly passes, not an implicit property of "not touching the file again."
- **`evaluations/blind_spot/` is written once, by the reconstruction step, and never rewritten by anything in this feature's training loop** — enforcing FR-002's "never train on the held-out group" at the data layer: nothing in `scripts/generate_sft_stories.py`, `label_sft_stories.py`, or `assemble_sft_dataset.py` reads from `evaluations/blind_spot/`, so there is no code path by which it could leak into `evaluations/sft/sft_dataset.jsonl`.
- **No baseline-promotion path is touched.** Same boundary spec-005 already established: nothing in this feature writes to `evaluations/baselines/`. A candidate clearing the ship gate still requires the existing manual promotion step, unchanged (ADR-005 §6 point 4).
