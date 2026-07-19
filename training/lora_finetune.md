# LoRA Fine-Tune Procedure — `llm_union` Gemma-3-4B Cartridge

**Status**: documented procedure, not a runnable script in this repo (`spec-006` T019). Run this on an external free-tier GPU notebook (Colab/Kaggle, T4-class). Governed by `adr/005-fine-tune-engine-llm.md` §5 — cite that ADR for the *why*, this file is the *how*.

**Input**: `evaluations/sft/sft_dataset.jsonl` (T017, frozen, `dataset_version: sha256:73ddf4ca1167fa8ebc105201e78492c7b8cf1440ae77aa7fa8d0c84aa6963b97`, 907 rows).
**Output**: a merged, quantized Q4_K_M GGUF candidate + `training/manifests/<candidate_id>.json` (T021, contracts/finetune-manifest-schema.md).

---

## 0. Base model pin

Train against the base model this feature's governing ADR pins as currently deployed — as of this writing, exactly:

```
google/gemma-3-4b-it
```

**Never the GGUF** (LoRA cannot train a quantized checkpoint) **and never a different-sized variant** (spec.md FR-009). If the deployed cartridge changes in a later ADR, re-derive this pin from that ADR rather than assuming it still applies.

**Load the base in 4-bit (QLoRA), not plain `bfloat16`/`float16` — this is a requirement, not a style choice.** The first real training run (`specs/006-fine-tune-llm/candidate-2026-07-18-results.md`) loaded the base in plain `float16` and got `nan` training loss across the entire 34-layer stack on a T4 — running this model's full forward/backward pass in raw fp16 (no `bitsandbytes` quantization, no autocast) is numerically unstable regardless of GPU. 4-bit `bitsandbytes` quantization was the fix that actually worked, verified by a pre-flight loss check (§1a below) before committing to a full run:

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

model_id = "google/gemma-3-4b-it"
tokenizer = AutoTokenizer.from_pretrained(model_id)

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,  # T4 (Turing) has no bf16 compute support
    bnb_4bit_use_double_quant=True,
)
model = AutoModelForCausalLM.from_pretrained(model_id, quantization_config=bnb_config, device_map="auto")
base_model_revision = f"{model_id}@{model.config._commit_hash}"
```

## 1. Tooling

`peft` + `bitsandbytes` 4-bit QLoRA, **not "either works"** — this is the specific combination verified to produce a finite, trainable loss on a free-tier T4. `unsloth` may also work but has not been run against this dataset; if used instead, re-verify §1a's pre-flight check before trusting a full run.

Wrap the loaded model with `prepare_model_for_kbit_training` before attaching LoRA — this handles gradient-checkpointing setup and layer-norm upcasting correctly for a quantized base (a manual `gradient_checkpointing_enable()` call alone is not sufficient for a 4-bit model):

```python
from peft import prepare_model_for_kbit_training

model = prepare_model_for_kbit_training(model)
model.gradient_checkpointing_enable()
model.enable_input_require_grads()
```

### 1a. Pre-flight check — confirm the loss is finite before committing to a full run

Run one real example through the model and check `.loss` is a real number, not `nan`, **before** starting the full training loop — this catches a numerical-instability regression in under a second instead of after a wasted multi-epoch run:

```python
check_batch = {k: v.to(peft_model.device) for k, v in collate_fn([train_examples[0]]).items()}
check_out = peft_model(**check_batch)
assert torch.isfinite(check_out.loss), f"loss is {check_out.loss.item()} — stop, do not proceed to training"
```

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
MAX_LENGTH = 768  # defensive cap — see note below

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

    if len(prompt_ids) + len(target_ids) > MAX_LENGTH:
        keep = MAX_LENGTH - len(target_ids)
        assert keep > 0, f"target alone exceeds MAX_LENGTH ({len(target_ids)} tokens) — raise MAX_LENGTH"
        prompt_ids = prompt_ids[-keep:]  # truncate the prompt from the left, never the target

    input_ids = prompt_ids + target_ids
    labels = [-100] * len(prompt_ids) + target_ids  # mask the prompt, train only on the completion
    token_type_ids = [0] * len(input_ids)  # see note below — required, not optional
    return {"input_ids": input_ids, "labels": labels, "token_type_ids": token_type_ids}
```

`-100` is the standard PyTorch/HF ignore-index for cross-entropy loss — masking the prompt tokens this way means the model is trained only to produce the JSON-array completion, not to reproduce the prompt it was given.

**`token_type_ids` is required, not optional, and must be included in every batch (the collator must pad it alongside `input_ids`/`labels`).** `gemma-3-4b-it` is the multimodal checkpoint (see §3 below) — its forward pass hard-requires `token_type_ids` in training mode to distinguish text tokens from image tokens (`token_type_ids == 1` marks an image token), and raises `ValueError: token_type_ids is required as a model input when training` if omitted, even when the batch contains zero images. All-zeros is correct here since this task never feeds an image. `MAX_LENGTH` truncation is a defensive cap discovered necessary when Gemma's large (256k) vocabulary made an unusually long batch spike GPU memory during loss computation — truncating the prompt (never the target, so the label always survives intact) keeps worst-case memory bounded.

