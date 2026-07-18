# Fine-Tune Candidate Results — 2026-07-18

**Status**: candidate trained and evaluated, does NOT clear the ship gate as-is. Not promoted, not deployed. This document is both a results record and a self-contained prompt for the next iteration — paste it into a fresh AI session to continue.

---

## 1. What was done

**Governing docs**: `adr/005-fine-tune-engine-llm.md`, `specs/006-fine-tune-llm/{spec.md,plan.md,training/lora_finetune.md}`. Read those for full context; this file summarizes the concrete run.

### Dataset (Phase 4, complete, committed)
- 907 rows: 28 `real_weak` pairs (reconstructed from `biassemble-core`'s production traces) + 879 `synthetic` stories (multi-provider generated: Claude, Qwen, Gemini, Grok, DeepSeek, GPT).
- Labeled by one consistent teacher model (DeepSeek), validated against the live 38-id bias catalog.
- Frozen at `evaluations/sft/sft_dataset.jsonl`, `dataset_version: sha256:73ddf4ca1167fa8ebc105201e78492c7b8cf1440ae77aa7fa8d0c84aa6963b97`.
- Coverage report passes all rules (per-bias floor, group coverage, negative fraction ≥18%, synthetic volume ≥300).

### Training (Phase 5, complete)
- Base: `google/gemma-3-4b-it@093f9f388b31de276ce2de164bdc2081324b9767` (HF, 4-bit QLoRA via `bitsandbytes` — plain fp16 casting caused NaN losses across the 34-layer stack; 4-bit quantized compute was the numerically stable fix).
- LoRA: rank 16, alpha 32, dropout 0.05, `target_modules` scoped via regex to `language_model` only (excludes the vision tower's identically-named `q_proj`/`k_proj`/`v_proj` — Gemma-3-4b-it is the multimodal checkpoint even though this task is text-only). 238 modules matched, 29.8M/4.33B trainable (0.69%).
- Data format: Gemma's own chat template (`apply_chat_template`), loss masked to completion only (`-100` on prompt tokens), target serialized as a real JSON array string (`json.dumps(sorted(bias_ids))`) matching `src/llm/prompt.py`'s exact parser — not a Python list repr. `token_type_ids` explicitly zeroed (Gemma-3's multimodal forward hard-requires this in training mode even with zero images).
- 3 epochs, `per_device_train_batch_size=1`, `gradient_accumulation_steps=16` (effective batch 16), `learning_rate=2e-4`, `fp16=True` (T4 has no bf16 support), `MAX_LENGTH=768` truncation guard.
- Result: `best_checkpoint_epoch=3`, `best_eval_loss=0.1778` (train loss 0.031; epoch 1: 0.194/0.214, epoch 2 ticked up to 0.206/0.312 — noise, not real overfitting, since epoch 3 came back down and beat epoch 1).
- Smoke test: 20 random training-sample generations, 19/20 exact or near-exact match, 20/20 syntactically valid JSON with real catalog ids.

### Packaging (the actual bottleneck — read this before repeating it)
- **Merged-GGUF path failed repeatedly and was abandoned for this candidate.** Root causes, in order hit: (1) `merge_and_unload()` on a bitsandbytes-4bit base left raw packed `uint8`+`.absmax` tensors in the saved checkpoint — llama.cpp's converter can't dequantize bnb's format; fixed by merging into a **fresh, unquantized fp16** copy of the base instead. (2) Kaggle's 20GB disk couldn't hold the ~8.6GB merged checkpoint + a ~7.76GB F16 intermediate GGUF simultaneously — worked around via a Q8_0 intermediate (~4.1GB) instead of F16. (3) The resulting GGUF failed to load in this repo's pinned `llama-cpp-python==0.3.19` runtime — version skew: Kaggle's fresh `llama.cpp` clone (`main`, today) vendors a much newer GGUF/tokenizer-detection implementation than `llama-cpp-python==0.3.19`'s pinned commit (`c0159f9c`, 2026-03-25). Rebuilding `llama.cpp` at that exact commit surfaced a *second* issue: the tokenizer's BPE pre-type hash wasn't recognized at all — because `transformers`' `tokenizer.save_pretrained()` re-serializes `tokenizer.json` with different byte layout than Google's original repo, changing the fingerprint hash `llama.cpp` checks. (4) Kaggle's session repeatedly OOM'd redoing the 8GB merge.
- **Pivot that worked**: convert only the **LoRA adapter** to GGUF (`convert_lora_to_gguf.py`, no base-model merge at all) — 119MB, no OOM risk, no tokenizer-hash risk (adapter carries no tokenizer). Added optional runtime-adapter support to `src/llm/generator.py`/`src/config.py` (`llm_lora_repo`/`llm_lora_file`, default empty — production untouched) so `Llama(..., lora_path=...)` applies the adapter over the existing production base GGUF at load time. This is what was actually evaluated below — **a trial-eval proxy, not the final production artifact**. A proper merged+quantized GGUF still needs to be produced (on a machine with more RAM, or against the exact pinned llama.cpp commit from the start) before this could ship.

### Evaluation (Phase 6, T022 — this is the real result)
Ran `scripts/run_evaluation.py --strategy llm_union` (production base GGUF + adapter) against `evaluations/baselines/baseline_2026-07-17.json` via `scripts/check_regression.py`.

## 2. Results

```
GROUP          METRIC           BASELINE   CURRENT     DELTA  TOLERANCE  ELIGIBLE  RESULT
adversarial    recall_at_k         0.333     0.333    +0.000      0.500        no  reported only (ineligible)
adversarial    precision_at_k      0.200     0.225    +0.025      0.500        no  reported only (ineligible)
blind_spot     recall_at_k         0.325     0.481    +0.156      0.013       yes  pass
blind_spot     precision_at_k      0.128     0.315    +0.187      0.013       yes  pass
edge           recall_at_k         0.750     0.750    +0.000      0.500       yes  pass
edge           precision_at_k      0.400     0.467    +0.067      0.500        no  reported only (ineligible)
negative       empty_rate          0.200     1.000    +0.800      0.200        no  reported only (ineligible)
positive       recall_at_k         0.729     0.667    -0.062      0.250       yes  pass (within noise)
positive       precision_at_k      0.500     0.517    +0.017      0.250       yes  pass
```

`check_regression.py` exit code: 0 (no eligible metric regressed past tolerance).

**Honest read:**
- **`blind_spot` (N=80, the statistically meaningful held-out set)**: Recall@5 +0.156, Precision@5 +0.187 — a real, substantial generalization win. This is the metric this whole feature was built to move, and it moved a lot.
- **`negative` (N=5)**: empty_rate correct-detection jumped 20%→100% — genuine improvement (negative scenarios *should* return empty; it now reliably does).
- **`positive` (N=4)** — the ADR-003 SC-001 hard ship gate (`recall_at_5 ≥ 0.85`): candidate scores **0.667**, below the 0.85 bar and nominally below baseline's 0.729. But N=4 means this is a ~1-scenario swing — not statistically meaningful in either direction. This is exactly the small-N problem `blind_spot` (N=80) exists to solve, and by that lens the fine-tune clearly helped — but the absolute gate, as literally written, is not met.
- **One real concern, not just noise**: `blind_spot` `empty_rate` rose from ~3% to 12% — the model got somewhat more likely to return nothing at all on held-out stories. Worth checking whether this is appropriate caution on genuinely ambiguous stories or under-triggering on real signal.

**Per ADR-005 §6's own rule**: *"Below 0.85 = keep iterating on data, not a judgment call."* This candidate does not ship as-is.

## 3. Proposed improvements for the next iteration

**Priority 1 — more training data, specifically shaped like the `positive` eval group.** The `positive` group's hand-authored scenarios are clear, single-or-dual-bias narrative stories — the current 907-row dataset already targets this shape broadly, but given `positive` is the literal ship-gate metric (however statistically noisy at N=4), the highest-leverage next step is a targeted top-up batch of this exact shape/style, generated and labeled the same way as `b5`/`b6` in this feature's history (`evaluations/staging/sft_raw_batches/`), then retrain.

**Priority 2 — investigate the `blind_spot` empty_rate regression (3%→12%).** Pull the specific blind_spot scenarios that flipped from a real answer to empty and read them — is the model being appropriately conservative, or has training over-taught "when unsure, say no bias"? If the latter, the negative-fraction floor (currently relaxed to 18%) or the training data's edge/negative balance may need rebalancing, not just more volume.

**Priority 3 — training hyperparameters.** Validation loss was still noisy/near its floor at epoch 3 (0.178, only marginally better than epoch 1's 0.194) — worth trying: `warmup_ratio=0.05`, explicit `weight_decay=0.01`, `lr_scheduler_type="cosine"`, and possibly more epochs with `load_best_model_at_end` doing the real work of picking the winner (cheap to try, no reason not to, given `Trainer`'s per-epoch checkpoint-selection safety net).

**Priority 4 — fix the packaging pipeline before the next candidate, don't repeat this saga.** For the next run: merge on a machine with ≥16GB RAM (not Kaggle's ~13GB effective ceiling), and build `llama.cpp` at the **exact** pinned commit (`c0159f9c1f874da15e94f371d136f5920b4b5335`, matching `llama-cpp-python==0.3.19`) from the start — not `main`. Also copy the base model's **original** tokenizer files verbatim into the merged checkpoint rather than letting `transformers.save_pretrained()` re-serialize them, to avoid the BPE pre-tokenizer hash mismatch entirely.

**Priority 5 (bigger, separate conversation, not a data-generation task)** — reconsider whether N=4 is the right size for the `positive` eligible-ship-gate group at all, given `blind_spot` (N=80) now exists and is clearly more statistically trustworthy. That's an ADR-level scope discussion, not something to resolve by quietly overriding the gate.

## 4. What's already true and doesn't need redoing
- Dataset pipeline (T001-T018), training procedure doc (T019), and the actual LoRA training run (T020) are all solid, committed, and reusable. Only the packaging step (merge→GGUF) and the ship-gate data gap need another pass.
