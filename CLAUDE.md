<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
specs/005-ci-metrics-gate/plan.md

Supporting artifacts:
- specs/005-ci-metrics-gate/spec.md — feature specification
- specs/005-ci-metrics-gate/research.md — implementation-level decisions (script boundaries, wheel vs. source build, test placement)
- specs/005-ci-metrics-gate/data-model.md — JSON shapes crossing the CI boundary (no DB changes)
- specs/005-ci-metrics-gate/contracts/check-regression-cli.md — scripts/check_regression.py CLI contract (args, output, exit codes)
- specs/005-ci-metrics-gate/quickstart.md — §6 validation sequence from adr/004, made runnable
- adr/004-ci-metrics-gate.md — accepted decision record (two-tier gate: pytest every push/PR, retrieval-regression gate on PR, weekly production-drift monitor)
- adr/003-generative-llm-bias-selection.md — prior decision (LLM selection; unaffected by this feature)
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

