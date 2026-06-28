# Feature Specification: Semantic Bias Retrieval Service

**Feature Branch**: `001-rag-retrieval`

**Created**: 2026-06-27

**Status**: Draft

## User Scenarios & Testing

### User Story 1 — Bias Retrieval for Story Assessment (Priority: P1)

A story is submitted by the Biassemble backend. The service returns the most relevant cognitive biases from the knowledge base, each with structured descriptive content (definition, what to look for, common false positives, related biases). The returned biases are used to enrich the LLM prompt that assesses the story.

**Why this priority**: This is the core product capability. Without it, nothing else in this service has value.

**Independent Test**: Submit a story that clearly describes sunk cost behavior (e.g., continuing to invest in a failing project because of prior investment). The service returns Sunk Cost Fallacy in the top results with its full content. Can be tested with a single HTTP request.

**Acceptance Scenarios**:

1. **Given** a story clearly exhibiting confirmation bias and anchoring, **When** the story is submitted, **Then** both biases appear in the top 5 results with scores above the relevance threshold.
2. **Given** a neutral story describing everyday activities with no identifiable cognitive bias, **When** the story is submitted, **Then** the service returns an empty bias list (not an error).
3. **Given** a story submitted with optional analysis fields (themes, beliefs, claims), **When** the story is submitted, **Then** the analysis fields improve retrieval quality compared to story text alone.

---

### User Story 2 — Knowledge Base Indexing (Priority: P2)

A developer authors or updates a bias description document and re-runs the indexing process. The new or updated bias becomes retrievable without any code changes or service redeployment.

**Why this priority**: The knowledge base is the primary quality lever. If it cannot be updated easily, retrieval quality cannot improve over time.

**Independent Test**: Add a new bias document, run indexing, submit a story that should trigger it, confirm it appears in results. Requires only document authoring and a CLI command.

**Acceptance Scenarios**:

1. **Given** a new bias document is authored and the indexing process is run, **When** a relevant story is submitted, **Then** the new bias appears in retrieval results.
2. **Given** an existing bias document is updated and re-indexed under a new version, **When** a relevant story is submitted, **Then** the updated content is returned.
3. **Given** a bias document is missing a required section (false positives), **When** indexing is run, **Then** the process reports the issue and does not silently produce incomplete data.

---

### User Story 3 — Retrieval Quality Evaluation (Priority: P3)

A developer runs an evaluation script against a labeled dataset of stories with known expected biases. The script reports recall, precision, MRR, and other metrics, allowing the developer to confirm whether a change improved or degraded retrieval.

**Why this priority**: Without measurable quality, tuning is guesswork. The evaluation script is the feedback loop that makes all other improvements verifiable.

**Independent Test**: Run evaluation against a dataset of at least 3 labeled stories. Confirm the output shows per-scenario recall, precision, MRR, and aggregate metrics.

**Acceptance Scenarios**:

1. **Given** a labeled dataset with expected bias IDs per story, **When** evaluation is run, **Then** the script reports recall, precision, and MRR per scenario and in aggregate.
2. **Given** a neutral story in the evaluation dataset with no expected biases, **When** evaluation is run, **Then** the scenario is reported as passing if the service returns no biases.
3. **Given** retrieval parameters are changed (threshold, result count), **When** evaluation is run again, **Then** the output reflects the new parameter values so the comparison is unambiguous.

---

### User Story 4 — Operational Visibility (Priority: P4)

An operator checks whether the service is healthy: model loaded, knowledge index populated, database reachable, and the current index version. This is the primary operational signal for deployment and incident response.

**Why this priority**: Without a health endpoint, there is no way to know if the service is degraded before users are affected.

**Independent Test**: Call the health endpoint. Confirm it returns the model status, index row count, database connectivity, and last indexed timestamp.

**Acceptance Scenarios**:

1. **Given** the service is running and the knowledge index is populated, **When** the health endpoint is called, **Then** it returns confirmation that the model is loaded, the database is connected, and the index is non-empty.
2. **Given** the database is unreachable, **When** the health endpoint is called, **Then** it reports database disconnected rather than returning an error or appearing healthy.

---

### Edge Cases

- Story is empty or fewer than 5 words — service returns an empty bias list, not an error.
- Knowledge index has not been populated (first deploy, indexing not yet run) — service reports this explicitly; returning an empty bias list would be indistinguishable from "no relevant biases found."
- Database becomes unreachable mid-request — service returns a service-unavailable response rather than an empty bias list, which would be a false "no biases" signal.
- Same bias has multiple sections that all match a story — service returns the bias once, using the highest-scoring section to represent it.
- Caller does not provide an authorization credential — service returns an authentication error.
- Embedding model fails to load at startup — service refuses to start; it must not accept requests without a functional model.
- Knowledge directory is empty — indexing reports this as a configuration error rather than producing an empty index silently.
- A bias document is malformed or unreadable — indexing reports the specific document and skips it; it does not silently omit content.
- Embedding representation version is mismatched with the stored index (e.g. model was changed without re-indexing) — service reports the mismatch at startup rather than producing garbage retrieval results.

