# Quickstart: Fine-Tune the `llm_union` Cartridge

Feature `006-fine-tune-llm`. This is ADR-005's task list (§7) made runnable, in dependency order. **Do not skip ahead — Steps 1 and 2 must both complete before Step 3 generates a single synthetic story (spec.md User Story 1's ordering requirement is load-bearing, not incidental).**

## Step 0 — Prerequisite credentials exist (verified present, need wiring into this repo)

**Not actually missing** — verified directly in `biassemble-core`'s `.env` (not `biassemble-engine`'s, which is why an earlier pass wrongly assumed these were unprovisioned):

```
GEMINI_API_KEY   # real, already the production key biassemble-core uses for its own labeling
                 # pipeline — exactly the teacher model ADR-005 §2 calls for, not a new credential
<DeepSeek/OpenAI/Qwen/OpenRouter keys>  # also present in biassemble-core's .env (commented out
                 # there, not wired into that app's own config, but valid) — pick whichever
                 # genuinely-different-provider(s) for generation per ADR-005 §2
```

What's actually needed before Step 3 can run: surface `GEMINI_API_KEY` (and whichever generation-provider key gets chosen) into `biassemble-engine`'s own `.env`/config once `scripts/generate_sft_stories.py`/`scripts/label_sft_stories.py` (T012/T013) exist to consume them — a small wiring step, not a provisioning blocker. Both `.env` files are gitignored, no exposure risk in git history.

`biassemble-core`'s Supabase read access (Step 1) and the raw DeepSeek export files (Step 2) already exist / are already accessible — no new credentials needed for those two steps either.

## Step 1 — Reconstruct the 28 weak-supervision pairs

```bash
uv run python scripts/reconstruct_weak_pairs.py --output evaluations/sft/weak_supervision_pairs.jsonl
```

Expect: 28 rows, each `source: "real_weak"`, joining `reasoning_traces.trace -> bias_hypotheses[].supporting_excerpts` to `retrieval_comparisons.final_list` via `run_id` (ADR-005 §1a). If the count differs from 28, re-verify against a fresh direct query before trusting the script — the number was correct as of 2026-07-15 and this ADR explicitly warns it "decays fast." **No new database credential is needed** — verified directly: `biassemble-engine`'s own `DATABASE_URL` and `biassemble-core`'s point at the same Supabase project (same pooler host and project ref), so this script reads `biassemble-core`'s tables through the engine's already-configured connection, no separate secret required. **Queries must be schema-qualified**: these tables live in that project's `core` schema, not `public` — `SELECT ... FROM reasoning_traces` resolves against `public` (Supabase's default `search_path`) and fails with "relation does not exist"; the script must query `core.reasoning_traces` / `core.retrieval_comparisons` explicitly.

## Step 2 — Promote the blind-spot batch into a real, held-out eval group (must complete before Step 3)

```bash
uv run python scripts/reconstruct_blind_spot_stories.py \
  --results evaluations/staging/blind_spot_eval_2026-07-13.json \
  --raw-dir ~/Downloads \
  --output-dir evaluations/blind_spot/
```

Expect: 80 scenario files under `evaluations/blind_spot/`, each with real `story` text joined in from the 8 raw DeepSeek export files by `(group, domain)` order (research.md). **Read the script's own summary output carefully**: it must flag the one known-bad label (`adv_005`'s `scarcity_bias`, not in the catalog — resolve before scoring, don't silently carry it forward) and confirm all 8 raw source files were found (fail loudly, don't silently skip, if any are missing from `~/Downloads` — they exist nowhere else).

**Every `BlindSpotScenario`'s `group` field must be the literal string `"blind_spot"`, not the batch's original per-story positive/negative/edge/adversarial label** — verified directly against `src/evaluation/evaluate.py`: `load_scenarios` reads `group` from each file's own JSON, not from the directory name, and aggregation keys on that same field. Reusing the original labels would silently merge these 80 scenarios into the *existing* four groups' metrics instead of creating a distinct, separately-gated group. `scripts/reconstruct_blind_spot_stories.py` must overwrite this field during reconstruction (data-model.md).

```bash
ENGINE_URL="" uv run python scripts/run_evaluation.py --strategy llm_union
```

