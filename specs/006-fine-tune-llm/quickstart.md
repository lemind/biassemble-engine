# Quickstart: Fine-Tune the `llm_union` Cartridge

Feature `006-fine-tune-llm`. This is ADR-005's task list (§7) made runnable, in dependency order. **Do not skip ahead — Steps 1 and 2 must both complete before Step 3 generates a single synthetic story (spec.md User Story 1's ordering requirement is load-bearing, not incidental).**

## Step 0 — Prerequisite credentials exist (blocks Steps 3–4)

Not currently configured anywhere in this repo:

```
GEMINI_API_KEY          # synthetic labeling (single consistent teacher, ADR-005 §2)
<generation providers>  # whichever additional LLM providers are chosen for story generation —
                         # must be genuinely different from Gemini (different provider/family/template)
```

`biassemble-core`'s Supabase read access (Step 1) and the raw DeepSeek export files (Step 2) already exist / are already accessible — no new credentials needed for those two steps.

## Step 1 — Reconstruct the 28 weak-supervision pairs

```bash
python scripts/reconstruct_weak_pairs.py --output evaluations/sft/weak_supervision_pairs.jsonl
```

Expect: 28 rows, each `source: "real_weak"`, joining `reasoning_traces.trace -> bias_hypotheses[].supporting_excerpts` to `retrieval_comparisons.final_list` via `run_id` (ADR-005 §1a). If the count differs from 28, re-verify against a fresh direct query before trusting the script — the number was correct as of 2026-07-15 and this ADR explicitly warns it "decays fast."

## Step 2 — Promote the blind-spot batch into a real, held-out eval group (must complete before Step 3)

```bash
python scripts/reconstruct_blind_spot_stories.py \
  --results evaluations/staging/blind_spot_eval_2026-07-13.json \
  --raw-dir ~/Downloads \
  --output-dir evaluations/blind_spot/
```

Expect: 80 scenario files under `evaluations/blind_spot/`, each with real `story` text joined in from the 8 raw DeepSeek export files by `(group, domain)` order (research.md). **Read the script's own summary output carefully**: it must flag the one known-bad label (`adv_005`'s `scarcity_bias`, not in the catalog — resolve before scoring, don't silently carry it forward) and confirm all 8 raw source files were found (fail loudly, don't silently skip, if any are missing from `~/Downloads` — they exist nowhere else).

```bash
uv run python scripts/run_evaluation.py --strategy llm_union --groups blind_spot
```

Confirm this produces a real Recall@5/Precision@5 result for the new group, using the exact same tooling as every other group — no new eval code path.

**Then re-promote a baseline that includes `blind_spot`.** `scripts/check_regression.py`'s `compute_findings()` iterates over the *baseline's* groups, not the run's — a group promoted into the eval harness but absent from the currently promoted baseline produces zero findings for it, silently, in every later comparison (research.md, data-model.md's `ShipGateResult`). Skipping this re-promotion does not cause an error anywhere; it just means Step 7's gate never actually checks `blind_spot`, which defeats the entire point of Step 2.

**Also add `"sft"` to `src/evaluation/evaluate.py`'s `_SKIP_GROUPS` now, before Step 5 writes anything to `evaluations/sft/`.** Verified directly: `load_scenarios` globs `*.json` under every non-skipped subdirectory of `evaluations/`, so a stray `.json` file placed in `evaluations/sft/` (a coverage report, a manifest copy) would otherwise be silently loaded as a malformed scenario the next time anything runs the eval harness.

## Step 3 — Generate and label a pilot synthetic batch

```bash
python scripts/generate_sft_stories.py --pilot --count 40 --output evaluations/sft/pilot_stories.jsonl
python scripts/label_sft_stories.py --input evaluations/sft/pilot_stories.jsonl \
  --output evaluations/sft/pilot_labeled.jsonl
```

Expect: every row's `bias_ids` validated against the live catalog (`scripts/validate_bias_catalog.py`, DB-sourced — see data-model.md); any row naming an out-of-catalog id is rejected outright, not coerced. Before generating anything, diff the pilot's story premises/domains against `evaluations/{positive,negative,edge,adversarial}/*.json` **and** the newly-promoted `evaluations/blind_spot/*.json` — deliberate topical overlap defeats the whole point of Step 2.

## Step 4 — Human spot-check the pilot

