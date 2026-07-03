# Tasks: Taxonomy Retrieval Improvement

**Input**: Design documents from `specs/002-improve-taxonomy-retrieval/`

**Format**: `[ID] [P?] [Story?] Description`
- **[P]**: parallelisable (no dependency on incomplete task)
- **[Story]**: user story label — US1 through US5

**Date convention**: `YYYY-MM-DD` in version strings and file paths is substituted with the actual current date at execution time (e.g., if work begins on 2026-07-02, `YYYY-MM-DD.1` becomes `2026-07-02.1`).

---

## Phase 0: Setup

**Purpose**: Tooling and environment prerequisites needed before content or code work begins.

- [x] T001 Bootstrap probe script, pin Python version, and verify index type — create `scripts/probe_chunk.py` (takes `--story`, `--old`, `--new`; embeds all three via `SentenceTransformerProvider`; prints cosine scores and delta; no DB connection); add `.python-version` file containing `3.11`; add `requires-python = ">=3.11,<3.12"` to `pyproject.toml`; **verify no IVFFlat index** on `bias_embeddings` by querying `SELECT indexname FROM pg_indexes WHERE tablename = 'bias_embeddings' AND indexname LIKE '%embedding%'` — if one is found, drop it before proceeding (exact scan is required for all subsequent eval numbers to be meaningful; IVFFlat introduces approximation error that would invalidate phase comparisons)

**Checkpoint**: ✅ `probe_chunk.py` runs correctly — example output: `old: 0.019 / new: 0.162 / delta: +0.143 IMPROVED`. ✅ DB query confirms no vector index on `bias_embeddings` — all indexes are btree/GIN on non-embedding columns; exact scan confirmed. **Note**: use `.venv/bin/python` directly instead of `uv run` — the system SOCKS proxy (`ALL_PROXY=socks://...`) causes `uv run` to hang; `probe_chunk.py` clears proxy env vars internally before importing httpx-dependent libraries.

---

## Phase 1: Indicator Rewrites [US1]

**Goal**: All 38 bias `## Indicators` sections rewritten in behavioral, observable, and first-order reasoning language. For biases implicated in current failures, delta probe confirms improvement. For all others, full eval shows no regressions.

**Independent Test**: Run `scripts/probe_chunk.py` on any rewritten indicator for a failing story — `new > old`. Run full eval at `YYYY-MM-DD.1` — positive group Recall@5 ≥ 0.667, negative empty_rate = 100%.

- [x] T002 [US1] Rewrite all 38 `## Indicators` sections in `knowledge/*.md` — replace analytical observer language with behavioral, observable, and first-order reasoning patterns following `knowledge/STYLE_GUIDE.md`; use `scripts/probe_chunk.py` to validate improvements for biases in current failures (`confirmation_bias`, `overconfidence_bias`, `framing_effect`, `availability_heuristic`, `affect_heuristic`) before committing; **commit the knowledge file changes separately from indexing steps** (one commit for the 38 rewritten files, one for the reindex result in `.env`); bump `TAXONOMY_VERSION=YYYY-MM-DD.1` in `.env`; run `uv run python scripts/run_indexing.py`; run `uv run python scripts/run_evaluation.py` and verify SC-001 (edge recall improves), SC-003 (positive recall ≥ 0.667), SC-004 (negative empty_rate = 100%); promote to baseline with `--promote` (flag exists in `scripts/run_evaluation.py` from spec 001)

**Checkpoint**: Eval run at `YYYY-MM-DD.1` shows no regressions. Promoted to baseline.

---

## Phase 2: Chunk Splitting Infrastructure [US2]

**Goal**: All chunk types split into atomic per-unit vectors. Each example paragraph is its own chunk. Indicators grouped into 2–3 thematic clusters. Index rebuilt. Threshold recalibrated.

**Independent Test**: Reindex at `YYYY-MM-DD.2`, run threshold sweep, confirm negative empty_rate = 100% at new threshold. Run full eval — positive Recall@5 does not decrease from `YYYY-MM-DD.1` baseline.

