# LoRA Fine-Tune Procedure — `llm_union` Gemma-3-4B Cartridge

**Status**: documented procedure, not a runnable script in this repo (`spec-006` T019). Run this on an external free-tier GPU notebook (Colab/Kaggle, T4-class). Governed by `adr/005-fine-tune-engine-llm.md` §5 — cite that ADR for the *why*, this file is the *how*.

**Input**: `evaluations/sft/sft_dataset.jsonl` (T017, frozen, `dataset_version: sha256:73ddf4ca1167fa8ebc105201e78492c7b8cf1440ae77aa7fa8d0c84aa6963b97`, 907 rows).
**Output**: a merged, quantized Q4_K_M GGUF candidate + `training/manifests/<candidate_id>.json` (T021, contracts/finetune-manifest-schema.md).

---

## 0. Base model pin

Train on the **HF bf16 checkpoint** of the base model this feature's governing ADR pins as currently deployed — as of this writing, exactly:

```
google/gemma-3-4b-it
```

**Never the GGUF** (LoRA cannot train a quantized checkpoint) **and never a different-sized variant** (spec.md FR-009). If the deployed cartridge changes in a later ADR, re-derive this pin from that ADR rather than assuming it still applies.

At load time, record the exact commit SHA actually pulled — this becomes `base_model_revision` in the manifest (`google/gemma-3-4b-it@<sha>`), not just the repo name:

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model_id = "google/gemma-3-4b-it"
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype="bfloat16", device_map="auto")
base_model_revision = f"{model_id}@{model.config._commit_hash}"
```

## 1. Tooling

A LoRA/QLoRA library that runs on a free-tier T4-class GPU — `peft` + `bitsandbytes` (4-bit QLoRA) or `unsloth`. Implementation detail, not locked by the ADR; either works. Examples below use `peft`.

## 2. Data prep — training/serving format match

This is the step most likely to silently break inference later. The training input **must** exactly mirror what `src/llm/generator.py`'s `generate(system, user)` sends at inference time via `create_chat_completion`, and the target **must** exactly mirror what `src/llm/prompt.py`'s `_extract_json` parses back out.

### 2.1 System + user message (copy verbatim from `src/llm/prompt.py`)

```python
SYSTEM = (
    "You are a cognitive-bias detector helping build a candidate list for a later, more "
    "careful review. Read the story and identify every bias that PLAUSIBLY applies — err on "
    "the side of including a bias if there is a reasonable case for it. Choose ONLY from the "
    "provided list of bias_ids, using the exact id. "
    'Respond with STRICT JSON only: an array of bias_id strings, e.g. '
    '["anchoring_bias", "sunk_cost_fallacy"]. No objects, no other fields. '
    "Return [] only if truly nothing in the list plausibly applies. "
    "Output nothing but the JSON array."
)

_EXAMPLE = (
    "\n\nEXAMPLE:\n"
    "bias_ids: sunk_cost_fallacy, anchoring_bias, loss_aversion\n"
    "STORY: Despite losing money every month, Maria keeps the failing shop open because she "
    "already spent her savings renovating it.\n"
    'Correct output: ["sunk_cost_fallacy"]\n'
)

def build_user_message(story: str, catalog_ids: list[str]) -> str:
    ids = ", ".join(catalog_ids)
    return (
        f"{_EXAMPLE}\nNOW YOUR TURN.\nbias_ids: {ids}\n\n"
        f"STORY:\n{story}\n\nReturn the JSON array of bias_id strings now."
    )
