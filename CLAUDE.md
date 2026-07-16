<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
specs/006-fine-tune-llm/plan.md

Supporting artifacts:
- specs/006-fine-tune-llm/spec.md — feature specification
- specs/006-fine-tune-llm/research.md — implementation-level decisions (blind-spot story reconstruction, test boundary, training/ directory placement)
- specs/006-fine-tune-llm/data-model.md — new file-based data shapes (weak-supervision pairs, SFT dataset rows, fine-tune manifest)
- specs/006-fine-tune-llm/contracts/sft-dataset-schema.md — evaluations/sft/sft_dataset.jsonl row contract
- specs/006-fine-tune-llm/contracts/finetune-manifest-schema.md — training/manifests/<candidate_id>.json contract
- specs/006-fine-tune-llm/quickstart.md — ADR-005 §7 task list, made runnable
- adr/005-fine-tune-engine-llm.md — accepted-pending decision record (LoRA fine-tune of llm_union's Gemma-3-4B cartridge)
- specs/005-ci-metrics-gate/plan.md — prior feature's plan (CI regression gate this feature's ship decision reuses unchanged)
- adr/004-ci-metrics-gate.md — prior decision (two-tier CI gate; check_regression.py reused as-is by this feature)
- adr/003-generative-llm-bias-selection.md — prior decision (LLM selection; llm_union is the strategy being fine-tuned)
- adr/002-nli-zero-shot-shortlist.md — prior decision (NLI; superseded as production default by ADR-003)
- adr/001-vector-search-retrieval.md — baseline decision record (retroactive)
- specs/004-add-llm-model/plan.md — prior feature's plan (LLM selection strategy; unaffected by this feature)
- specs/001-rag-retrieval/contracts/retrieve-biases.md — POST /retrieve-biases contract (v1, unchanged)
- specs/001-rag-retrieval/contracts/health.md — GET /health contract (unchanged)
- specs/001-rag-retrieval/contracts/stats.md — GET /stats contract (unchanged)
- specs/001-rag-retrieval/python-patterns.md — Python patterns reference
<!-- SPECKIT END -->

## Conventions

**Commit messages**: `feat|fix|chore(T0XX): <short description>`. Omit the task ref when there is no associated task.

**Hack tagging**: code whose existence is justified by a specific model/environment quirk (not general correctness) must be tagged inline, right above it:

```
# HACK(<scope>): <OBSERVED w/ citation, or SPECULATIVE — say which>. See <doc path>.
# REVISIT: <condition that should trigger re-checking or deleting this>.
```

Before swapping the model behind any `SELECTION_STRATEGY` (ADR-003) or otherwise changing runtime model/environment assumptions, `grep -rn "HACK(" src/` and re-validate every hit against the new reality — delete anything whose REVISIT condition fired with no evidence to back it up.

Do not keep unverified defensive code around as "cheap insurance" without this tag — untagged speculative branches accumulate silently and nobody re-checks them when the thing they were guarding against changes. Example: `src/llm/prompt.py`'s `_validate_schema` used to accept a legacy `{"bias_id": ..., "confidence": ...}` object form "in case the model drifts from the requested bare-array format." That tolerance was actually carried over from a *different* model's *different* bug (Qwen raw-completion garbage, fixed by switching to the chat template — research.md#L101) and was never observed with the deployed model/prompt. Removed 2026-07-13 rather than relabeled, once traced back to zero supporting evidence.