### 2.4 Validation split

Hold out 10-15% of `sft_dataset.jsonl` (a fixed default; document the exact fraction actually used in the manifest's `lora_hyperparameters.validation_split_fraction`). Use a fixed random seed for reproducibility. A plain random split is sufficient — stratifying by `source`/`group` is not required, but if the split happens to be badly skewed (e.g. validation set ends up with very few `negative` rows), re-seed rather than proceed on a split that isn't representative.

## 3. LoRA configuration

**`gemma-3-4b-it` is the multimodal checkpoint** (text + a SigLIP-style vision tower under `model.vision_tower`, confirmed directly from the base-model load log: `Materializing param=model.vision_tower.vision_model.post_layernorm.weight`) even though this task is text-only and never feeds an image. The vision tower's own attention blocks also use `q_proj`/`k_proj`/`v_proj` names — a plain substring-matched `target_modules` list would attach LoRA adapters there too, wasting capacity on parameters that never see a gradient signal relevant to this task. **Scope `target_modules` to the language model only.**

First, inspect the real module tree and confirm the two subtrees are actually named the way this section assumes (checkpoint-specific naming can drift between `transformers` versions — don't assume, check):

```python
lang_modules = [n for n, _ in model.named_modules() if "language_model" in n and n.endswith(("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"))]
vision_modules = [n for n, _ in model.named_modules() if "vision_tower" in n and n.endswith(("q_proj", "k_proj", "v_proj"))]
print(f"{len(lang_modules)} language-model target candidates, e.g. {lang_modules[:2]}")
print(f"{len(vision_modules)} vision-tower q/k/v modules that must NOT be targeted, e.g. {vision_modules[:2]}")
```

Then target only the `language_model` subtree, via a regex `target_modules` string (peft matches this against the full dotted module path, not a bare substring) rather than the plain-list form:

```python
from peft import LoraConfig, get_peft_model

lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$",
    task_type="CAUSAL_LM",
)
peft_model = get_peft_model(model, lora_config)
```

**Verify `target_modules` actually resolved against the base model's real module names before training, and confirm the vision tower was correctly excluded** — an empty or attention-only match means the adapter trains on close to zero effective parameters despite completing without error, and a vision-tower match means capacity was wasted on layers this task can't use; nothing later in this pipeline catches either on its own:

```python
peft_model.print_trainable_parameters()
matched = {n for n, m in peft_model.named_modules() if hasattr(m, "lora_A")}
assert any("q_proj" in n or "k_proj" in n for n in matched), "attention projections did not resolve"
assert any("gate_proj" in n or "up_proj" in n for n in matched), "MLP projections did not resolve"
assert not any("vision_tower" in n for n in matched), "LoRA attached to the vision tower — target_modules regex is too broad"
```

Record the **resolved** module name list (not just the requested config) in the manifest's `lora_hyperparameters.target_modules` — this is what makes a silent zero-effective-parameter (or wrongly-vision-scoped) training run detectable after the fact instead of only showing up as an unexplained recall gap at Step 7.

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
    inputs = tokenizer(prompt_text, return_tensors="pt").to(peft_model.device)
    inputs["token_type_ids"] = torch.zeros_like(inputs["input_ids"])  # required — see §2.3
    with torch.no_grad():
        out = peft_model.generate(**inputs, max_new_tokens=100, do_sample=False)
    output = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    print(row["id"], "->", output)
    # manually confirm: output parses as a JSON array, every id is in catalog_ids
```

A chat-template mismatch, tokenizer issue, or serialization bug can let training "succeed" (loss decreases normally) while the resulting model's actual outputs are garbage. Catching this here costs minutes; catching it only after the full evaluation gate (spec-006 Phase 6) costs a wasted eval cycle and a much harder-to-diagnose failure. Do not proceed to merging until this passes.

## 6. Merge → clear cache → quantize (order matters — and three real traps found in the first run)

**Do not call `.merge_and_unload()` directly on the 4-bit `peft_model` from §1/§1a.** The first real run tried this and produced a checkpoint that *looked* merged but whose tensors were still raw packed 4-bit `uint8` + separate `.absmax` scale tensors — `llama.cpp`'s converter cannot dequantize `bitsandbytes`' format and fails with `NotImplementedError: Quant method is not yet supported: 'bitsandbytes'`. **Merge into a fresh, separately-loaded plain-`fp16` copy of the base instead** — a clean float addition with no quantization involved:

```python
from transformers import AutoModelForCausalLM
from peft import PeftModel

# Save the adapter alone first (small, ~100-150MB) — this is the artifact that actually
# matters if anything below goes wrong; everything past this point is reproducible from it.
peft_model.save_pretrained("./final-lora-adapter")
tokenizer.save_pretrained("./final-lora-adapter")

fresh_base = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype="float16", device_map="cpu")
merge_model = PeftModel.from_pretrained(fresh_base, "./final-lora-adapter")
merged_model = merge_model.merge_and_unload()
merged_model.save_pretrained("./merged-checkpoint", safe_serialization=True)
```

**Copy the base model's *original* tokenizer files in verbatim — do not call `tokenizer.save_pretrained()` on the merged checkpoint.** `transformers` re-serializes `tokenizer.json` with a different byte layout than Google's original repo, which changes the BPE pre-tokenizer's fingerprint hash; `llama.cpp`'s converter either misidentifies it as a wrong, unrelated tokenizer (silently wrong) or refuses outright with `NotImplementedError: BPE pre-tokenizer was not recognized`, depending on version. Fix: copy Google's original files in place of whatever `transformers` would write:

```python
from huggingface_hub import snapshot_download
import shutil, os

tok_dir = snapshot_download(model_id, allow_patterns=["tokenizer*", "special_tokens_map.json"])
for f in os.listdir(tok_dir):
    if f.startswith("tokenizer") or f == "special_tokens_map.json":
        shutil.copy(os.path.join(tok_dir, f), f"./merged-checkpoint/{f}")
```

**Build/use `llama.cpp` at the exact commit this repo's `llama-cpp-python==0.3.19` vendors, not `main`.** A fresh `git clone` of `main` on a notebook is several months ahead of what this repo's pinned runtime can actually load — the first run's candidate GGUF, built from a fresh `main` clone, failed to load in this repo's runtime entirely. The correct commit:

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp && git fetch --depth 1 origin c0159f9c1f874da15e94f371d136f5920b4b5335 && git checkout c0159f9c1f874da15e94f371d136f5920b4b5335
cmake -B build . -DGGML_CUDA=OFF && cmake --build build --config Release -j --target llama-quantize
cd ..
```
(Re-derive this commit if `llama-cpp-python`'s pinned version in `pyproject.toml` ever changes — don't assume `c0159f9c` stays correct forever: `gh api repos/abetlen/llama-cpp-python/contents/vendor?ref=v<version>` returns it.)

**Correct order from here: clear HF download cache → convert → quantize.** The merge above already completed and saved to disk, so the cache is no longer needed as a merge input (unlike a same-session merge-then-immediately-quantize flow, where clearing too early forces a re-download mid-procedure):

```bash
rm -rf ~/.cache/huggingface/hub/models--google--gemma-3-4b-it

# NOTE: this llama.cpp version's convert_hf_to_gguf.py does NOT accept --outtype q4_k_m
# directly (only f32/f16/bf16/q8_0/tq1_0/tq2_0/auto) — convert to Q8_0 first, then
# requantize down. Q8_0 is also ~half the size of an F16 intermediate, which matters on a
# disk-constrained free-tier session (F16 + the merged checkpoint together can exceed a
# 20GB session disk; Q8_0 + the merged checkpoint fits comfortably).
python llama.cpp/convert_hf_to_gguf.py ./merged-checkpoint --outfile ./candidate-q8_0.gguf --outtype q8_0
rm -rf ./merged-checkpoint  # no longer needed once the GGUF exists — free the space

# llama-quantize refuses to requantize an already-quantized file by default; --allow-requantize
# overrides that (small, expected quality cost vs. quantizing from F16, not worth the extra
# disk pressure of keeping an F16 intermediate around instead of Q8_0):
./llama.cpp/build/bin/llama-quantize --allow-requantize ./candidate-q8_0.gguf ./candidate.Q4_K_M.gguf Q4_K_M
```

**Disk note**: peak usage across this step is additive, not just the largest single file — the merged checkpoint (~8GB) and the intermediate GGUF coexist on disk until the merged checkpoint is deleted (above). On a ~20GB free-tier session disk, this is tight but workable with the Q8_0 intermediate; it was not workable with an F16 intermediate (~7.76GB), which is why Q8_0 is the default here rather than F16.

Record the exact `quantization_command` used, verbatim and copy-pasteable, in the manifest.

**Verify the resulting GGUF actually loads in this repo's runtime before trusting it as a candidate** — none of the above guarantees it did; the fastest check is pointing `scripts/run_evaluation.py` at it (Phase 6) and confirming the model loads rather than raising `ValueError: Failed to load model from file`.

## 7. Write the manifest (T021)

Before proceeding to evaluation (spec-006 Phase 6), write `training/manifests/<candidate_id>.json` per `contracts/finetune-manifest-schema.md` — a candidate with no manifest does not proceed to evaluation. Populate everything except `eval_result` now (dataset version/composition, resolved LoRA hyperparameters, `base_model_revision`, `quantization_command`); `eval_result` is populated by Phase 6's evaluation step via `scripts/check_regression.py`'s `compute_findings()`, imported directly — `[dataclasses.asdict(f) for f in compute_findings(...)]`, never parsed from CLI output.

## 8. Determinism note

Keep `temperature=0.0` when scoring the fine-tuned candidate against the eval harness (Phase 6) — same as every other strategy (ADR-003 §5), for eval comparability.