- [x] T003 [US2] Implement paragraph splitting and indicator grouping in the indexing pipeline — complete in this order with intermediate commits:

  **[x] Step A — Code + tests** *(commit after this step)*:
  Add `paragraph_index: int = 0` to `RawDocument` in `src/indexing/sources/base.py`; update `TaxonomySource._parse()` in `src/indexing/sources/taxonomy.py` to split examples on `\n\n`, extract `[Domain]` labels using `_DOMAIN_RE = re.compile(r"^\[([A-Za-z]+)\]\s*")` (single-word only — per `knowledge/STYLE_GUIDE.md` controlled vocab; multi-word labels like `Everyday Social` are invalid), strip labels from chunk text, and set `paragraph_index`; add `_group_indicator_bullets()` to `src/indexing/chunk_builder.py` using `\b`-bounded regex (not substring `in`), grouping into reasoning/behavioral/verbal clusters with distribution warning when any group exceeds 80%; update `chunk_index` formula to `section_base * 100 + paragraph_index` with `assert paragraph_index < 100`; update tests in `tests/test_chunk_builder.py` and `tests/test_normalizer.py` for splitting, grouping, and domain extraction

  **[x] Step B — tune_threshold.py** *(commit after this step)*:
  Create `scripts/tune_threshold.py` that sweeps 0.25–0.60 in 0.025 steps and reports `neg_empty`, `adv_empty`, and `pos_recall@5` per threshold

  **[x] Step C — Reindex, sweep, eval** *(commit after this step)*:
  Bump `TAXONOMY_VERSION=YYYY-MM-DD.2` in `.env`; run `uv run python scripts/run_indexing.py`; run `uv run python scripts/tune_threshold.py` and update `SIMILARITY_THRESHOLD` in `.env` to the recommended value (highest threshold maintaining neg_empty=100% that does not crush positive Recall@5 below `YYYY-MM-DD.1` baseline); run `uv run python scripts/run_evaluation.py` and verify SC-003 (positive recall ≥ baseline), SC-004 (negative empty_rate = 100%)

**Checkpoint**: Eval run at `YYYY-MM-DD.2` shows chunk count ~380, positive recall maintained, negative empty_rate = 100%. Promote to baseline.

---

## Phase 3: Retrieval Diagnostics [US3]

**Goal**: Full error analysis dataset produced for every failed scenario — expected biases, retrieved biases, scores, chunk types. This dataset drives Phase 5 domain decisions.

**Independent Test**: Run `uv run python scripts/run_evaluation.py --diagnostics` — output file at `evaluations/diagnostics/diagnostics_YYYY-MM-DD.json` contains `retrieved_with_diagnostics` for every failed scenario, each record including `bias_id`, `retrieval_score`, `matched_chunk_type`, `matched_text`.

- [x] T004 [US3] Extend evaluation pipeline with diagnostics mode and produce mandatory analysis document — add `retrieved_with_diagnostics: list[dict] | None = None` field to `ScenarioResult` in `src/evaluation/evaluate.py`; update `_retrieve_sync()` to optionally return `RetrievedBias` objects alongside bias IDs; add `--diagnostics` flag to `scripts/run_evaluation.py` that populates the field and writes output to `evaluations/diagnostics/diagnostics_YYYY-MM-DD.json`; run `uv run python scripts/run_evaluation.py --diagnostics`; **write a mandatory analysis document at `evaluations/diagnostics/analysis_YYYY-MM-DD.md`** with the following required structure:
  ```
  ## Failed Scenarios by Group
  - For each failed scenario: scenario_id, group, expected biases, what was retrieved, matched_chunk_type, score
  
  ## Domain Coverage Gaps
  - Which bias × domain combinations have zero or near-zero coverage in knowledge files
  
  ## Recommended Domain Additions (Phase 5 input)
  - Prioritised list: bias_id, domain, suggested paragraph count
  
  ## Baseline Scores for Failing Biases
  - Highest cosine score seen for each failing bias (establishes Phase 5 probe pass threshold)
  ```
  T005 cannot begin until this document exists — it is the input that determines which biases and domains to target.

**Checkpoint**: Diagnostics file produced. `analysis_YYYY-MM-DD.md` exists and lists specific biases and domains for Phase 5.

---

## Phase 4: Domain Expansion [US4]

**Goal**: New example paragraphs added to the specific biases and domains identified as failing in Phase 4. Each paragraph tagged with a controlled-vocab `[Domain]` label. Reindexed and validated.

**Independent Test**: Run eval at `YYYY-MM-DD.3` — at least one previously zero-recall adversarial or edge scenario improves.

- [ ] T005 [US4] Add targeted domain example paragraphs to failing biases — read `evaluations/diagnostics/analysis_YYYY-MM-DD.md` to identify which biases need which domains; add 1–2 new `[Domain]` labelled paragraphs per identified bias in the `## Examples` section of `knowledge/<bias>.md` using only controlled-vocab single-word labels (`Political`, `Social`, `Management`, `Consumer`, `Legal`, `Medical`) per `knowledge/STYLE_GUIDE.md`; validate each new paragraph with `scripts/probe_chunk.py` against its failing story — pass condition is `new_score > SIMILARITY_THRESHOLD` (the threshold set in Phase 3, not just "higher than an existing example"); bump `TAXONOMY_VERSION=YYYY-MM-DD.3` in `.env`; run `uv run python scripts/run_indexing.py`; run `uv run python scripts/run_evaluation.py` and verify SC-006 (at least one failing domain now shows Recall@5 > 0), SC-003 (positive recall maintained), SC-004 (negative empty_rate = 100%); if adversarial group Recall@5 > 0 → Phase 6 is skipped; if still 0 → proceed to T006

