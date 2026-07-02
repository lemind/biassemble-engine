# Implementation Plan: Taxonomy Retrieval Improvement

**Branch**: `002-improve-taxonomy-retrieval` | **Date**: 2026-07-02 | **Spec**: [spec.md](spec.md)

## Summary

Improve bias retrieval coverage by rewriting all 38 knowledge files' indicator sections from analytical observer language into behavioral and reasoning patterns, splitting all chunk types into atomic per-unit vectors, and adding evaluation-driven domain examples to fill identified coverage gaps. The evaluation pipeline is extended with a diagnostics mode and two new utility scripts (cosine delta probe, threshold sweep). A conditional Phase 5 adds `observable_patterns` chunks if the adversarial group remains at zero recall after Phases 1–4.

## Technical Context

**Language/Version**: Python 3.11 (deploy target via Dockerfile). Local dev environment uses Python 3.14 — a three-minor-version gap that risks dataclass, typing, and asyncio behaviour differences. Pin local dev to 3.11 via `.python-version` file (`3.11`) and `requires-python = ">=3.11,<3.12"` in `pyproject.toml`. Do not develop on an interpreter that doesn't match the deploy target.

**Primary Dependencies**: sentence-transformers (`all-MiniLM-L6-v2`), asyncpg, pgvector, pytest — no new dependencies introduced by this feature

**Storage**: `bias_embeddings` table in Supabase (pgvector). No schema changes. New chunk structure produces ~380 rows per full index (was 190) — exact scan remains appropriate; no IVFFlat needed.

**Testing**: pytest — existing test suite; `test_chunk_builder.py` and `test_normalizer.py` receive new cases for splitting and domain tag extraction

**Target Platform**: HuggingFace Spaces (Linux container) — unchanged

**Project Type**: Data pipeline + web service — this feature primarily changes the data pipeline (TaxonomySource, chunk_builder) and knowledge file content

**Performance Goals**: Chunk count ~380 rows — exact scan at <1ms. No impact on retrieval latency.

**Constraints**: 256-token model limit per chunk — paragraph splitting must stay within this. Domain label prefix is stripped before embedding; no token budget wasted.

**Scale/Scope**: 38 knowledge files × ~10 chunks each ≈ 380 rows per index version

**Package Manager**: uv

**Linting / Type checking**: Ruff + mypy

## Constitution Check

Constitution template not yet filled — no gates defined. Proceeding without gate violations.

Post-design review: no patterns introduced that conflict with simplicity, observability, or testability principles. Changes are contained to the indexing pipeline and knowledge file content. API surface is unchanged.

## Project Structure

### Documentation (this feature)

```text
specs/002-improve-taxonomy-retrieval/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── checklists/
│   └── requirements.md
└── tasks.md             ← /speckit-tasks output
```

No contracts/ — this feature introduces no new API endpoints or external interface changes.

### Source Code changes

```text
biassemble-engine/
├── knowledge/
│   ├── STYLE_GUIDE.md               # updated: authoring principle + before/after examples
│   └── *.md (38 files)              # indicator rewrites; new domain paragraphs (Phase 4);
│                                    #   observable patterns section (Phase 5, conditional)
├── src/
│   ├── schemas/
│   │   └── internal.py              # CHUNK_TYPE_OBSERVABLE_PATTERNS added (Phase 5 conditional)
│   ├── indexing/
│   │   ├── sources/
│   │   │   ├── base.py              # RawDocument: add paragraph_index field
│   │   │   └── taxonomy.py          # _parse(): paragraph splitting, domain label extraction
│   │   └── chunk_builder.py         # indicator grouping; chunk_index formula; propagate paragraph_index
│   └── evaluation/
│       └── evaluate.py              # ScenarioResult: add retrieved_with_diagnostics field
├── scripts/
│   ├── probe_chunk.py               # new: cosine delta probe (no DB)
│   └── tune_threshold.py            # new: threshold sweep against negative group
└── tests/
    ├── test_chunk_builder.py        # new cases: paragraph splitting, indicator grouping, domain tags
    └── test_normalizer.py           # new cases: domain label extraction
```

## Assessment-Level Validation (final step)

After all retrieval phases complete, run biassemble-core's assessment evaluation against the new index and confirm:
- Assessment FP rate does not degrade from pre-feature baseline
- `evidence_grounded_rate` does not degrade from pre-feature baseline

This is SC-008 from the spec. Retrieval improvement that degrades assessment quality is not a net improvement. This step is the ground truth for whether the feature succeeded.

## Complexity Tracking

No constitution violations — no complexity justification required.
