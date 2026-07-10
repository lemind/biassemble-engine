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