**Checkpoint**: Eval run at `YYYY-MM-DD.3`. Promote to baseline. Gate check: is adversarial Recall@5 > 0?

---

## Phase 5: Observable Patterns [US5] *(conditional — only if adversarial Recall@5 = 0 after T005)*

**Goal**: New `observable_patterns` chunk type per bias containing 5–8 short phrases people actually say when exhibiting the bias. Adversarial group recall moves off zero.

**Independent Test**: At least one adversarial scenario retrieves a correct bias. No regressions.

- [ ] T006 [US5] Add observable_patterns chunk type and author content for all 38 biases — add `CHUNK_TYPE_OBSERVABLE_PATTERNS = "observable_patterns"` to `src/schemas/internal.py`; add `"observable patterns": "observable_patterns"` to `_SECTION_MAP` in `src/indexing/sources/taxonomy.py`; add `"observable_patterns": (CHUNK_TYPE_OBSERVABLE_PATTERNS, "Observable Patterns")` to `_CHUNK_TYPE_MAP` in `src/indexing/chunk_builder.py`; append `"observable_patterns"` to `_CANONICAL_ORDER` (position 5, chunk_index 500); add `## Observable Patterns` section to all 38 `knowledge/*.md` files — 5–8 short phrases per bias in first-person or direct speech register following `knowledge/STYLE_GUIDE.md` authoring rules; validate candidate phrases with `scripts/probe_chunk.py` against failing adversarial stories before committing; bump `TAXONOMY_VERSION=YYYY-MM-DD.4` in `.env`; run `uv run python scripts/run_indexing.py`; run `uv run python scripts/run_evaluation.py` and verify SC-002 (adversarial Recall@5 > 0), SC-003, SC-004

**Checkpoint**: Eval run at `YYYY-MM-DD.4`. Adversarial recall > 0. Promote to baseline. Proceed to T007.

---

## Phase 6: Assessment-Level Validation *(always runs — final gate)*

**Goal**: Confirm that retrieval improvements do not degrade assessment quality. The end metric for this feature is whether the LLM assessment gets better, not whether retrieval scores improve.

**Independent Test**: biassemble-core assessment FP rate and `evidence_grounded_rate` are equal to or better than pre-feature baseline.

- [ ] T007 Run biassemble-core assessment evaluation against the final index (whichever version is current — `YYYY-MM-DD.3` if T006 was skipped, `YYYY-MM-DD.4` if T006 ran) and verify SC-008: assessment FP rate does not degrade from pre-feature baseline; `evidence_grounded_rate` does not degrade from pre-feature baseline; document results in `evaluations/assessment_eval_YYYY-MM-DD.md`

**Checkpoint**: SC-008 passes. Feature complete.

---

## Dependencies & Execution Order

```
T001 (Phase 0: setup + ivfflat check)
  └── T002 [US1] Phase 1: indicator rewrites + reindex YYYY-MM-DD.1
        └── T003 [US2] Phase 2: splitting infrastructure + reindex YYYY-MM-DD.2
              └── T004 [US3] Phase 3: diagnostics dataset + mandatory analysis doc
                    └── T005 [US4] Phase 4: domain expansion + reindex YYYY-MM-DD.3
                          ├── T006 [US5] Phase 5: observable_patterns + reindex YYYY-MM-DD.4
                          │         (only if T005 leaves adversarial = 0)
                          └── T007 Phase 6: assessment eval (always runs; input = highest YYYY-MM-DD.N)
```

Strictly sequential — each phase depends on the reindexed state from the previous one.

---

## Implementation Strategy

**MVP (T001 + T002)**: Indicator rewrites alone may be enough to improve edge group recall. Run eval at `YYYY-MM-DD.1` before doing any code work. A weak `.1` result — positive Recall@5 improves but adversarial remains near zero — is not a failure of T002. It means the text improvement worked but chunk granularity is still the limiting factor; proceed to T003. Only if positive Recall@5 regresses do you need to revisit the rewrites.

**Stop points**: Promote to baseline at every phase checkpoint. If any phase achieves all spec success criteria, subsequent phases are optional.

**Total tasks**: 7 (T001–T007). T006 is conditional. T007 always runs as the final gate.
