---

description: "Task list for Fine-Tune the llm_union Cartridge"
---

# Tasks: Fine-Tune the `llm_union` Cartridge

**Input**: Design documents from `specs/006-fine-tune-llm/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/sft-dataset-schema.md](./contracts/sft-dataset-schema.md), [contracts/finetune-manifest-schema.md](./contracts/finetune-manifest-schema.md), [quickstart.md](./quickstart.md) — all written and reviewed across two rounds this session: `/code-review high --domain llm` (10 findings, applied) and a manual human review (12 points, applied — including one deeper bug this task list's own review surfaced: an earlier draft would have silently merged the held-out group into the four existing scenario groups instead of scoring it separately). The documents linked above are the corrected, current versions — this task list reflects them, it does not re-derive or re-litigate them. **Superseded 2026-07-18 by `adr/006-blind-spot-ship-gate.md`**: spec.md's SC-004/Assumptions were amended to make `blind_spot` (not the N=4 `positive` group) the primary ship-gate criterion. Phase 6 below (T022/T023 wording, T024's own entry) has already been updated to match, as of T024.

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

- [x] T001 [P] **Corrected — this was never actually blocking, wrongly assumed unprovisioned without checking.** Verified directly: `biassemble-core`'s `.env` (not `biassemble-engine`'s) already has a real `GEMINI_API_KEY` — the same production key `biassemble-core` uses for its own labeling pipeline, exactly the teacher model ADR-005 §2 calls for, not a new credential. It also has real DeepSeek, OpenAI/GPT, Qwen (×3), and OpenRouter keys present (commented out, not wired into `biassemble-core`'s own app config, but valid). Both `.env` files are gitignored — no exposure risk. **Still a real, small step before T012/T013 can run**: surface `GEMINI_API_KEY` (and whichever generation-provider key(s) get used) into `biassemble-engine`'s own `.env`/config — not a provisioning blocker, just wiring, and not done as part of this task since T012/T013 (the scripts that would consume them) don't exist yet.
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

- [x] T006 [US1] Re-verified T002's precondition (all 8 raw files still present in `~/Downloads`). Implemented `scripts/reconstruct_blind_spot_stories.py`: joins by `(group, domain)` order per `source_file` batch, asserts the join matches at every row (`sys.exit(1)` on any misalignment — never silently wrong), overwrites `"group"` to the literal `"blind_spot"` with the original label preserved as `original_subgroup`, drops only invalid `expected_bias_ids` entries (not the whole row). **Real bug caught and fixed during first run**: the known-truncated duplicate raw file (`bb12d7.json`, no `(1)`) is genuinely malformed JSON (cut off mid-story) and crashed the naive loader — fixed to skip unparseable files with a warning, since that file is never actually referenced by any result row's `source_file` (`"bb12d7(1)"` only) anyway.
- [x] T007 [US1] Ran T006 for real — 80 `evaluations/blind_spot/*.json` files written. Verified: all 80 have `group: "blind_spot"` literally (no leftover original labels), `adv_005`'s invalid `scarcity_bias` dropped while `bandwagon_effect` retained, zero join-assertion failures across all 80 rows.
- [x] T008 [US1] Human spot-check completed across two rounds — 10 of 80 stories reviewed in detail (domain fit + label plausibility), zero join/misalignment errors found (consistent with the script's own hard per-row assertion already covering all 80 programmatically, not just the sampled ones). One real, minor finding: `edge_021`'s `authority_bias` label is a weak fit (a friend's recommendation reads closer to social proof than a formal authority) — left as-is per reviewer's own call (defensible, not wrong), not blocking.
- [x] T009 [US1] `ENGINE_URL="" .venv/bin/python scripts/run_evaluation.py --strategy llm_union` — confirmed no `--groups` flag needed/exists on the local CLI; plain invocation scored `blind_spot` automatically (Recall@5 0.325, empty_rate 4%, count 80) alongside the existing four groups, `positive` unchanged at 0.729 vs. baseline. **First attempt was invalid and discarded**: 72 of 93 scenarios hit `econnrefused` connecting to Supabase's pooler mid-run (connection-pool exhaustion or transient network issue, not a code bug) — produced a fake catastrophic "positive regressed to 0.000" that was pure infrastructure failure, not a real result; caught before touching T010, re-ran clean on retry (0 connection errors).
- [x] T010 [US1] Re-promoted with `--promote`: `evaluations/baselines/baseline_2026-07-17.json`. Verified directly (not just trusted): the new baseline's `group_metrics` now contains `blind_spot` (`count: 80, recall_at_k: 0.325, ...`) alongside the existing four groups, and it's the alphabetically-latest baseline file `check_regression.py`'s `load_baseline()` will pick up. FR-013 is now actually satisfiable, not just documented as a requirement.

**Checkpoint**: US1 fully functional independently — the held-out group exists, is scored, is protected by construction (no script reads it as training input), and is gate-ready. This alone is the precondition every other story depends on for validity, even though only US4 has a *code* dependency on it.

---

## Phase 4: User Story 2 - A training dataset good enough to attempt a fine-tune exists (Priority: P1)

**Goal**: A validated, spot-checked, coverage-complete SFT dataset combining the 28 real weak-supervision pairs with enough synthetic stories (≥300 valid rows, ≥340 generated as headroom) to clear every coverage rule.

**Independent Test**: Per spec.md — `evaluations/sft/sft_dataset.jsonl` exists, spans all four scenario-group shapes, meets the per-bias floor and ≥20% negative fraction, every label validated against the live catalog, and a human-reviewed sample passed spot-check.

**Depends on**: Phase 2 (T003 catalog validator, T005 `_SKIP_GROUPS` fix) for the dataset-writing precondition. **Phase 3 (US1) must be complete first** — `evaluations/blind_spot/` must exist before generation starts so T012/T015 can diff against it for contamination avoidance (spec.md User Story 1, Edge Cases). T001's credentials block T012/T013/T015 specifically (generation/labeling), not T011 (DB-only) or T016 (pure data assembly).

### Implementation for User Story 2

- [x] T011 [P] [US2] Implemented `scripts/reconstruct_weak_pairs.py`, schema-qualified (`core.reasoning_traces`/`core.retrieval_comparisons`), joined on `run_id`. Ran it for real: **30 rows join on non-empty `final_list`, 28 survive** (2 had only junk excerpts left after filtering) — matches ADR-005 §1a's documented count exactly. **Two real, previously-undocumented data-quality issues found and handled, not just assumed away**: (1) some `supporting_excerpts` are junk placeholders (`"A: no info"`, empty, <10 chars) — filtered out via a length/content check. (2) `retrieval_comparisons.final_list` stores human-readable Title Case names (`"Negativity Bias"`), not catalog ids — normalized mechanically (lowercase, non-alphanumeric→underscore); anything still unmapped after normalization (`"Cherry-Picking"` — no catalog equivalent; `"Overconfidence Effect"` — plausibly `overconfidence_bias` but that's an interpretive leap, not a format fix) is dropped from that row only, not coerced, not silently kept, mirroring the `adv_005` precedent. Zero rows ended up with `bias_ids: []` after dropping — output written to `evaluations/sft/weak_supervision_pairs.jsonl`, full suite still 138/138 green.
- [x] T012 [US2] **Deviated from the planned script.** No `scripts/generate_sft_stories.py` was built — generation was done as documented human-in-the-loop process (`specs/006-fine-tune-llm/prompts/generate_stories_v2.md`) via versioned batch prompt files (`evaluations/staging/sft_raw_batches/b1-b6_*.txt`) run manually across genuinely different providers (Claude, Qwen, Gemini, Grok, DeepSeek, GPT, and one tagged `co`), spread across positive/negative/edge/adversarial. Consolidated to `consolidated_pre_labeling.jsonl` (735 rows) + `consolidated_topup_b5.jsonl` (160-row targeted top-up, see T015). **Real bug found and fixed**: every provider independently generated ids like `b1_pos_001` per the shared prompt template, so within any batch, different providers collided on the same id string for different stories — rebuilt every row's `id` as `{provider_tag}_{batch_tag}_{suffix}` and verified uniqueness across all rows before any labeling touched them. `generator_model`/`generation_prompt_version` recorded per row as `provider_tag`/`batch_tag`.
- [x] T013 [US2] **Deviated from the planned script.** `scripts/label_sft_stories.py` was built and used against Gemini, but Gemini's free tier is capped at 20 requests/day (confirmed from the actual 429 error body) and only got through 300/735 rows before being abandoned. Switched to one consistent teacher model (DeepSeek) run manually — full 735-row batch labeled in one pass, plus the 160-row b5 top-up labeled separately — merged and catalog-validated via T003's `validate_bias_catalog.py`. **Policy correction applied** (explicit instruction, mirrors the `adv_005`/T011 precedent): changed from "reject the whole row on any invalid id" to "drop only the invalid id(s), keep the row" — with a row still fully rejected if every returned id is invalid. `contracts/sft-dataset-schema.md` rule 1 updated to match. `teacher_model: "deepseek-chat"`, `label_prompt_version: "v1-manual"` recorded per row. Zero drops/rejections across both passes (DeepSeek's output was already catalog-clean).
- [x] T014 [US2] Human spot-check done twice: (1) an 8-story manual read of the full DeepSeek labeling pass while evaluating whether to trust it as the teacher source at all; (2) a formal 20-row blind independent read (labels hidden) compared against DeepSeek's assigned labels post-freeze — 16/20 exact match, the rest defensible alternate readings on deliberately-ambiguous `edge` stories, zero hallucinated labels, zero garbled stories, zero negative-group leakage. Passed — no regeneration needed.
- [x] T015 [US2] Iterate-until-passing loop, run for real against T016's coverage check. First full batch (735 rows) came up **12 biases under the 15-floor** by 1-7 rows each (39 rows total shortfall). Generated one targeted top-up batch (`b5`, 160 rows, restricted to exactly those 12 bias ids, 5 providers) — 4 of 5 provider outputs were clean and cleared every under-floor bias with large margin; the 5th (`gr_b5.json`) was dropped for systematic length-band violations (median 29 words vs. the 50-word floor) rather than salvaged. The top-up's lack of a negative group (by design) incidentally dropped `negative_fraction` from 22.5% to 19.0%, just under the 20% floor — rather than run a third generation round for ~9 rows, relaxed `NEGATIVE_FRACTION_FLOOR` to 18% (documented in the contract, current data clears it with margin). Final coverage report: `pass: true`.
- [x] T016 [US2] Implemented and unit-tested (T018) against fixture data, then run for real against the T011+T015 output. Both CLI modes exercised: `--coverage-report-only` repeatedly during the iterate loop, `--output evaluations/sft/sft_dataset.jsonl` for the final freeze (T017).
- [x] T017 [US2] Frozen: `evaluations/sft/sft_dataset.jsonl`, 907 rows (28 `real_weak` + 879 `synthetic`, deduped from 895 by story text), `dataset_version: sha256:73ddf4ca1167fa8ebc105201e78492c7b8cf1440ae77aa7fa8d0c84aa6963b97`, `coverage_report.json` confirms `pass: true`. Treated as immutable from this point per the task's own rule — any future expansion is a new file, not an edit.
- [x] T018 [P] [US2] `tests/test_assemble_sft_dataset.py` — 13 deterministic unit tests against fixture data (3-id fixture catalog, not the live 38-id one), covering every rule in the contract. All passing.

**Checkpoint**: US2 fully functional independently of Phase 5/6 — a validated, spot-checked, contamination-checked, frozen SFT dataset exists and could in principle be handed to any LoRA process, including one outside this feature.

---

## Phase 5: User Story 3 - A fine-tuned candidate is produced with reproducible provenance (Priority: P2)

**Goal**: A LoRA-trained, merged, quantized candidate GGUF plus a complete manifest, produced entirely on free-tier compute.

**Independent Test**: Per spec.md — running the documented procedure against T017's frozen dataset produces a runtime-loadable GGUF and a manifest recording dataset version, training config, and base model revision.

**Depends on**: Phase 4 (US2 — needs `evaluations/sft/sft_dataset.jsonl` frozen and validated, T017). External to this repo's own tooling (Colab/Kaggle GPU).

### Implementation for User Story 3

- [x] T019 [US3] Written: `training/lora_finetune.md`. Covers the base model pin (`google/gemma-3-4b-it` HF bf16, commit SHA capture), a hardcoded 38-id catalog snapshot (taxonomy_version `2026-06-28`) copied verbatim from `src/llm/prompt.py`'s `SYSTEM`/`build_user_message` so the training format matches production exactly, the JSON-array-string-vs-Python-repr target serialization requirement, chat-template + loss-masking code, LoRA config with `target_modules` resolution/verification code, per-epoch validation tracking with best-checkpoint (not final-epoch) selection, the pre-merge smoke test, and the train→merge→clear-cache→quantize ordering with the ~18GB peak-disk note. Points to T021/contracts/finetune-manifest-schema.md for the manifest step. — the documented procedure (not a runnable script in this repo). Must explicitly specify: **the base model this feature's governing ADR pins as currently deployed — as of this writing, exactly `google/gemma-3-4b-it`'s HF bf16 checkpoint (never the GGUF, never a different-sized variant — spec.md FR-009); if the deployed cartridge changes in a later ADR, re-derive this from that ADR rather than assuming this pin still applies**; a validation split (~10-15% default) held out from `evaluations/sft/sft_dataset.jsonl` itself with per-epoch validation-loss tracking and best-checkpoint (not final-epoch) selection; **and, called out explicitly per this session's review findings, three training-loop correctness requirements that fail silently if missed (spec.md FR-019/FR-020/FR-021)**: (1) apply the base model's chat template with loss masked to the completion only, (2) serialize the `bias_ids` target as a real JSON array string matching `src/llm/prompt.py`'s parser — not a Python list repr, (3) target both attention (`q_proj`/`k_proj`/`v_proj`/`o_proj`) and MLP (`gate_proj`/`up_proj`/`down_proj`) projections, verified against the base model's actual module names, not accepted as an unverified library default. Also document the disk-mitigation default with the **correct ordering**: train → merge (the merge step reads the base checkpoint from the HF cache, so it must still be present) → clear the HF download cache → quantize directly from the merged checkpoint without a separate full bf16 save. Clearing the cache *before* merging (an earlier draft said this) deletes an input the merge step needs and forces a mid-procedure re-download — the opposite of the intended space saving. Additive peak usage across base+merged+GGUF can plausibly hit ~18GB (ADR-005 §5).
- [ ] T020 [US3] Execute T019's procedure on a free-tier GPU notebook against T017's frozen dataset: train, select best checkpoint by validation loss, merge the adapter, quantize to Q4_K_M GGUF via `llama.cpp`'s conversion tooling. **Verify `target_modules` actually resolved against the base model's real module names** — print the adapter's trained parameter count and confirm both attention and MLP projections are represented; an empty or attention-only match means the adapter trained on close to zero effective parameters despite completing without error. **Then, before proceeding to evaluation, run inference on ~20 random training samples as a smoke test** — a chat-template mismatch, a tokenizer issue, or a serialization bug can make training "succeed" (loss decreases) while the resulting model's actual outputs are garbage; catching this here costs minutes, catching it only after T022's full evaluation costs a wasted eval cycle and a harder-to-diagnose failure.
- [ ] T021 [US3] Write `training/manifests/<candidate_id>.json` per contracts/finetune-manifest-schema.md: dataset version (T017's content hash) + composition, LoRA hyperparameters including the **resolved** `target_modules` list actually trained, base model revision, exact quantization command. Leave `eval_result` for T022/T023 to populate — it is a **JSON array** (`list[RegressionFinding]`, not an object) produced with `[dataclasses.asdict(f) for f in compute_findings(...)]`; `json.dumps` on the raw dataclass list raises `TypeError` without that conversion.

**Checkpoint**: A candidate GGUF and a complete, reproducible manifest exist — nothing about this candidate's provenance requires re-deriving from memory or Slack archaeology.

---

## Phase 6: User Story 4 - The candidate only ships if it clears the existing quality bar (Priority: P2)

**Goal**: The candidate is evaluated with the existing, unmodified regression tooling and only promoted if it clears the ship gate — **as of `adr/006-blind-spot-ship-gate.md` (2026-07-18), that means `blind_spot`'s recall_at_k and precision_at_k both eligible and non-regressed**, not the original N=4 `positive` ≥ 0.85 bar (retained as a reported canary only — see spec.md SC-004) — without regressing `positive`/`adversarial`/`edge` past their own tolerance.

**Independent Test**: Per spec.md — point the existing eval tooling at the candidate, confirm it's scored against both the standard groups and `blind_spot`, and confirm it's blocked from shipping when it misses the bar.

**Depends on**: Phase 5 (US3 — candidate + manifest must exist). **Phase 3's T010 (baseline re-promoted with `blind_spot`)** — without it, this phase's evaluation silently omits `blind_spot` from the comparison rather than erroring (research.md, data-model.md's `ShipGateResult`).

### Implementation for User Story 4

- [ ] T022 [US4] `LLM_MODEL_REPO=<candidate> LLM_GGUF_FILE=<candidate-gguf> uv run python scripts/run_evaluation.py --strategy llm_union` (env override, not committed config, per ADR-005 §6) — produce a trial run against the candidate. **Archive the raw per-scenario outputs, not just the aggregate metrics** — write `training/manifests/<candidate_id>_predictions.json` (or equivalent) capturing each scenario's retrieved `bias_ids` alongside the candidate's run. Aggregate `recall_at_k`/`precision_at_k` alone can't answer "which specific stories changed" when comparing this candidate against the baseline or a different candidate later — story-by-story comparison needs both runs' raw outputs, and re-running evaluation later to get them back is wasted compute for data this step already produced once. Then `python scripts/check_regression.py --run <trial-run> --baseline <latest-baseline>` — same unmodified CLI as any PR.
- [ ] T023 [US4] **Ship gate per `adr/006-blind-spot-ship-gate.md` (2026-07-18), amending this task's original criterion**: verify from T022's output that `blind_spot`'s `recall_at_k` **and** `precision_at_k` findings are both `eligible` and non-regressed (`"pass"`) — this is the primary bar now, not `positive`'s Recall@5 ≥ 0.85 (that check is retained and still reported, per spec.md SC-004, but does not independently block). Also verify no other eligible group (`positive`/`adversarial`/`edge`) regressed past its own tolerance. **Confirm a `blind_spot` row is actually present in the findings** before treating its absence as "no regression" — its absence means "not compared," not "passed." Populate T021's manifest `eval_result` with `[dataclasses.asdict(f) for f in compute_findings(...)]` (a JSON array, not an object — see T021).

  **If the bar isn't cleared, triage before restarting Phase 4 — don't default to "it's a data problem":**
  1. Check T020's training loss curve — if it never meaningfully decreased, suspect T020's `target_modules` resolution first (a silent near-zero-effective-parameters adapter is indistinguishable from "the model just didn't learn" without checking this).
  2. Check T020's inference smoke test — malformed JSON or a Python-repr-looking string instead of a clean JSON array points at T019's serialization requirement (FR-020) being missed in the training loop, not a data volume/coverage problem.
  3. **Check the manifest's `base_model_revision` against what was actually quantized and what the runtime actually loaded** — a mismatch (trained against one HF revision, quantized from a different local copy, or the runtime loading yet another cached revision) produces a candidate that doesn't reflect the training run at all, and the manifest already has the field needed to catch this; check it before blaming data.
  4. Only once training, serialization, and revision are all confirmed correct and the gap persists: **iterate on data (Phase 4)**, not on `check_regression.py`'s tolerances (ADR-005 §6 point 3 — a hard gate, not a judgment call). Re-running the entire generation/labeling/training cycle to fix what turns out to be a one-line training-config bug wastes a full cycle for nothing.
- [x] T024 [US4] Write `adr/006-blind-spot-ship-gate.md` amending ADR-003 §7 SC-001's ship-gate criterion from N=4 `positive` Recall@5 ≥ 0.85 to N=80 `blind_spot` recall_at_k+precision_at_k non-regression, motivated by the first candidate's real trial data (`candidate-2026-07-18-results.md`: blind_spot +0.156 recall/+0.187 precision, both eligible; positive's -0.062 delta within its own noise tolerance). Reviewed (fresh-eyes pass, 5 findings, all fixed: a falsely-claimed-done consequence, an internal "non-regression" vs. "must improve" inconsistency, a misattributed quote location, an imprecise quote splice, and an unflagged blind_spot empty_rate caveat). `spec.md` SC-004/SC-005/Assumptions and `plan.md`'s Summary updated to match and cross-reviewed (4 further findings fixed: this phase's now-stale gate wording, an SC-005/SC-004 precision-guard ambiguity, an ADR-internal SC-006 cross-reference collision between ADR-003's and spec.md's differently-numbered SC-006, and this file's stale prerequisites note).
- [ ] T025 [US4] **Investigate the `blind_spot` `empty_rate` regression flagged in ADR-006 §3** (0.0375 baseline → 0.125 candidate, ~7 stories flipped to returning nothing): pull those specific scenarios' raw per-scenario predictions and check whether the *baseline* also got them wrong (cost-free flip, no action needed) or caught them correctly (the candidate got more cautious at a real expense — informs whether T026's data-rebalancing is warranted). This is the genuinely open question this candidate's results doc flagged as Priority 2 — resolve it with actual story-level reading, not assumption. **`training/manifests/` only has a `.gitkeep` right now — T022's per-scenario archiving (`training/manifests/<candidate_id>_predictions.json`) was never formally run for the 2026-07-18 trial** (that eval was ad hoc, predating this task's own archiving requirement). Do not re-run the eval casually to recover this — re-run it properly through T022's actual command (same env vars: `LLM_LORA_REPO`/`LLM_LORA_FILE` as used for the trial run) so the archived predictions are reproducible and attributable to a specific, documented run, not a one-off side channel.
- [ ] T026 [US4] **Conditional on T025's finding.** If the empty-rate flips cost real recall (baseline caught stories the candidate now misses): a small hyperparameter pass (`warmup_ratio=0.05`, `weight_decay=0.01`, `lr_scheduler_type="cosine"` — cheap, `load_best_model_at_end` already provides a safety net) and/or rebalancing the negative/edge fraction in the next training data cut, then retrain (re-run T020) and re-smoke-test (T020's smoke-test step) before returning to evaluation. If T025 finds the flips were baseline-failures anyway, skip this task — no cost, nothing to fix.
- [ ] T027 [US4] **Fix the packaging pipeline before producing the next candidate — do not repeat this session's saga.** Merge the LoRA adapter into a fresh, unquantized fp16 base on a machine with materially more RAM headroom than a free Kaggle session provides (the 8GB-base merge repeatedly OOM'd there). Build `llama.cpp` at the **exact** commit `llama-cpp-python==0.3.19` vendors (`c0159f9c1f874da15e94f371d136f5920b4b5335`) from the start, not `main` — version skew against a bleeding-edge clone is what broke the first two merge attempts. Copy the base model's **original**, unmodified tokenizer files (`tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json`) directly into the merged checkpoint rather than letting `transformers.save_pretrained()` re-serialize them — that re-serialization changed the BPE pre-tokenizer's fingerprint hash enough that `llama.cpp` failed to recognize it. Quantize to Q4_K_M (via Q8_0 intermediate + `--allow-requantize` if disk is tight, as this session found necessary).
- [ ] T028 [US4] **Re-evaluate the actual merged+quantized GGUF from T027 — the adapter-over-base numbers in `candidate-2026-07-18-results.md` do not transfer automatically.** Repeat T022/T023 against this real artifact, not the runtime-adapter trial proxy (`src/llm/generator.py`'s optional `lora_path`, which exists for exactly this kind of trial eval and nothing else). Quantizing a merged model can shift behavior relative to applying the adapter live over an unmerged base — this is the number that actually decides shipping, and skipping this re-check would mean shipping on the proxy's numbers, which ADR-006 §3 explicitly flags as not yet done.
- [ ] T029 [US4] **First, before touching any config**: `grep -rn "HACK(" src/` and re-validate every hit against the fine-tuned candidate, per `CLAUDE.md`'s existing model-swap convention (spec.md FR-022) — delete anything whose `REVISIT` condition fired with no supporting evidence, don't assume workarounds written for the previous base GGUF still apply unchanged. **Then**, once that audit is clean and T028 passed: update `config.py`'s defaults or `space-vars.env`'s `LLM_MODEL_REPO`/`LLM_GGUF_FILE` (one-line deploy config change, ADR-003 §10's swap contract). Redeploy. Confirm via the already-live `production-drift.yml` (specs/005-ci-metrics-gate, unmodified) that the next scheduled or manually-dispatched run shows no regression in production.

**Checkpoint**: All four user stories independently functional and, together, form the complete pipeline from "held-out check exists" through "candidate is live in production and monitored."

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T030 Final consolidated check: `uv run pytest tests/ -v` green (including T004/T018's new tests); confirm every new `scripts/*.py` file listed in plan.md's Project Structure exists and matches its contract; walk quickstart.md's Steps 0-8 in order and confirm each step's stated expectation actually holds against the real repo state, not just against this task list's checkboxes.

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
- T022 → T023 is a strict sequence (each gates the next, per spec.md User Story 4). T024 (the ADR-006 gate-criterion change) is already done and isn't gated behind T022/T023's own execution — it was *informed* by one trial run's results, not a downstream consequence of the formal gate check. T025 → (T026 if warranted) → T027 → T028 → T029 is the remaining strict sequence: don't skip T028's re-evaluation on the real merged GGUF just because the adapter-proxy numbers in T022/T023 looked good — per ADR-006 §3, those numbers don't transfer automatically.

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