**`ENGINE_URL=""` is required, not optional, for every local `--strategy llm_union` invocation in this quickstart** — verified against `scripts/run_evaluation.py`'s own guard: if `ENGINE_URL` resolves to a non-empty string (a real risk here, since this repo's `.env` already sets it for the deployed-Space workflows spec-005 built), any non-`vector_only` strategy exits immediately with `"ERROR: unset ENGINE_URL for local ... evaluation"` before running anything — this matches the script's own documented usage (`ENGINE_URL="" HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_evaluation.py`), which every command below follows.

**No `--groups` flag exists on this script's local CLI** (verified: `scripts/run_evaluation.py`'s local path, `main_sync`, calls `load_scenarios(eval_dir)` with no group filter at all — `--groups` is only a query parameter on the *deployed* `/evaluate` HTTP endpoint, a different code path). The plain command above scores every non-skipped group under `evaluations/`, which now includes `blind_spot` automatically — confirm the printed output shows a `blind_spot` row with a real Recall@5/Precision@5 result, using the exact same tooling as every other group, no new eval code path.

**Then re-promote a baseline that includes `blind_spot`, using the script's existing `--promote` flag:**

```bash
ENGINE_URL="" uv run python scripts/run_evaluation.py --strategy llm_union --promote
```

`scripts/check_regression.py`'s `compute_findings()` iterates over the *baseline's* groups, not the run's — a group promoted into the eval harness but absent from the currently promoted baseline produces zero findings for it, silently, in every later comparison (research.md, data-model.md's `ShipGateResult`). Skipping this re-promotion does not cause an error anywhere; it just means Step 7's gate never actually checks `blind_spot`, which defeats the entire point of Step 2.

**Also add `"sft"` to `src/evaluation/evaluate.py`'s `_SKIP_GROUPS` now, before Step 5 writes anything to `evaluations/sft/`.** Verified directly: `load_scenarios` globs `*.json` under every non-skipped subdirectory of `evaluations/`, so a stray `.json` file placed in `evaluations/sft/` (a coverage report, a manifest copy) would otherwise be silently loaded as a malformed scenario the next time anything runs the eval harness.

## Step 3 — Generate and label a pilot synthetic batch

```bash
uv run python scripts/generate_sft_stories.py --count 40 --output evaluations/sft/pilot_stories.jsonl
uv run python scripts/label_sft_stories.py --input evaluations/sft/pilot_stories.jsonl \
  --output evaluations/sft/pilot_labeled.jsonl
```

Expect: every row's `bias_ids` validated against the live catalog (`scripts/validate_bias_catalog.py`, DB-sourced — see data-model.md); any row naming an out-of-catalog id is rejected outright, not coerced. Before generating anything, diff the pilot's story premises/domains against `evaluations/{positive,negative,edge,adversarial}/*.json` **and** the newly-promoted `evaluations/blind_spot/*.json` — deliberate topical overlap defeats the whole point of Step 2.

## Step 4 — Human spot-check the pilot

