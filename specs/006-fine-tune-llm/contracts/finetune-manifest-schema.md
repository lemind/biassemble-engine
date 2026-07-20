# Contract: `training/manifests/<candidate_id>.json` schema

**Version**: v1 | **Written by**: the LoRA training procedure (`training/lora_finetune.md`), one file per candidate produced

---

## Shape

```json
{
  "candidate_id": "gemma3-4b-lora-2026-08-01",
  "dataset_version": "sha256:...",
  "dataset_composition": {
    "by_source": {"synthetic": 312, "real_weak": 28},
    "by_group": {"positive": 96, "negative": 68, "edge": 88, "adversarial": 88},
    "per_bias_coverage": {"anchoring_bias": 17, "...": "..."}
  },
  "lora_hyperparameters": {
    "rank": 16,
    "alpha": 32,
    "learning_rate": 0.0002,
    "epochs_planned": 3,
    "epochs_run": 2,
    "validation_split_fraction": 0.12,
    "best_checkpoint_epoch": 2,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
  },
  "base_model_revision": "google/gemma-3-4b-it@<commit-sha>",
  "quantization_command": "python llama.cpp/convert_hf_to_gguf.py ... --outtype q4_k_m",
  "eval_result": [
    {"group": "positive", "metric": "recall_at_k", "baseline_value": 0.729, "current_value": 0.875, "delta": 0.146, "tolerance": 0.25, "eligible": true, "regressed": false}
  ]
}
```

**`eval_result` is a JSON array, not an object** — one entry per `(group, metric)` finding, matching `scripts/check_regression.py`'s `compute_findings()` return shape exactly (`list[RegressionFinding]`, see specs/005-ci-metrics-gate/data-model.md). The single-entry example above is illustrative; a real manifest's `eval_result` has one entry per gated `(group, metric)` pair across every scored group, same as the CLI's printed table.

| Field | Type | Required | Notes |
|---|---|---|---|
| `candidate_id` | str | yes | Unique, used as the filename (`<candidate_id>.json`) — collisions must not silently overwrite a prior manifest. |
| `dataset_version` | str | yes | Content hash (e.g. `sha256:` prefix) of `evaluations/sft/sft_dataset.jsonl` at training time. |
| `dataset_composition` | object | yes | Aggregate counts only — no individual story text, so this file stays small and diffable. |
| `lora_hyperparameters.best_checkpoint_epoch` | int | yes | The epoch actually shipped, which — per ADR-005 §5 — is not required to equal `epochs_run`; the whole point of tracking both is that they can differ. |
| `lora_hyperparameters.target_modules` | list[str] | yes | The **resolved** module names actually trained, verified against the base model's real module names — not merely the requested config. Must include both attention (`q_proj`/`k_proj`/`v_proj`/`o_proj`) and MLP (`gate_proj`/`up_proj`/`down_proj`) projections (ADR-005 §5); an empty or attention-only list is a strong signal the adapter trained on close to zero effective parameters even if training completed without error. |
| `base_model_revision` | str | yes | Must be specific enough to re-pull the exact same base weights later (a commit SHA, not just a repo name). |
| `quantization_command` | str | yes | Verbatim, copy-pasteable. |
| `eval_result` | **array** (not object) | yes | The complete `check_regression.py` output for this candidate — `[dataclasses.asdict(f) for f in compute_findings(...)]`, imported and called directly (data-model.md) rather than parsed from the CLI's printed table. `json.dumps` on the raw dataclass list fails without the `asdict` conversion — not a summary, so a later reviewer never has to re-run evaluation just to see what happened. If the promoted baseline used for this comparison predates `blind_spot`'s promotion, this array will contain no `blind_spot` entries — see data-model.md's `ShipGateResult` note; do not read their absence as "no regression." |

## Validation rules

1. A manifest MUST be written for every candidate that reaches evaluation (User Story 3, Scenario 3) — a candidate with no manifest MUST NOT be evaluated against the ship gate (there would be nothing to attribute the eval result to later).
2. `dataset_version` MUST match the actual file hash at training time — a manifest with a stale or hand-typed hash defeats the entire point of this record (ADR-005 §5).
3. This file is never read by any runtime code path (`src/`) — it exists purely for human/audit reproducibility, same status as `evaluations/HISTORY.md`.

## Non-goals

- Does not gate anything itself — `scripts/check_regression.py`'s exit code is still the sole ship/no-ship signal (data-model.md's `ShipGateResult`). The manifest records the outcome; it doesn't decide it.
- Does not version or store the model weights themselves — those live wherever the training platform/HF Hub puts them; this file only records enough to identify and reproduce them.
