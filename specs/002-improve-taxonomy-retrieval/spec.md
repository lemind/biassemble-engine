# Feature Specification: Taxonomy Retrieval Improvement

**Feature Branch**: `002-improve-taxonomy-retrieval`

**Created**: 2026-07-02

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Indicator Language Rewrite (Priority: P1)

All 38 bias `## Indicators` sections are rewritten from analytical observer language into behavioral, observable, and first-order reasoning patterns that naturally appear in user stories. Current indicators describe what an analyst sees from the outside ("dismisses contradictory evidence"). Rewritten indicators describe the reasoning and behavior as it appears in text produced by someone exhibiting the bias ("explains away contradictory evidence as unreliable or exceptional").

**Why this priority**: This is the largest single vocabulary gap between the taxonomy and the stories the system must retrieve against. Indicators are currently written in psychology textbook register, not in the language people use when reasoning, arguing, or making decisions.

**Independent Test**: For biases implicated in current failures, a before/after comparison on a failing story shows measurably improved matching for the rewritten version. For biases not implicated in failures, the rewritten file passes the full evaluation suite with no regressions.

**Acceptance Scenarios**:

1. **Given** an indicator written in analytical observer language for a bias that appears in a failing story, **When** it is rewritten into behavioral and reasoning patterns, **Then** a before/after measurement on that failing story shows the rewritten version matches more closely than the original.
2. **Given** a bias not implicated in any current failure, **When** its indicators are rewritten, **Then** the full evaluation suite shows no regressions.
3. **Given** all 38 files with rewritten indicators, **When** the full evaluation suite runs, **Then** no previously passing scenarios regress.

---

### User Story 2 - Atomic Chunk Splitting (Priority: P2)

All knowledge file sections are split into atomic per-unit chunks so that each chunk answers exactly one retrieval question. Splitting rules differ by chunk type: example sections are split per domain paragraph (each paragraph is its own chunk); indicator sections are grouped into 2–3 thematic clusters of 30–60 words each rather than split per individual bullet, because single bullets are too short to embed stably.

**Why this priority**: A chunk that blends finance, medicine, law, and technology examples into one vector cannot be well-matched to a political story. Splitting gives each domain its own representation. Indicator bullets are grouped rather than split individually to avoid noisy micro-embeddings that misfire on unrelated stories.

**Independent Test**: Given a political example paragraph currently merged into a multi-domain chunk, when split into its own chunk, that chunk retrieves correctly against a political story.

**Acceptance Scenarios**:

1. **Given** an example section with paragraphs from multiple domains merged into one chunk, **When** split into per-paragraph chunks, **Then** the political paragraph chunk retrieves correctly against a political story.
2. **Given** indicator bullets split into thematic groups, **When** measured on both target and unrelated stories, **Then** the grouped chunks improve target matching without increasing false retrievals on unrelated stories.
3. **Given** all 38 files split and reindexed, **When** the full evaluation suite runs, **Then** positive group Recall@5 does not decrease from the pre-split baseline.

---

### User Story 3 - Retrieval Diagnostics Dataset (Priority: P3)

After Phases 1 and 2, a full evaluation run is executed and a structured error analysis dataset is produced for every failed scenario. Each record captures: expected biases, retrieved biases, similarity scores for each retrieved result, chunk types of retrieved results, and which chunk type produced each retrieval.

**Why this priority**: Without diagnostic data, domain expansion decisions are guesswork. This dataset is the evidence base that determines which domains to add and which chunk types are underperforming.

**Independent Test**: The diagnostics output can answer: "Which chunk types retrieved in the edge group failures?" and "Which domains are absent from the biases that failed on political stories?"

**Acceptance Scenarios**:

1. **Given** a failed evaluation scenario, **When** diagnostics are collected, **Then** the record includes expected biases, retrieved biases, similarity scores, chunk types, and top retrieved chunks.
2. **Given** the full diagnostics dataset, **When** analyzed, **Then** it is possible to rank chunk types by retrieval frequency across each evaluation group and identify which domains are absent from failures.

---

### User Story 4 - Targeted Domain Expansion (Priority: P4)

New domain example paragraphs are added only to the biases identified as failing on specific story types in the Phase 3 diagnostics. Domains not identified as failing receive no new content. Each new paragraph lands in its own atomic chunk and carries a domain tag. Domain selection is driven by the error analysis — not determined in advance.

**Why this priority**: Adding domains uniformly wastes effort and risks degrading performance in domains that already retrieve correctly. Evaluation failures drive coverage decisions.

