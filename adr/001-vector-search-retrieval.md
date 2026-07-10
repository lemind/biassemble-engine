# engine ADR-001 — Semantic Bias Retrieval via Vector Search (RAG)
### Status: ACCEPTED (implemented); selection role SUPERSEDED by engine ADR-002 (NLI shortlist) · Retroactive record, written 2026-07-06

## Context

biassemble-core injected all 38 bias descriptions into every assessment prompt — oversized input, diluted LLM attention. Needed: select only story-relevant biases.

## Decision

Build `biassemble-engine`: a pure semantic retriever (no LLM calls). Stack: Python/FastAPI, `all-MiniLM-L6-v2` (384-dim), pgvector on Supabase, exact scan. Taxonomy: 38 biases as markdown (Definition / Examples / Indicators / False Positives / Related), split into atomic chunks (~380), `full_document` on every row (match by chunk, return complete context). Pipeline: story query → cosine top-40 → threshold → max-score collapse per bias → top-5 → full documents. Infra failure = 5xx. Immutable `taxonomy_version` per reindex; eval harness (golden dataset: positive/edge/adversarial/negative) with read-only discipline.

**SIMILARITY_THRESHOLD=0.35**, chosen via `tune_threshold.py` sweep as the highest threshold holding negative empty_rate at 1.00 without degrading positive recall. Recalibration after every reindex is mandatory — score distributions shift with content.

**`repeated_story` query strategy** (story truncated to 100 words, repeated to fill the 256-token window) chosen over summary/keyword strategies for simplicity and zero LLM cost. Consequence recorded with hindsight: this put raw user-story vocabulary, topic-dominated, into the query embedding — a direct contributor to the tonal-bias ceiling that ADR-002 addresses.

## Accepted state (Jul 3, post-T005)

| Group | baseline | post indicator-rewrite + atomic chunks + domain examples |
|---|---|---|
| positive Recall@5 (target 0.85) | 0.667 | 0.667 |
| negative empty_rate (target ≥0.90) | 1.000 | 1.000 |
| edge Recall@5 | 0.417 | 0.583 |
| adversarial Recall@5 | 0.000 | 0.333 |

A further extension (+20 story patterns/bias, reindexed 2026-07-06.1) regressed adversarial 0.333→0.000 with positive flat; branch parked unmerged. **Current accepted state = Jul 3 post-T005: positive 0.667 / negative 1.000 / edge 0.583 / adversarial 0.333, threshold 0.35.**

Misses concentrated in tonal biases (`overconfidence` 3/4 scenarios, implicit `confirmation`). Diagnosis: single-vector embeddings encode topic, not tone — **mechanism ceiling, not vocabulary gap**. Three content interventions, zero positive-recall movement = evidence, not opinion.

## Consequences

- Worked: edge recall +0.166 from content fixes; negative discipline perfect; eval/versioning infrastructure proved its worth (caught a regression before merge).
- Didn't: positive recall immovable by content; story-patterns investment (~760 chunks) net-negative.
- Outcome: bias **selection** role handed to NLI recognition (engine ADR-002); vector search retained as secondary union signal and as the retrieval mechanism for the b2b corpus path (product ADR-002), where nearness-of-meaning is the actual question.

**Reversal — `biases: []` discipline:** The original design stated `biases: []` = valid "nothing relevant" response. This position was reversed by T008: in practice an empty retrieval left the assessment prompt without any taxonomy context, making the LLM's judgment unanchored and unusable. T008 introduced a roster fallback (minimal default bias set injected when retrieval returns empty). The 5xx-on-infra-failure discipline stands; only the empty-result consumption changed.
