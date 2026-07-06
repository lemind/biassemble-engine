<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
specs/003-nli-zero-shot-shortlist/plan.md

Supporting artifacts:
- specs/003-nli-zero-shot-shortlist/spec.md — feature specification
- specs/003-nli-zero-shot-shortlist/research.md — technical decisions and rationale
- specs/003-nli-zero-shot-shortlist/data-model.md — new entities and config (no DB changes)
- specs/003-nli-zero-shot-shortlist/contracts/retrieve-biases-v2.md — additive contract changes
- adr/002-nli-zero-shot-shortlist.md — accepted decision record (prompt-ADR, paste into sessions)
- adr/001-vector-search-retrieval.md — baseline decision record (retroactive)
- specs/001-rag-retrieval/contracts/retrieve-biases.md — POST /retrieve-biases contract (v1, unchanged)
- specs/001-rag-retrieval/contracts/health.md — GET /health contract (unchanged)
- specs/001-rag-retrieval/contracts/stats.md — GET /stats contract (unchanged)
- specs/001-rag-retrieval/python-patterns.md — Python patterns reference
<!-- SPECKIT END -->

## Conventions

**Commit messages**: `feat|fix|chore(T0XX): <short description>`. Omit the task ref when there is no associated task.