Manually review a sample of `evaluations/sft/pilot_labeled.jsonl` (mirrors the blind-spot batch's own "staged, pending spot-check" discipline). Record pass/fail per reviewed row. If the failure rate is high, fix the generation/labeling prompts and regenerate the pilot — do not partially salvage a batch with a high failure rate (spec.md Edge Cases).

## Step 5 — Scale to full volume

**The actual requirement is ≥300 valid rows plus every coverage rule met — the exact count generated is an implementation detail, not a fixed target.** Generate with headroom (start around 340, since catalog validation rejects whole rows outright with no partial-row salvage) and iterate against the coverage check rather than generating one fixed batch and hoping it clears every rule:

```bash
uv run python scripts/generate_sft_stories.py --count 340 --output evaluations/sft/synthetic_stories.jsonl
uv run python scripts/label_sft_stories.py --input evaluations/sft/synthetic_stories.jsonl \
  --output evaluations/sft/synthetic_labeled.jsonl

# --coverage-report-only (T016's two-mode CLI): writes evaluations/sft/coverage_report.json without
# writing sft_dataset.jsonl — check this before assuming the batch above is sufficient. Existing
# hand-authored positive/edge/adversarial scenarios average ~3.0 labels/story (measured directly);
# ADR-005 §4's ~15-per-bias floor assumes synthetic generation carries similar multi-label density,
# but that isn't guaranteed — read the report's per_bias_counts rather than assuming it transferred
uv run python scripts/assemble_sft_dataset.py --weak-supervision evaluations/sft/weak_supervision_pairs.jsonl \
  --synthetic evaluations/sft/synthetic_labeled.jsonl --coverage-report-only

# if coverage_report.json shows specific under-covered bias ids or groups, generate a small
# targeted top-up batch for exactly those (not a full re-run), re-label, and re-check — repeat
# until "pass": true, then omit --coverage-report-only to write the real dataset:
uv run python scripts/assemble_sft_dataset.py \
  --weak-supervision evaluations/sft/weak_supervision_pairs.jsonl \
  --synthetic evaluations/sft/synthetic_labeled.jsonl \
  --output evaluations/sft/sft_dataset.jsonl
```

Expect: `assemble_sft_dataset.py` reports coverage against contracts/sft-dataset-schema.md's rules (per-bias floor, ≥20% negative fraction, group spread, ≥300 synthetic rows) and refuses to mark the dataset ready if any check fails, rather than emitting a partial dataset silently.

```bash
uv run pytest tests/test_validate_bias_catalog.py tests/test_assemble_sft_dataset.py -v
```

These are the two genuinely CI-testable pieces of this feature (research.md) — confirm they're green before trusting the assembled dataset's coverage report.

**Freeze the dataset once `coverage_report.json` shows `"pass": true`**: compute a content hash of `evaluations/sft/sft_dataset.jsonl`, record it as `dataset_version`, and treat the file as immutable from this point — any future expansion writes a new versioned file (`sft_dataset_v2.jsonl`), never an in-place edit. Without this, two candidates could later cite "the same" dataset path while its actual content silently differed between their training runs.

## Step 6 — LoRA fine-tune (external GPU platform — see `training/lora_finetune.md`)

Not run from this repo's own environment. Follow `training/lora_finetune.md`'s documented procedure on a free-tier Colab/Kaggle notebook: train on the HF bf16 checkpoint of the base model this feature's governing ADR pins as currently deployed — as of this writing, exactly `google/gemma-3-4b-it` (never the GGUF, never a different-sized variant — spec.md FR-009; if the deployed cartridge changes in a later ADR, re-derive this from that ADR instead), hold out a validation split from `evaluations/sft/sft_dataset.jsonl` itself, track per-epoch validation loss, keep the best checkpoint.

**Before trusting any of this run's output, confirm three training-loop details explicitly (spec.md FR-019/FR-020/FR-021) — none of these fail loudly if wrong:**
1. Training examples use Gemma-3's own chat template, with loss masked to the completion only (not the prompt).
2. The `bias_ids` target is serialized as an actual JSON array string (`["anchoring_bias"]`), matching `src/llm/prompt.py`'s wire format — not a Python list repr.
3. `target_modules` resolves to both attention and MLP projections against the base model's real module names, not an empty or attention-only match from an unverified library default.

**Before merging, verify `target_modules` actually resolved against the real model** — print the adapter's trained parameter count and confirm it includes both attention and MLP projections; an empty or attention-only match means the adapter trained on close to zero effective parameters despite training completing without error, and no later step in this pipeline will catch that on its own (Step 7's gate would just read as "no improvement," pointing back at data, not this).

**Then, before moving to Step 7, run inference on ~20 random training samples as a smoke test.** A chat-template mismatch, tokenizer issue, or serialization bug can let training "succeed" (loss decreases normally) while the resulting model's actual outputs are garbage — catching this here costs minutes; catching it only after Step 7's full evaluation costs a wasted eval cycle and a much harder-to-diagnose failure.

**Disk**: peak usage across the merge+quantize step is additive (HF base checkpoint + merged bf16 checkpoint + GGUF output can coexist, a plausible ~18GB peak). **Order matters**: merge first (this step reads the base checkpoint from the HF cache — clearing the cache first forces a mid-procedure re-download), *then* clear the HF download cache, *then* quantize directly from the merged checkpoint without a separate full bf16 save. Train → merge → clear cache → quantize, as the default sequence, not a fallback for when space runs out (ADR-005 §5).