**Independent Test**: Given the error analysis showing bias X fails on political stories, when a political example paragraph is added for bias X, retrieval accuracy for political stories that include bias X improves.

**Acceptance Scenarios**:

1. **Given** error analysis showing specific biases fail on political stories, **When** political examples are added for those biases only, **Then** retrieval accuracy on political stories improves for those biases.
2. **Given** biases not identified as failing on a domain, **When** no new examples are added for that domain, **Then** their retrieval performance is unchanged.

---

### User Story 5 - Observable Patterns Chunk Type (Priority: P5, conditional)

A new chunk type — `observable_patterns` — is added per bias containing 5–8 short phrases people actually say when exhibiting the bias. This type encodes linguistic surface patterns that appear in the voice of the biased actor, not in the voice of an analyst describing the bias.

**Why this priority**: Conditional on Phase 3 diagnostics showing the adversarial evaluation group remains at zero recall after Phases 1–4. If the gap persists, it indicates a structural difference between how biases are described in the taxonomy and how they are enacted in rhetorical text that atomic splitting and domain expansion cannot close.

**Independent Test**: Given an adversarial story still failing after Phases 1–4, when an observable_patterns chunk is added for the expected bias, the story retrieves that bias.

**Acceptance Scenarios**:

1. **Given** the adversarial group at zero recall after Phase 4 evaluation, **When** observable_patterns chunks are added for all 38 biases, **Then** at least one adversarial scenario retrieves a correct bias.
2. **Given** observable_patterns chunks added, **When** the full evaluation suite runs, **Then** no previously passing scenarios regress.

---

### Edge Cases

- A rewritten indicator that improves one story but causes regressions elsewhere must be rejected and revised before committing.
- Domain examples must not be added for biases that already retrieve correctly on the target domain — the error analysis gates this.
- The observable_patterns phase must not begin unless the gate condition (adversarial group Recall@5 = 0 after Phase 4 evaluation) is explicitly verified.
- The evaluation dataset is read-only throughout — no scenario, story, or expected label may be modified for any reason.
- After Phase 2 reindex, the similarity threshold must be recalibrated: Phases 1–2 raise similarity scores across the board, making the pre-existing threshold too permissive and risking false retrievals on negative stories. Threshold recalibration must be performed before proceeding to Phase 3.
- If chunk splitting grows the retrieval index significantly, the approximate nearest-neighbour index parameters must be retuned to approximately the square root of the new row count to maintain recall quality. This must be assessed and documented as part of the Phase 2 reindex.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All 38 bias `## Indicators` sections MUST be rewritten into behavioral, observable, and first-order reasoning patterns that are likely to appear in user stories.
- **FR-002a**: For biases implicated in current evaluation failures, each rewritten indicator section MUST demonstrate measurably improved matching against at least one failing story before being committed.
- **FR-002b**: For biases not implicated in any current evaluation failure, rewritten indicator sections MUST comply with the STYLE_GUIDE and produce no regressions on the full evaluation suite.
- **FR-003**: Knowledge file sections MUST be split into chunks according to type-specific rules: example sections are split per domain paragraph; indicator sections are grouped into 2–3 thematic clusters of 30–60 words each (not per individual bullet). Definition, false positive, and related sections retain one chunk per section.
- **FR-004**: Each chunk MUST answer exactly one of the following retrieval questions: "What is this bias?", "What does this bias look like in practice?", "What reasoning pattern signals this bias?", "When might this look like the bias but not be?", "What related concepts should retrieval also surface?"
- **FR-005**: The retrieval index MUST be rebuilt to reflect the new chunk structure after Phases 1 and 2.
- **FR-006**: A full evaluation run MUST be executed after Phases 1 and 2 to establish a post-rewrite baseline before any domain expansion begins.
- **FR-007**: The error analysis output MUST capture, per failed scenario: expected biases, retrieved biases, similarity scores for each retrieved result, chunk types, and top retrieved chunks. NDCG is tracked in run output but is not a phase-gate metric.
- **FR-008**: New domain example paragraphs MUST only be added to biases and domains explicitly identified as failing in the Phase 3 error analysis. Each new domain chunk MUST carry a `domain` metadata tag identifying its domain (e.g., `political`, `everyday_social`).
- **FR-009**: observable_patterns chunks MUST only be added if the adversarial group remains at zero recall after Phase 4. The gate condition MUST be explicitly verified before this phase begins.
- **FR-010**: The evaluation dataset MUST remain read-only at all times. No modification to evaluation scenarios for any reason.
- **FR-011**: No previously passing evaluation scenario MUST regress at any phase boundary.
- **FR-012**: All knowledge file edits MUST comply with the existing STYLE_GUIDE (section length limits, mandatory sections, naming conventions, authoring language principle).
- **FR-013**: The full document payload returned per retrieved chunk MUST remain the complete merged canonical sections of the bias (not the matched atomic chunk text alone). The matched chunk's text MUST also be returned separately so the assessment layer can choose what to use. This preserves full context for assessment while enabling atomic retrieval.
- **FR-014**: After the Phase 2 reindex, similarity threshold recalibration MUST be performed. The recalibrated threshold must maintain Empty Retrieval Rate = 100% on the negative evaluation group before Phase 3 proceeds.
- **FR-015**: Every phase boundary that produces a new retrieval index MUST increment the `taxonomy_version`. Every evaluation run MUST record the `taxonomy_version` it measured against, so phase-boundary comparisons remain unambiguous.

