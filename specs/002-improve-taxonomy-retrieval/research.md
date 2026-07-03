# Research: Taxonomy Retrieval Improvement

**Date**: 2026-07-02 | **Branch**: `002-improve-taxonomy-retrieval`

No NEEDS CLARIFICATION items — the technical context is fully established by spec 001 and the existing codebase. This document records decisions for each open design question introduced by this feature.

---

## Paragraph splitting strategy for `semantic_example` chunks

**Decision**: Split on double newline (`\n\n`) within the section text. Each non-empty paragraph becomes its own `RawDocument` with `paragraph_index` tracking its position within the section. The `chunk_type` field stays `"examples"` on every split document — same semantic constant, multiple vectors.

**Rationale**: Double newline is the existing formatting convention in every knowledge file. The current indicator files use single newlines between bullets; example paragraphs are separated by blank lines. Splitting on `\n\n` requires zero authoring changes and captures the natural paragraph boundary used by all existing files.

**Alternatives considered**:
- Split on single newline — too aggressive; would split mid-paragraph prose.
- Detect paragraph boundaries by sentence structure — fragile; requires NLP heuristics.
- New markdown delimiter (e.g., `---` between paragraphs) — requires touching all 38 files before any retrieval improvement is visible; defers value.

---

## Indicator bullet grouping strategy

**Decision**: Group indicator bullets into 2–3 thematic clusters within `chunk_builder` rather than splitting per bullet. Target ~30–60 words per cluster. Three semantic categories:
- **Reasoning patterns** — thoughts, beliefs, conclusions, what the person tells themselves
- **Behavioral patterns** — observable actions, decisions, choices
- **Verbal patterns** — what someone actually says when exhibiting the bias

Grouping is done by assigning each bullet to a category based on keyword signals. Bullets that don't clearly map to a category are added to the smallest group. This produces 2–3 semantically coherent clusters that are long enough to embed stably, rather than 6–8 fragile micro-vectors.

**Rationale**: Individual indicator bullets are 8–15 words — too short for stable 384-dim embeddings. Very short text produces noisy vectors that misfire on unrelated stories. The three-category grouping gives each cluster enough semantic density while separating reasoning-language indicators (which match internal monologue stories) from verbal-language indicators (which match rhetorical stories).

**Alternatives considered**:
- One chunk per bullet — produces noisy micro-embeddings; max-score collapse then returns false positives on the noisiest vector.
- One chunk for all bullets (current) — produces a blended centroid that is not close to any specific story type.
- Two groups (reasoning + behavioral) — reasonable, but misses the verbal/rhetorical cluster that is specifically needed for adversarial stories.

---

## `full_document` payload under atomic splitting

**Decision**: `FullBiasDocument` fields remain the full merged section text across all paragraphs. The `BiasChunk.full_document` object is unchanged. `matched_text` in `RetrievedBias` (already populated by the reranker) carries the specific atomic chunk that scored highest. The API `BiasResult` exposes full section text to biassemble-core, not the matched chunk alone.

**Rationale**: biassemble-core consumes the full `examples`, `indicators`, and `false_positives` fields to build the assessment prompt — it needs the full context to reason about whether a bias is present. Giving it only the matched paragraph would remove context the LLM needs. The atomic chunk's job is retrieval — it is logged via `matched_chunk_type` / `matched_text` but not injected into the prompt. FR-013 explicitly confirms this.

**Alternatives considered**:
- Replace `full_document` with only the matched chunk — degrades assessment quality; the LLM loses the full indicator and false positive context that shapes its reasoning.
- Add a `matched_context` field alongside `full_document` — unnecessary; `RetrievedBias.matched_text` already carries this and is already logged.

---

## Domain metadata tagging convention

**Decision**: Domain-tagged example paragraphs are written with a bracketed domain label at the start: `[Political] In an election campaign, ...`. `TaxonomySource` detects the pattern `^\[([A-Za-z]+)\]` at the start of a paragraph, extracts the domain string, stores it in `metadata.domain`, and strips the label from `chunk_text` before embedding. Non-domain-tagged paragraphs have `metadata.domain` absent.