Quantize to Q4_K_M GGUF. Write `training/manifests/<candidate_id>.json` (contracts/finetune-manifest-schema.md, including the resolved `target_modules` list) before moving to Step 7 — a candidate with no manifest does not proceed.

## Step 7 — Evaluate the candidate against the ship gate

```bash
ENGINE_URL="" LLM_MODEL_REPO=<candidate-repo> LLM_GGUF_FILE=<candidate-gguf> \
  uv run python scripts/run_evaluation.py --strategy llm_union
python scripts/check_regression.py --run evaluations/runs/run_<latest>.json \
  --baseline evaluations/baselines/baseline_<latest>.json
echo $?
```

**Archive the raw per-scenario outputs alongside the manifest**, not just the aggregate metrics — copy or save each scenario's retrieved `bias_ids` from this run (e.g. `training/manifests/<candidate_id>_predictions.json`). Aggregate recall/precision numbers alone can't answer "which specific stories changed" when comparing this candidate against the baseline or another candidate later, and re-running evaluation just to recover that detail is wasted compute for data this step already produced once.

Same CLI as any PR (specs/005-ci-metrics-gate), unmodified — no new eval code path. Confirm: `positive`'s `recall_at_k` finding reads `>= 0.85`; no other group regressed past its own eligibility (`check_regression.py`'s existing per-`(group,metric)` table, unchanged); `positive`'s `precision_at_k` did not drop in the same run (ADR-005 §6 point 3's recall/precision trade-off check). **Confirm the table actually includes a `blind_spot` row before trusting its absence** — it only appears if the `--baseline` file was re-promoted after Step 2's promotion (research.md); a baseline that predates that re-promotion silently omits it rather than erroring, and a candidate that clears 0.85 on `positive` while `blind_spot` was never actually compared is not proven to generalize, it's untested. When writing `eval_result` into the candidate's manifest, populate it with `[dataclasses.asdict(f) for f in compute_findings(...)]`, imported from `scripts/check_regression.py` directly (data-model.md) — it's a JSON array, not an object, and the raw dataclass list is not directly `json.dumps`-able.

**If the bar isn't cleared, triage before restarting Step 3 — don't assume it's a data problem by default:**
1. Check the training loss curve from Step 6 — if it never meaningfully decreased, the adapter likely didn't train at all (a `target_modules` resolution failure is the most common silent cause — re-check Step 6's checkpoint before touching data).
2. Sample a handful of raw inference outputs from the candidate against known stories (Step 6's smoke test should already have caught this, but re-check) — if outputs are malformed JSON or a Python-repr-looking string instead of a JSON array, the training-loop serialization requirement (Step 6, FR-020) was likely missed, not a data-volume problem.
3. Check the manifest's `base_model_revision` against what was actually quantized (Step 6) and what the runtime actually loaded for this trial run — a mismatch between "trained against," "quantized from," and "runtime loaded" produces a candidate that doesn't reflect the training run at all, and is easy to overlook since nothing else in this pipeline would flag it.
4. Only once training, serialization, and revision are all confirmed correct and the recall gap persists: **iterate on data (Steps 3–5)**, not on `check_regression.py`'s tolerances. This is a hard gate, not a judgment call (ADR-005 §6 point 3) — but re-running the entire data pipeline to fix a one-line training-config bug wastes a full generation/labeling/training cycle for nothing.

## Step 8 — Ship (only after Step 7 passes)

**Before touching config**: `grep -rn "HACK(" src/` and re-validate every hit against the fine-tuned candidate, per `CLAUDE.md`'s convention for swapping the model behind any `SELECTION_STRATEGY` (spec.md FR-022) — a workaround tagged for the previous base GGUF's quirks may not apply, or a new quirk may exist that no tag was ever written for. Delete anything whose `REVISIT` condition fired with no supporting evidence, same as any other such swap.

Then update `config.py`'s defaults or `space-vars.env`'s `LLM_MODEL_REPO`/`LLM_GGUF_FILE` — a one-line deploy config change, no other code changes (ADR-003 §10's swap contract). Redeploy. Confirm via the already-live `production-drift.yml` (specs/005-ci-metrics-gate) that the next scheduled or manually-dispatched run shows no regression in production.