---

## Requirements

### Functional Requirements

- **FR-001**: Service MUST return a ranked list of relevant biases given a story text input.
- **FR-002**: Each returned bias MUST include: name, relevance score, definition, examples, indicators, false positives, and related biases.
- **FR-003**: Service MUST return an empty bias list (not an error) when no biases meet the relevance threshold.
- **FR-004**: Service MUST explicitly distinguish between "no relevant biases found" and "service is unable to retrieve" — the former is a 200 response with an empty list; the latter is an error response.
- **FR-005**: Service MUST require authentication from callers.
- **FR-006**: Service MUST expose a health endpoint reporting: model load status, knowledge index version, index row count, last indexed timestamp, and database connectivity.
- **FR-007**: Knowledge base MUST be indexable from a directory of authored bias documents without service code changes.
- **FR-008**: Indexing MUST validate that every bias document includes a false positives section and report missing ones before completing.
- **FR-009**: Indexing MUST be idempotent when the knowledge version identifier is changed — re-indexing must not corrupt or duplicate existing indexed data.
- **FR-010**: Retrieval quality MUST be measurable via an evaluation script that accepts a labeled dataset and reports recall, precision, MRR, nDCG, and empty retrieval rate.
- **FR-011**: Service MUST remain operational (health endpoint responsive) even when the database is unreachable at startup.
- **FR-012**: Service MUST crash at startup if the embedding model fails to load — it must not serve requests in a degraded model state.
- **FR-013**: Every retrieval request MUST emit structured log events covering: request received, embedding computed, search executed, results returned. These logs are the primary observability artifact and must be queryable for debugging retrieval regressions.
- **FR-014**: Service MUST expose a `GET /stats` endpoint returning: taxonomy version, embedding model, embedding dimension, indexed row count broken down by chunk type and source, and last index timestamp. This answers "what exactly is deployed?" independently of `/health`.
- **FR-015**: Callers MAY provide a `request_id` with each retrieval request. If provided, it MUST be echoed in the response and included in all structured log events for that request, enabling end-to-end correlation across biassemble-core and biassemble-engine logs.

### Non-functional Requirements

- **NFR-001**: Retrieval latency at the 95th percentile MUST be under 300ms (embedding + vector search + response serialization).
- **NFR-002**: Health endpoint MUST respond in under 50ms under normal conditions.
- **NFR-003**: Service MUST handle concurrent retrieval requests without serializing them — a slow request must not block other in-flight requests.
- **NFR-004**: Retrieval MUST be deterministic — identical story input and identical index version MUST produce identical ranked results.
- **NFR-005**: Service MUST NOT make any calls to external AI or LLM APIs during retrieval. The embedding model runs locally.
- **NFR-006**: The embedding model MUST be loaded once at startup and held in memory for the lifetime of the process — never reloaded per request.
- **NFR-007**: Total service memory footprint MUST remain under 1 GB under normal operating conditions (model + index + request handling).

### Key Entities

- **Bias**: A cognitive bias with a unique identifier, display name, definition, examples, behavioral indicators, false positives (situations that look like the bias but are not), and related biases.
- **Bias Document**: An authored text file describing a single bias in structured sections. The source of truth for bias content.
- **Knowledge Index**: The pre-built, searchable representation of all bias documents. Created by the indexing process. Versioned — a new version is a complete new snapshot, not an update to an existing one.
- **Knowledge Version**: An immutable identifier for a specific snapshot of indexed bias content. Changing bias documents requires a new knowledge version. Old versions are retained until explicitly removed.
- **Embedding Version**: An identifier for the specific representation model used to build the knowledge index. Switching the representation model requires a new embedding version and full re-indexing — an index built with one model cannot be queried with another.
- **Story**: A text narrative submitted by the caller. The primary input to retrieval.
- **Story Analysis**: Optional structured metadata about a story (themes, beliefs, claims). Generated upstream by the caller — this service never produces it. Retrieval must continue working correctly without it. The structure may evolve; this service treats it as optional enrichment.
- **Retrieval Result**: A ranked, filtered list of biases returned for a given story, with scores and full content.
- **Evaluation Dataset**: A labeled set of stories with expected bias IDs, organized into positive (known biases), negative (no biases), and edge (ambiguous) groups. Used to measure retrieval quality and detect regressions.
- **Evaluation Baseline**: A saved JSON snapshot of evaluation metrics for a specific taxonomy version and config. New runs compare against the baseline to show metric deltas.