**Rationale**: Self-documenting in the knowledge file; no separate mapping file to maintain; authoring intent is visible without looking at the indexer. The GIN index on `metadata` (already present) enables `WHERE metadata->>'domain' = 'political'` filtering for future domain-specific retrieval.

**Domain labels to use in Phase 4**: derived from Phase 3 error analysis. Expected candidates: `Political`, `Social`, `Management`, `Consumer`. Not defined in advance. Labels must be single words — the regex `^\[([A-Za-z]+)\]` does not match multi-word phrases like `Everyday Social`; use `Social` instead.

**Alternatives considered**:
- Separate `domain_map.json` file mapping `bias_id:paragraph_index → domain` — fragile; breaks when paragraphs are reordered; not self-documenting.
- New markdown section per domain (e.g., `## Political Examples`) — requires a schema change to TaxonomySource's section map and adds more sections than the STYLE_GUIDE allows.
- Metadata annotation in HTML comments — invisible to authors reading the file; harder to validate.

---

## `paragraph_index` field in `RawDocument`

**Decision**: Add `paragraph_index: int = 0` to `RawDocument`. Defaults to 0 for single-chunk sections (definition, false positives, related). Set by `TaxonomySource` when splitting multi-paragraph sections. `chunk_builder` computes `chunk_index` as `section_base * 100 + paragraph_index`, where `section_base` is the section's position in `_CANONICAL_ORDER`. This preserves section-level ordering while allowing sub-ordering within sections (example paragraph 2 of confirmation_bias will always sort after paragraph 1).

**Alternatives considered**:
- Change chunk_index to a global sequential counter — loses section-level ordering signal; makes debugging harder ("which section did this chunk come from?").
- Drop chunk_index entirely — it's used by the dedup index and debug display; removing it requires a schema migration.

---

## `taxonomy_version` naming across phases

**Decision**: Use `"YYYY-MM-DD.N"` sub-version format, e.g., `"2026-07-02.1"`, `"2026-07-02.2"`. N increments for each reindex within a day. Each phase boundary that produces a new retrieval index must bump N. Set manually in `.env` and `Settings.taxonomy_version` before each reindex run.

**Rationale**: The existing date-string convention (`"2026-06-28"`) is already established. Sub-version suffix `.N` extends it without breaking existing sort order. Each phase evaluation run records its version, making phase-boundary comparisons unambiguous.

**Alternatives considered**:
- `p1`, `p2` suffix (`"2026-07-02-p1"`) — readable but not sortable as a version string.
- Timestamp format (`"2026-07-02T14:30"`) — too granular; looks like an accident rather than an intentional version bump.
- Semantic versioning (`v2.0.0`) — overkill for a taxonomy content update; the date component is more meaningful here.

---

## Error analysis diagnostics format

**Decision**: Extend `ScenarioResult` with `retrieved_with_diagnostics: list[dict] | None`. Each dict contains `{bias_id, retrieval_score, matched_chunk_type, matched_text}` for every bias returned by the reranker (not just top-K bias IDs). Set to `None` in normal runs; populated when `--diagnostics` flag is passed to `run_evaluation.py`. Saved to `evaluations/diagnostics/diagnostics_YYYY-MM-DD.json`.

**Rationale**: Normal evaluation runs don't need the extra payload — it would inflate every run file. Diagnostics are produced explicitly as part of the Phase 3 step, not automatically on every run. Keeps the normal run format stable for baseline comparison.

The `matched_chunk_type` and `matched_text` fields already exist on `RetrievedBias` (the reranker output) — they just need to be captured before the response serializer drops them.

**Alternatives considered**:
- Always capture diagnostics — bloats every run JSON; the run file is already the baseline record; adding diagnostic payload makes it noisier.
- Separate diagnostic endpoint on the API — not needed here; this is a local development tool.