```

`catalog_ids` is the same 38-id list `src/llm/prompt.py`'s `load_catalog()` fetches from the DB at the `dataset_version`'s taxonomy version — this notebook has no DB access, so snapshot the exact id list from `scripts/validate_bias_catalog.py`'s output at dataset-freeze time and hardcode it here, noting the taxonomy version it was pulled from. **Do not re-derive or reorder this list from memory** — training on a different id order/set than what production sends is exactly the training/serving mismatch this step exists to prevent.

Snapshot taken at T017's freeze time (`taxonomy_version: "2026-06-28"`, `src/config.py`), alphabetical, 38 ids — use exactly this list and this order unless the live catalog has since changed (re-run `scripts/validate_bias_catalog.py` to check before training if in doubt):

```python
CATALOG_IDS = [
    "affect_heuristic", "ambiguity_effect", "anchoring_bias", "authority_bias",
    "availability_heuristic", "bandwagon_effect", "base_rate_neglect",
    "choice_supportive_bias", "confirmation_bias", "curse_of_knowledge",
    "decoy_effect", "dunning_kruger_effect", "escalation_of_commitment",
    "framing_effect", "fundamental_attribution_error", "gamblers_fallacy",
    "halo_effect", "hindsight_bias", "hot_hand_fallacy", "illusion_of_control",
    "in_group_bias", "loss_aversion", "narrative_fallacy", "negativity_bias",
    "omission_bias", "optimism_bias", "overconfidence_bias", "planning_fallacy",
    "projection_bias", "recency_bias", "representativeness_heuristic",
    "self_serving_bias", "spotlight_effect", "status_quo_bias",
    "stereotyping_bias", "sunk_cost_fallacy", "survivorship_bias", "zero_risk_bias",
]
```

### 2.2 Target serialization — the #1 silent failure mode

Serialize the target as an **actual JSON array string**, matching `_extract_json`'s wire format exactly:

```python
import json
target = json.dumps(sorted(row["bias_ids"]))   # '["anchoring_bias", "sunk_cost_fallacy"]'
# NOT str(row["bias_ids"])                     # "['anchoring_bias', 'sunk_cost_fallacy']" — WRONG, single-quoted Python repr
```

`src/llm/prompt.py`'s `_extract_json` parses for `[`/`]`-delimited **JSON**, not a Python `list` repr. A repr-formatted target trains the model to emit a string its own production parser cannot read — training loss looks completely normal while the fine-tune's effect silently reverts at inference time. Sort the ids for determinism across epochs; parsing doesn't care about order, but reproducible targets make debugging easier.

### 2.3 Chat template + loss masking

Apply Gemma-3's own chat template (`<start_of_turn>`/`<end_of_turn>`) via the tokenizer — training on raw concatenated text teaches a different input distribution than what `create_chat_completion` actually sends:

```python
def build_example(row, catalog_ids, tokenizer):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": build_user_message(row["story"], catalog_ids)},
    ]
    prompt_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    target_text = json.dumps(sorted(row["bias_ids"])) + tokenizer.eos_token

    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    target_ids = tokenizer(target_text, add_special_tokens=False)["input_ids"]

    input_ids = prompt_ids + target_ids
    labels = [-100] * len(prompt_ids) + target_ids  # mask the prompt, train only on the completion
    return {"input_ids": input_ids, "labels": labels}
```

`-100` is the standard PyTorch/HF ignore-index for cross-entropy loss — masking the prompt tokens this way means the model is trained only to produce the JSON-array completion, not to reproduce the prompt it was given.

### 2.4 Validation split

Hold out 10-15% of `sft_dataset.jsonl` (a fixed default; document the exact fraction actually used in the manifest's `lora_hyperparameters.validation_split_fraction`). Use a fixed random seed for reproducibility. A plain random split is sufficient — stratifying by `source`/`group` is not required, but if the split happens to be badly skewed (e.g. validation set ends up with very few `negative` rows), re-seed rather than proceed on a split that isn't representative.

## 3. LoRA configuration

```python
from peft import LoraConfig, get_peft_model

lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    task_type="CAUSAL_LM",
)
peft_model = get_peft_model(model, lora_config)
```

**Verify `target_modules` actually resolved against the base model's real module names before training** — an empty or attention-only match means the adapter trains on close to zero effective parameters despite completing without error, and nothing later in this pipeline catches that on its own:

```python
peft_model.print_trainable_parameters()
matched = {n for n, _ in peft_model.named_modules() if any(t in n for t in lora_config.target_modules)}
assert any("q_proj" in n or "k_proj" in n for n in matched), "attention projections did not resolve"
assert any("gate_proj" in n or "up_proj" in n for n in matched), "MLP projections did not resolve"
```

Record the **resolved** module name list (not just the requested config) in the manifest's `lora_hyperparameters.target_modules` — this is what makes a silent zero-effective-parameter training run detectable after the fact instead of only showing up as an unexplained recall gap at Step 7.

`rank=16`, `alpha=32`, `learning_rate=2e-4`, `epochs_planned=3` are starting defaults (mirrors the illustrative values in `contracts/finetune-manifest-schema.md`), not derived/locked values — adjust based on the validation loss curve, and record whatever was *actually* run (`epochs_run`, `best_checkpoint_epoch`) rather than the plan.

## 4. Training loop — per-epoch validation tracking

Track validation loss after every epoch; save a checkpoint per epoch; keep the **best** checkpoint by validation loss, not the final epoch:

```python
best_val_loss = float("inf")
best_checkpoint_epoch = None

