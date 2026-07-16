# Contract: `evaluations/sft/sft_dataset.jsonl` schema

**Version**: v1 | **Format**: JSONL, one `SftExample` object per line (data-model.md)

---

## Row shape

```json
{"story": "...", "bias_ids": ["anchoring_bias", "sunk_cost_fallacy"], "source": "synthetic", "spot_checked": true}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `story` | str | yes | Full story text (synthetic rows) or `"\n\n".join(story_excerpts)` (weak-supervision rows — see below) |
| `bias_ids` | list[str] | yes | Every id MUST be present in the live catalog at the time this row was validated (`scripts/validate_bias_catalog.py`) — a row containing even one out-of-catalog id MUST NOT appear in this file (ADR-005 §2, spec.md FR-005). May be `[]` for negative examples. |
| `source` | str | yes | Exactly `"synthetic"` or `"real_weak"` — no other value is valid. |
| `spot_checked` | bool | yes | `true` only once the batch this row belongs to has passed human review (FR-006). A row with `spot_checked: false` MUST NOT be consumed by the LoRA training step. |

## Weak-supervision rows specifically

A `WeakSupervisionPair` (data-model.md) becomes an `SftExample` by joining its `story_excerpts` with `"\n\n"` into a single `story` string. This is a lossy, fragment-based reconstruction, not equivalent to a complete story — consumers of this file that want to distinguish full stories from fragment-joins must use the `source` field (`real_weak` rows are always fragment-joins), not story length or content heuristics.

## Validation rules (enforced by `scripts/assemble_sft_dataset.py` before the file is considered ready to train on)

1. **Catalog membership**: every `bias_ids` entry validated against the live DB-sourced catalog (data-model.md's `BiasCatalogSnapshot`) — reject the whole row on any invalid id, do not coerce or drop just the invalid entry (spec.md's Edge Cases).
2. **Group coverage**: rows must span all four scenario-group shapes represented in the existing eval harness (positive/negative/edge/adversarial-style story content) — checked by `tests/test_assemble_sft_dataset.py`'s coverage logic, not eyeballed.
3. **Per-bias floor**: at least ~15 rows (starting default, ADR-005 §4) reference each catalog bias id somewhere in their `bias_ids`, across the whole file.
4. **Negative fraction**: at least 20% of rows have `bias_ids: []`.
5. **Volume**: at least 300 rows with `source: "synthetic"` before the dataset is considered ready to train on (the 28 `real_weak` rows are additive, not counted toward this floor, since ADR-005 §2 treats them as a seed, not the primary volume source).
6. **No blind-spot overlap**: no row's `story` field may originate from `evaluations/blind_spot/*.json` — this is enforced by construction (`assemble_sft_dataset.py` never reads that directory, data-model.md's lifecycle notes), not by a runtime check against its contents.

## Non-goals

- Does not define how stories are generated or labeled (that's `generate_sft_stories.py` / `label_sft_stories.py`'s job) — this is the contract for the *assembled, validated* output only.
- Does not define chat-template application, prompt/completion loss masking, or the JSON-array-string target serialization the training loop needs (`src/llm/prompt.py`'s exact wire format, not a Python list repr) — those are `training/lora_finetune.md`'s responsibility, applied when this file is consumed, not stored in it (spec.md FR-019/FR-020, data-model.md's `SftExample` notes).
- Does not track per-row provenance beyond `source` (which generator/provider produced a synthetic row is recorded in the pre-assembly `SyntheticStoryRecord`, not carried into the final training file — the training step does not need it, and `training/manifests/*.json`'s `dataset_composition` field is the place aggregate provenance is recorded).