Manually review a sample of `evaluations/sft/pilot_labeled.jsonl` (mirrors the blind-spot batch's own "staged, pending spot-check" discipline). Record pass/fail per reviewed row. If the failure rate is high, fix the generation/labeling prompts and regenerate the pilot — do not partially salvage a batch with a high failure rate (spec.md Edge Cases).

## Step 5 — Scale to full volume

```bash
# generate with headroom: catalog-validation in the next step rejects any row naming an
# out-of-catalog id outright (no partial-row salvage), so generating exactly the 300 floor
# leaves zero room for ordinary rejection attrition without a second generation pass
python scripts/generate_sft_stories.py --count 340 --output evaluations/sft/synthetic_stories.jsonl
python scripts/label_sft_stories.py --input evaluations/sft/synthetic_stories.jsonl \
  --output evaluations/sft/synthetic_labeled.jsonl
python scripts/assemble_sft_dataset.py \
  --weak-supervision evaluations/sft/weak_supervision_pairs.jsonl \
  --synthetic evaluations/sft/synthetic_labeled.jsonl \
  --output evaluations/sft/sft_dataset.jsonl
```

Expect: `assemble_sft_dataset.py` reports coverage against contracts/sft-dataset-schema.md's rules (per-bias floor, ≥20% negative fraction, group spread, ≥300 synthetic rows) and refuses to mark the dataset ready if any check fails, rather than emitting a partial dataset silently.

```bash
uv run pytest tests/test_validate_bias_catalog.py tests/test_assemble_sft_dataset.py -v
```

These are the two genuinely CI-testable pieces of this feature (research.md) — confirm they're green before trusting the assembled dataset's coverage report.

## Step 6 — LoRA fine-tune (external GPU platform — see `training/lora_finetune.md`)

Not run from this repo's own environment. Follow `training/lora_finetune.md`'s documented procedure on a free-tier Colab/Kaggle notebook: train on the HF bf16 checkpoint of exactly `google/gemma-3-4b-it` (never the GGUF, never a different-sized Gemma-3 variant — spec.md FR-009), hold out a validation split from `evaluations/sft/sft_dataset.jsonl` itself, track per-epoch validation loss, keep the best checkpoint.

**Before trusting any of this run's output, confirm three training-loop details explicitly (spec.md FR-019/FR-020/FR-021) — none of these fail loudly if wrong:**
1. Training examples use Gemma-3's own chat template, with loss masked to the completion only (not the prompt).
2. The `bias_ids` target is serialized as an actual JSON array string (`["anchoring_bias"]`), matching `src/llm/prompt.py`'s wire format — not a Python list repr.
3. `target_modules` resolves to both attention and MLP projections against the base model's real module names, not an empty or attention-only match from an unverified library default.

**Disk**: peak usage during merge+quantize is additive (HF base checkpoint + merged bf16 checkpoint + GGUF output can coexist, a plausible ~18GB peak) — clear the HF download cache before merging, and quantize directly from the merged checkpoint without a separate full bf16 save, as the default approach rather than a fallback for when space runs out (ADR-005 §5).

Merge, quantize to Q4_K_M GGUF. Write `training/manifests/<candidate_id>.json` (contracts/finetune-manifest-schema.md, including the resolved `target_modules` list) before moving to Step 7 — a candidate with no manifest does not proceed.

## Step 7 — Evaluate the candidate against the ship gate

```bash
LLM_MODEL_REPO=<candidate-repo> LLM_GGUF_FILE=<candidate-gguf> \
  uv run python scripts/run_evaluation.py --strategy llm_union
python scripts/check_regression.py --run evaluations/runs/run_<latest>.json \
  --baseline evaluations/baselines/baseline_<latest>.json
echo $?
```

Same CLI as any PR (specs/005-ci-metrics-gate), unmodified — no new eval code path. Confirm: `positive`'s `recall_at_k` finding reads `>= 0.85`; no other group regressed past its own eligibility (`check_regression.py`'s existing per-`(group,metric)` table, unchanged); `positive`'s `precision_at_k` did not drop in the same run (ADR-005 §6 point 3's recall/precision trade-off check). **Confirm the table actually includes a `blind_spot` row before trusting its absence** — it only appears if the `--baseline` file was re-promoted after Step 2's promotion (research.md); a baseline that predates that re-promotion silently omits it rather than erroring, and a candidate that clears 0.85 on `positive` while `blind_spot` was never actually compared is not proven to generalize, it's untested. When writing `eval_result` into the candidate's manifest, populate it by importing `compute_findings()` from `scripts/check_regression.py` directly (data-model.md) rather than parsing this command's printed table.

If the bar isn't cleared: **iterate on data (Steps 3–5), not on `check_regression.py`'s tolerances.** This is a hard gate, not a judgment call (ADR-005 §6 point 3).

## Step 8 — Ship (only after Step 7 passes)

**Before touching config**: `grep -rn "HACK(" src/` and re-validate every hit against the fine-tuned candidate, per `CLAUDE.md`'s convention for swapping the model behind any `SELECTION_STRATEGY` (spec.md FR-022) — a workaround tagged for the previous base GGUF's quirks may not apply, or a new quirk may exist that no tag was ever written for. Delete anything whose `REVISIT` condition fired with no supporting evidence, same as any other such swap.

Then update `config.py`'s defaults or `space-vars.env`'s `LLM_MODEL_REPO`/`LLM_GGUF_FILE` — a one-line deploy config change, no other code changes (ADR-003 §10's swap contract). Redeploy. Confirm via the already-live `production-drift.yml` (specs/005-ci-metrics-gate) that the next scheduled or manually-dispatched run shows no regression in production.