---

## Quality Measurement

Evaluation is a first-class concern in this service, not a secondary feature. Biassemble's credibility depends on knowing whether its bias detection is working — and the only way to know is to measure it continuously.

The evaluation system serves two purposes:
1. **Baseline establishment** — measure retrieval quality before tuning any parameters.
2. **Regression detection** — confirm that a change to knowledge content, index parameters, or retrieval logic improved (or did not degrade) the baseline.

Every change to the following must be followed by an evaluation run before the change is considered complete:
- Knowledge documents
- Index parameters (threshold, result count)
- Representation model

The evaluation dataset is organized into four groups:
- **Positive scenarios** (`evaluations/positive/`): stories with known expected biases. Used to measure recall, MRR, and nDCG.
- **Negative scenarios** (`evaluations/negative/`): stories with no cognitive bias content. Used to measure false retrieval rate — the fraction of neutral stories that incorrectly return bias suggestions.
- **Edge scenarios** (`evaluations/edge/`): ambiguous stories used for threshold calibration. Not counted in primary metrics.
- **Adversarial scenarios** (`evaluations/adversarial/`): stories designed to stress the retrieval boundary — political rhetoric, satire, emotionally manipulative narratives, AI-generated hallucinations, deliberately contradictory evidence. Expected bias IDs are empty or minimal. Used as a robustness benchmark: good retrieval should not fire on these. Not counted in primary recall/MRR metrics but `empty_rate` is reported separately for this group.
- **Regression scenarios** (`evaluations/regression/`): permanent record of bugs that were once found and fixed. Every time a retrieval failure is discovered in production or testing, a story is added here and never removed. This group grows over time and is always re-run. Examples: a story that once returned the wrong bias, a neutral story that once incorrectly fired, an edge case that caused a 500 error.

Evaluation results must clearly distinguish between these groups and report metrics separately.

Each evaluation run saves a snapshot to `evaluations/baselines/baseline_vN.json`. Subsequent runs compare against the most recent baseline and print deltas (e.g., `Recall +2.4%, MRR -0.8%`). This makes evaluation behave like a CI benchmark — every change is measured against a known reference point.

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: A story exhibiting three well-known cognitive biases returns all three in the top 5 results.
- **SC-002**: A story with no identifiable cognitive bias returns zero bias suggestions.
- **SC-003**: Bias retrieval for a typical story completes in under 300ms from request receipt to response.
- **SC-004**: At least 85% of expected biases are found in the top 5 results across the evaluation dataset (Recall@5 ≥ 0.85).
- **SC-005**: The median rank of the first correct bias across the evaluation dataset is 1 or 2 (MRR ≥ 0.85).
- **SC-006**: Adding a new bias requires only authoring one document and running the indexing process — no code changes.
- **SC-007**: The health endpoint correctly reports whether the knowledge index is populated and the database is reachable.
- **SC-008**: Removing a story's cognitive context (replacing with neutral content) causes its previously returned biases to no longer appear above the relevance threshold.

---

## Assumptions

- The service is called exclusively by a trusted backend service (biassemble-core), not directly by end users. No rate limiting or user-facing error messages are required for v1.
- Stories are in English. Non-English story behavior is undefined and out of scope for v1.
- The knowledge base is authored and maintained by developers. End-user authoring of biases is out of scope.
- The service runs as a persistent process — the embedding model is loaded once at startup and held in memory. Serverless or ephemeral deployment is not a target for v1.
- The knowledge base covers approximately 30 cognitive biases for v1. Scaling beyond 200 biases may require index parameter tuning but no structural changes.
- When the service is unavailable, the caller (biassemble-core) is responsible for falling back to a static taxonomy. This service does not need to implement its own fallback.
- The false positives section in each bias document is the primary guard against over-retrieval — it is mandatory and validated at indexing time, not at retrieval time.

---

## Out of Scope

The following are explicitly excluded from v1. They may be revisited after an evaluation baseline is established.

- Hybrid retrieval (combining keyword search with semantic search)
- Cross-encoder reranking of retrieved results
- External knowledge sources (Wikipedia, academic papers, books)
- End-user authoring of knowledge content
- Fine-tuned or domain-adapted embedding models
- Multi-language story support
- Caching of retrieval results
- Rate limiting
- Liveness / readiness endpoint separation (single `/health` endpoint is sufficient for v1)