### Key Entities

- **Bias knowledge file**: One file per cognitive bias (38 total). Contains Definition, Examples, Indicators, False Positives, and Related Biases sections. Canonical source for all chunks.
- **Chunk**: Atomic retrieval unit derived from one section or paragraph of a knowledge file. Has a chunk type, a bias identifier, a text body, and optional metadata (e.g., `domain`). Each chunk answers exactly one retrieval question.
- **Chunk type**: Classification of what retrieval question a chunk answers. Current types: semantic_definition, semantic_example, semantic_indicator, semantic_false_positive, semantic_related. Proposed conditional type: observable_patterns.
- **Evaluation scenario**: A story paired with expected bias identifiers and a group label (positive, negative, edge, adversarial). Read-only ground truth.
- **Evaluation run**: Full execution of all evaluation scenarios, producing per-scenario recall, precision, MRR, and NDCG, plus group-level aggregates and deltas from the previous baseline. Each run records the `taxonomy_version` it measured.
- **Error analysis record**: Per-failed-scenario diagnostic record capturing expected biases, retrieved biases, similarity scores, chunk types, and top retrieved chunks.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Edge group Recall@5 improves above the baseline of 0.417 after Phases 1–2.
- **SC-002**: Adversarial group Recall@5 improves above the baseline of 0.000 after Phases 1–4, or Phase 5 is triggered and its outcome measured.
- **SC-003**: Positive group Recall@5 is maintained at or above the baseline of 0.667 at every phase boundary.
- **SC-004**: Negative group Empty Retrieval Rate is maintained at 100% at every phase boundary — no biases are retrieved for stories that contain none.
- **SC-005**: Error analysis dataset covers 100% of failed scenarios after the Phase 3 evaluation run.
- **SC-006**: After Phase 4 domain expansion, at least one scenario from each identified failing domain shows Recall@5 > 0.
- **SC-007**: Adversarial group Precision@5 is tracked at every phase boundary. Retrieving the correct bias behind multiple wrong ones is not treated as an improvement — the wrong retrievals must decrease.
- **SC-008**: After the final phase, an assessment-level evaluation (FP rate, evidence_grounded_rate) is run with the new retrieval index and confirms no degradation from the pre-feature baseline. Retrieval is the means; assessment quality is the outcome.

## Assumptions

- All 38 knowledge files in their current structure are the canonical source — no new biases are added in this feature.
- Evaluation datasets are static ground truth representing real-world stories the system must handle; they are never adjusted to fit the taxonomy.
- Phase ordering is enforced: evaluation diagnostics (Phase 3) must complete before domain expansion (Phase 4) begins; observable_patterns (Phase 5) only if gate condition is met.
- The observable_patterns chunk type, if added, is validated with the same before/after measurement process as indicator rewrites before being committed.
- The existing chunk type names (semantic_definition, semantic_example, semantic_indicator, semantic_false_positive, semantic_related) remain; this feature restructures how they are populated, not the type taxonomy itself, unless Phase 5 triggers.
- STYLE_GUIDE constraints on section word limits, mandatory sections, naming conventions, and authoring language continue to apply to all modified files.
- The taxonomy should be written in the language people think, not the language psychologists use to describe thinking.
- The `full_document` payload per retrieval result retains its current structure (complete merged bias document) to avoid breaking the biassemble-core assessment prompt. The atomic matched chunk text is an additive field, not a replacement.