---

## Pre-reindex cosine delta probe script

**Decision**: New script `scripts/probe_chunk.py`. Takes `--story`, `--old`, and `--new` arguments. Embeds all three, computes cosine similarity for old and new chunks against the story, prints delta and pass/fail. Does not touch the database. Used to validate every indicator rewrite before committing the knowledge file change.

**Usage example**:
```
uv run python scripts/probe_chunk.py \
  --story "The evidence is clear: our policies are working." \
  --old "Confidence intervals that are too narrow relative to actual outcome distributions" \
  --new "States an outcome as certain or inevitable without acknowledging the possibility of being wrong"
```

**Output**: similarity score for old chunk, similarity score for new chunk, delta, pass/fail (pass = new > old — no fixed threshold).

**Alternatives considered**:
- Test in a Jupyter notebook — not reproducible; can't be run in CI.
- Integrate into the test suite — probe is exploratory (iterate rewrites until pass); test suite is regression. These are different jobs.

---

## Threshold recalibration method

**Decision**: New script `scripts/tune_threshold.py`. Sweeps threshold values from 0.25 to 0.60 in steps of 0.025. For each candidate threshold, reports negative group empty_rate, adversarial group empty_rate, and positive group Recall@5 side by side. The recommended threshold is the highest value that maintains negative empty_rate = 100% — but must be rejected if positive Recall@5 drops below the pre-feature baseline (i.e., the threshold cannot be raised so aggressively that it crushes positive retrievals). Operator then sets `SIMILARITY_THRESHOLD` in `.env` manually.

Sample output format:
```
threshold  neg_empty  adv_empty  pos_recall@5
0.250      92.0%      100.0%     0.750
0.300      96.0%      100.0%     0.720
0.325      98.0%      100.0%     0.700
0.350      100.0%     100.0%     0.680  ← candidate
0.375      100.0%     100.0%     0.650
0.400      100.0%     100.0%     0.580  ← too high; crushes positives
```

`adv_empty` is shown because adversarial stories contain real biases — a threshold so high that it empties them is wrong in the other direction.

**Rationale**: Phases 1–2 raise similarity scores for well-matched stories, making the old threshold too permissive. Running the sweep after reindex grounds the threshold in the actual score distribution of new chunks. Showing positive Recall@5 alongside empty_rate prevents a false "safe" selection that actually degrades what was already working.

**Alternatives considered**:
- Automated threshold update — threshold affects production retrieval behavior; human review is appropriate before applying.
- Sweep only the negative group — misses the adversarial floor and the positive ceiling; produces an incomplete picture.

---

## `observable_patterns` chunk type (conditional, Phase 5 only)

**Decision**: If Phase 5 is triggered:
- New constant: `CHUNK_TYPE_OBSERVABLE_PATTERNS = "observable_patterns"` in `src/schemas/internal.py`
- `TaxonomySource` adds `"observable patterns"` to `_SECTION_MAP`
- `chunk_builder` adds `"observable_patterns": (CHUNK_TYPE_OBSERVABLE_PATTERNS, "Observable Patterns")` to `_CHUNK_TYPE_MAP`
- New markdown section `## Observable Patterns` added to all 38 knowledge files
- STYLE_GUIDE: 5–8 phrases per bias, ≤12 words each, written as first-person or direct speech, no analytics language, no section headers

**Observable patterns are NOT split further** — the full set of 5–8 phrases is one chunk. The phrases are short enough to fit within the 256-token limit collectively, and embedding them together preserves the semantic cluster of "ways this bias sounds" better than individual phrase embeddings.

**Alternatives considered**:
- One phrase per chunk — 8 chunks of 5–10 words each are too short to embed stably (same problem as per-bullet indicators).
- Embed into `semantic_indicator` — conflates the analytical language of existing indicators with the surface-form phrases; the vectors need to be separate to work.