for epoch in range(epochs_planned):
    train_one_epoch(peft_model, train_loader, optimizer)
    val_loss = evaluate(peft_model, val_loader)
    save_checkpoint(peft_model, f"checkpoint-epoch-{epoch}")
    if val_loss < best_val_loss:
        best_val_loss = val_loss
        best_checkpoint_epoch = epoch
    # optional: stop early if val_loss hasn't improved for 1-2 epochs (plateau)

load_checkpoint(peft_model, f"checkpoint-epoch-{best_checkpoint_epoch}")
```

Per ADR-005 §5, `best_checkpoint_epoch` is **not required to equal** `epochs_run` — the whole point of tracking both in the manifest is that they can differ.

## 5. Smoke test — before merging, before evaluating

Run inference on ~20 random training samples using the LoRA-adapted (not yet merged/quantized) model, and manually check the outputs:

```python
for row in random.sample(train_rows, 20):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": build_user_message(row["story"], catalog_ids)},
    ]
    prompt_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    output = generate(peft_model, tokenizer, prompt_text)
    print(row["id"], "->", output)
    # manually confirm: output parses as a JSON array, every id is in catalog_ids
```

A chat-template mismatch, tokenizer issue, or serialization bug can let training "succeed" (loss decreases normally) while the resulting model's actual outputs are garbage. Catching this here costs minutes; catching it only after the full evaluation gate (spec-006 Phase 6) costs a wasted eval cycle and a much harder-to-diagnose failure. Do not proceed to merging until this passes.

## 6. Merge → clear cache → quantize (order matters)

**Correct order: train → merge → clear HF download cache → quantize.** The merge step reads the base checkpoint from the HF download cache — clearing the cache *before* merging deletes an input the merge needs and forces a mid-procedure re-download, the opposite of the intended space saving.

```python
merged_model = peft_model.merge_and_unload()
merged_model.save_pretrained("./merged-checkpoint", safe_serialization=True)
tokenizer.save_pretrained("./merged-checkpoint")
```

```bash
# Only after the merge above has completed and been saved to disk:
rm -rf ~/.cache/huggingface/hub/models--google--gemma-3-4b-it

# Quantize directly from the merged checkpoint — no separate full bf16 save:
python llama.cpp/convert_hf_to_gguf.py ./merged-checkpoint \
  --outfile ./candidate.Q4_K_M.gguf --outtype q4_k_m
```

**Disk note**: peak usage across this step is additive, not just the largest single file — the downloaded HF base checkpoint (~7-8GB) typically coexists on disk with the merged checkpoint (~7-8GB) while GGUF conversion (~2.5GB output) is in progress, a plausible ~18GB simultaneous footprint on a platform that may only offer ~12-15GB free (ADR-005 §5). If tight, quantizing directly from the merged checkpoint (as above, skipping any separate full bf16 export) is the mitigation — not clearing the cache earlier.

Record the exact `quantization_command` used, verbatim and copy-pasteable, in the manifest.

## 7. Write the manifest (T021)

Before proceeding to evaluation (spec-006 Phase 6), write `training/manifests/<candidate_id>.json` per `contracts/finetune-manifest-schema.md` — a candidate with no manifest does not proceed to evaluation. Populate everything except `eval_result` now (dataset version/composition, resolved LoRA hyperparameters, `base_model_revision`, `quantization_command`); `eval_result` is populated by Phase 6's evaluation step via `scripts/check_regression.py`'s `compute_findings()`, imported directly — `[dataclasses.asdict(f) for f in compute_findings(...)]`, never parsed from CLI output.

## 8. Determinism note

Keep `temperature=0.0` when scoring the fine-tuned candidate against the eval harness (Phase 6) — same as every other strategy (ADR-003 §5), for eval comparability.
