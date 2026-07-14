<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
specs/004-add-llm-model/plan.md

Supporting artifacts:
- specs/004-add-llm-model/spec.md — feature specification
- specs/004-add-llm-model/research.md — technical decisions and rationale
- specs/004-add-llm-model/data-model.md — config, response field, provenance (no DB changes)
- specs/004-add-llm-model/contracts/retrieve-biases-v3.md — additive contract changes (source field, llm_union)
- specs/004-add-llm-model/quickstart.md — spike-first run/validation guide
- adr/003-generative-llm-bias-selection.md — accepted decision record (prompt-ADR, paste into sessions)
- adr/002-nli-zero-shot-shortlist.md — prior decision (NLI; superseded as production default by ADR-003)
- adr/001-vector-search-retrieval.md — baseline decision record (retroactive)
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

