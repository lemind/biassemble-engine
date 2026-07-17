# Feature Specification: Fine-Tune the `llm_union` Cartridge

**Feature Branch**: `006-fine-tune-llm`

**Created**: 2026-07-16

**Status**: Draft

**Input**: User description: "Fine-tune the biassemble-engine llm_union cartridge (Gemma-3-4B) via LoRA — formalize the decisions already made in adr/005-fine-tune-engine-llm.md: bootstrap an SFT dataset synthetically (seeded with 28 real weak-supervision pairs), LoRA fine-tune on the HF bf16 checkpoint, quantize to GGUF, and gate the candidate with the existing spec-005 CI infrastructure before ever swapping the deployed model."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A held-out check exists that can't be gamed by the training data itself (Priority: P1)

Before any training data is generated, a large, previously-unused batch of evaluation stories is promoted into a real, scored evaluation group, and is placed permanently off-limits as a training-data source. Its entire value is being a signal nobody — not the training-data generation process, not the person building it — ever saw or could have shaped.

**Why this priority**: Every other story in this feature produces a number ("Recall@5 improved to X"), but with the existing gate this small (`positive` is N=4 stories), that number alone can't distinguish a fine-tune that generalized from one that memorized its own training distribution. This check has to exist and be locked *before* any training data is built, or it can never do this job — sequencing, not just presence, is what makes it valid.

**Independent Test**: Promote the existing staged story batch into a scored evaluation group and confirm it reports a result today, before any new training data exists. Confirm there is a clear, checkable rule (not tribal knowledge) that this group must never appear in training data, at any point, before or after promotion.

**Acceptance Scenarios**:

1. **Given** a large, previously-generated, spot-checked story batch sitting unused, **When** it is promoted into the evaluation harness, **Then** it reports Recall@5/Precision@5 results like every other scenario group, using the same tooling.
2. **Given** the held-out group has been promoted, **When** anyone later assembles or expands the training dataset (User Story 2), **Then** there is an explicit, documented rule preventing that group's stories from being included, and no process step relies on someone simply remembering not to.
3. **Given** training data generation is about to begin, **When** its content is checked against the held-out group's story premises/domains, **Then** deliberate overlap is avoidable because the held-out group's content is known and diff-able in advance.

---

### User Story 2 - A training dataset good enough to attempt a fine-tune exists (Priority: P1)

A maintainer needs a labeled dataset of `(story, bias_ids)` pairs suitable for training, built from a combination of the small amount of real production data available today and newly generated synthetic stories, without waiting on the cross-repo data-retention question this feature explicitly does not solve.

**Why this priority**: This is the actual bottleneck. Without a real, sufficiently large, validated, and spot-checked dataset, there is nothing to fine-tune with — every downstream story (LoRA training, evaluation, shipping) depends on this existing first, and it's also where most of the volume of work and risk of quiet quality problems (mislabeled data, narrow domain coverage, contaminated overlap with eval) actually lives.

**Independent Test**: Produce a dataset file covering all four scenario groups, meeting the volume and per-bias coverage targets, with every label validated against the bias catalog and a human-reviewed sample passing spot-check — independent of whether a LoRA run has happened yet.

**Acceptance Scenarios**:

1. **Given** existing production records with confirmed bias labels and recoverable story fragments, **When** they are reconstructed into training pairs, **Then** they are included in the dataset and clearly marked as fragment-based, not full-story, examples.
2. **Given** newly generated synthetic stories from multiple genuinely different sources, **When** they are labeled by a single consistent labeling process, **Then** every label is checked against the current bias catalog before entering the dataset, and any label naming a bias outside that catalog is rejected outright rather than silently coerced or dropped.
3. **Given** a sample of the labeled dataset, **When** a human reviews it before the dataset is trusted, **Then** the review outcome (pass/fail rate) determines whether the batch is usable as-is or must be regenerated — an unreviewed batch is never used for training.
4. **Given** the assembled dataset, **When** its coverage is checked, **Then** it spans all four scenario groups, meets a minimum-examples-per-bias floor across the full bias catalog, includes a meaningful share of bias-free ("negative") examples, and spans multiple content domains and writing styles rather than concentrating in whichever came easiest to generate.
5. **Given** the dataset is being assembled, **When** its story premises are compared against both the existing small evaluation groups and the newly-promoted held-out group (User Story 1), **Then** deliberate topical overlap is avoided.

---

### User Story 3 - A fine-tuned candidate is produced with reproducible provenance (Priority: P2)

Given a validated training dataset, a maintainer runs a fine-tuning pass entirely on free-tier hardware and ends up with a candidate model in the same runtime format the production system already loads, along with a record of exactly how it was produced.

**Why this priority**: Lower priority than having the data itself (User Story 2), since a training run is comparatively mechanical once good data exists — but still has to happen before there's anything to evaluate or ship, and without a reproducibility record, a later "why did this candidate behave differently" question becomes unanswerable, breaking a discipline this project already treats as non-negotiable for baselines and eval runs.

**Independent Test**: Run the fine-tuning process against a validated dataset end-to-end and confirm it produces a runtime-loadable candidate plus a written record of the dataset version, training configuration, and base model revision used — without needing to touch the production configuration to do so.

**Acceptance Scenarios**:

1. **Given** a validated training dataset, **When** fine-tuning runs, **Then** it trains against the full-precision base checkpoint (not the already-quantized runtime format), holds out a validation split from that same dataset, and keeps the best-performing checkpoint by that validation signal rather than automatically using whichever checkpoint finishes last.
2. **Given** a completed training run, **When** its output is prepared for evaluation, **Then** it is converted into the exact runtime format the production system already loads, requiring no other code changes to be evaluable.
3. **Given** a completed training run, **When** it finishes, **Then** a record is produced capturing what data, configuration, and base model version produced it, sufficient for someone else to understand or reproduce the result later.
4. **Given** only free-tier compute and storage are available, **When** any step of this process runs, **Then** it completes within those constraints or explicitly flags where it cannot, rather than silently assuming paid resources.

---

### User Story 4 - The candidate only ships if it clears the existing quality bar (Priority: P2)

A maintainer evaluates a fine-tuned candidate using the same automated quality gate already built for every other change to this system, and the candidate is only promoted to production if it clears a concrete, pre-agreed numeric bar — not a subjective "looks better" judgment.

**Why this priority**: This is what makes the whole effort trustworthy rather than wishful — without a hard, pre-committed bar checked by existing, already-trusted tooling, "should we ship this" becomes a judgment call made fresh (and inconsistently) every time. It's ordered after User Story 3 because there's nothing to gate until a candidate exists, but it's what determines whether any of the preceding work actually pays off.

**Independent Test**: Point the existing evaluation tooling at a candidate model (real or a deliberately-degraded stand-in) and confirm it is scored, compared against both the standard scenario groups and the held-out group from User Story 1, and blocked from being described as ready to ship when it misses the numeric bar — with no separate, new evaluation mechanism required.

**Acceptance Scenarios**:

1. **Given** a fine-tuned candidate, **When** it is evaluated, **Then** the same regression-comparison tooling already used for every pull request scores it against the currently promoted production result, per scenario group — and this includes the held-out group only if the promoted baseline being compared against was itself re-promoted after that group's promotion (User Story 1); a baseline that predates the held-out group's promotion silently omits it from the comparison rather than erroring.
2. **Given** a candidate's evaluation result, **When** its primary quality metric fails to reach the pre-agreed numeric bar, **Then** it is not promoted to production, and the outcome is "keep iterating on data," not a judgment call made in the moment.
3. **Given** a candidate clears the primary bar, **When** its other scenario groups are checked, **Then** it must not have regressed any group past that group's own existing eligibility/tolerance rule, and must not have improved recall by sacrificing precision.
4. **Given** a candidate is approved to ship, **When** it is promoted, **Then** switching production to it requires only a configuration change, and the existing scheduled production-quality monitor confirms nothing regressed live afterward.

---

### Edge Cases

- What happens if the held-out group (User Story 1) is accidentally included in a later training-data expansion, e.g. by someone who doesn't know the rule? The dataset-assembly process must make this checkable (the held-out group's contents are known and named), not merely documented in prose that can be missed.
- What happens if a labeling pass produces a bias id that looks plausible (a near-miss spelling, or a human-readable name instead of the catalog id) but isn't in the current catalog? That row is rejected outright, not coerced to the nearest valid id and not silently dropped while the rest of a multi-label row is kept.
- What happens if the human spot-check (User Story 2) finds a high failure rate in a generated batch? That batch is not partially salvaged — the generation step is fixed and the batch is regenerated, since a high failure rate signals a systemic labeling or generation problem, not isolated bad luck.
- What happens if free-tier disk space is insufficient for the LoRA merge step's full-precision intermediate? The process quantizes directly from the merged checkpoint without a separate full-precision save, rather than assuming headroom that may not exist.
- What happens if a candidate clears the primary recall bar but only by naming more biases across the board (inflating recall by sacrificing precision)? It does not ship — User Story 4's Scenario 3 explicitly requires checking for this trade-off, not just the single headline number.
- What happens the first time this whole process runs, with no prior fine-tuned candidate to compare against? There is nothing to compare a candidate to except the currently promoted production baseline (the existing eval infrastructure already handles this) — no separate "first fine-tune" special case is needed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST promote the existing staged, previously-generated story batch into a real, scored evaluation group before any new training data is generated.
- **FR-002**: The system MUST prevent the held-out evaluation group's stories from ever being included in the training dataset, at any point in time, and this rule MUST be checkable rather than relying solely on documentation.
- **FR-003**: The system MUST reconstruct training pairs from existing production records where a real story fragment and a confirmed bias label both exist, and MUST mark these as fragment-based examples distinct from full synthetic stories.
- **FR-004**: The system MUST generate new synthetic training stories using genuinely different generation sources — different providers or model families, not merely different tiers or versions within the same family (e.g. two tiers of the same underlying model share too much stylistic similarity to count as diverse) — spread across all four evaluation scenario groups.
- **FR-005**: The system MUST label every generated story using one consistent labeling process for this initial dataset, and MUST validate every resulting label against the current bias catalog before it enters the dataset, rejecting any label naming a bias outside that catalog.
- **FR-006**: The system MUST subject a human-reviewed sample of the labeled dataset to spot-check before the dataset is used for training, and MUST NOT use an unreviewed batch for training.
- **FR-007**: The system MUST track dataset coverage against a minimum-examples-per-bias floor across the full bias catalog, a minimum share of bias-free examples, and diversity across content domains and writing styles — not total volume alone. Bias-free examples MUST be generated as genuinely mundane, low-narrative-tension content (e.g. routine summaries, logs, ordinary procedural accounts) where absence of a bias pattern is the natural, unprompted default — not by asking a generator to "write a story with no bias," which tends to produce narratively active content that inadvertently exhibits a bias anyway while still being labeled bias-free.
- **FR-008**: The system MUST avoid deliberate overlap between generated training story premises and the premises of existing evaluation scenarios, including the newly-promoted held-out group.
- **FR-009**: The system MUST train the fine-tuned candidate on the exact same base model family and size currently deployed (as of this feature's writing, `google/gemma-3-4b-it`'s full-precision checkpoint) — not the already-quantized runtime format, and not a different size within the same family (e.g. a larger variant), since a differently-sized checkpoint would still be "full-precision, not quantized" but could fail to fit the free-tier deployment target in a way that only surfaces after training completes. This requirement tracks whichever model is currently deployed per the governing ADR, not a permanent commitment to one specific model — if the deployed cartridge changes in a later ADR, this requirement is re-derived from that ADR, not assumed stale-but-harmless.
- **FR-010**: The system MUST hold out a validation split from the training dataset itself and select the best-performing checkpoint by that validation signal, rather than defaulting to whichever checkpoint a training run finishes on.
- **FR-011**: The system MUST convert a completed fine-tuned candidate into the same runtime format the production system already loads, requiring no other code changes to become evaluable.
- **FR-012**: The system MUST record, for every fine-tuned candidate produced, the training dataset version and composition, training configuration, base model revision, and the resulting evaluation outcome.
- **FR-013**: The system MUST evaluate every fine-tuned candidate using the existing regression-comparison tooling, comparing it against the currently promoted production result per scenario group, including the held-out group. Because that tooling compares against whichever groups the *promoted baseline itself* contains, the held-out group MUST be included in a promoted baseline (a deliberate re-promotion after User Story 1) before this requirement can be satisfied — promoting the held-out evaluation group alone is not sufficient by itself.
- **FR-014**: The system MUST NOT permit a fine-tuned candidate to be promoted to production unless its primary quality metric meets or exceeds the pre-agreed numeric bar.
- **FR-015**: The system MUST NOT permit a fine-tuned candidate to be promoted to production if it regresses any other scenario group past that group's own existing eligibility/tolerance rule, or improves its primary metric at the cost of a precision trade-off.
- **FR-016**: The system MUST make promoting an approved candidate to production a configuration-only change, with no other code changes required.
- **FR-017**: The system MUST NOT use the labeling process's own teacher model to construct or label any evaluation scenario, to avoid a candidate being judged by the same source it was trained to imitate.
- **FR-018**: The system MUST complete every step of dataset generation, training, and conversion within free-tier compute and storage constraints, or explicitly flag the specific step where it cannot.
- **FR-019**: The training process MUST apply the base model's own chat template to every training example and MUST train only on the completion portion of each example (loss masked on the prompt), matching the exact input/output shape `src/llm/generator.py` sends and expects at inference time — training on a different shape (raw concatenated text, or including the prompt in the loss) would optimize for an input distribution the deployed system never actually produces.
- **FR-020**: The training process MUST serialize each example's target labels as the same machine-parseable format `src/llm/prompt.py`'s parser expects (a JSON array of strings), not a language-native list representation — a target the production parser cannot read would make the fine-tune's effect invisible at inference time regardless of training loss.
- **FR-021**: The LoRA configuration MUST explicitly target both the attention and the feed-forward (MLP) projection layers, verified against the actual base model's module names rather than accepted as a library default — an unverified default target list can silently train near-zero effective parameters while still reporting a completed run.
- **FR-022**: Before a fine-tuned candidate replaces the deployed model, the system MUST re-check every existing model/environment-quirk workaround tag in the source tree against the new candidate, per this repository's existing convention for any model swap, and MUST NOT assume workarounds written for the previous model still apply unchanged.

### Key Entities

- **Held-out evaluation group**: A previously-generated, spot-checked batch of stories promoted into the evaluation harness specifically to detect memorization rather than generalization; permanently excluded from training data by rule.
- **Weak-supervision pair**: A training example reconstructed from real production data consisting of a partial/fragmentary story excerpt and a confirmed bias label, distinct from a full synthetic story example.
- **Synthetic training example**: A generated `(story, bias_ids)` pair produced by a generation source and validated labeling process, tagged separately from weak-supervision pairs so its contribution can be measured independently.
- **Fine-tuned candidate**: A LoRA-adapted, merged, and quantized model artifact in the production runtime format, accompanied by a reproducibility record (manifest) of how it was produced.
- **Ship gate result**: The outcome of evaluating a fine-tuned candidate against the existing regression-comparison tooling, determining whether it meets the pre-agreed numeric bar required for production promotion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The held-out evaluation group is promoted and reporting real evaluation results before a single new training story is generated.
- **SC-002**: The assembled training dataset reaches at least 300 stories, meets a minimum per-bias-id coverage floor across the full bias catalog, and includes at least 20% bias-free examples, with 100% of included labels validated against the current bias catalog.
- **SC-003**: A fine-tuned candidate is produced end-to-end (training through runtime-format conversion) using only free-tier compute and storage, with a complete reproducibility record.
- **SC-004**: A fine-tuned candidate's primary scenario group reaches Recall@5 ≥ 0.85 before it is promoted to production; candidates below that bar are not shipped, and this determination requires no subjective judgment call.
- **SC-005**: A fine-tuned candidate that clears the primary bar by trading away precision, or by regressing any other scenario group past its own eligibility/tolerance rule, is not promoted to production.
- **SC-006**: Once a candidate is approved, switching production to it requires exactly one configuration change and no other code changes.

## Assumptions

- The cross-repo question of whether `biassemble-core` should begin retaining full story text for training purposes is out of scope for this feature; the training dataset works within what is recoverable from existing data today (fragmentary excerpts) plus newly generated synthetic content.
- The existing bias catalog (38 ids) and the existing prompt output contract (`(story) -> bias_ids: string[]`) are treated as fixed for this feature — changing either at the same time as fine-tuning the model would make it impossible to attribute a quality change to either one.
- "One consistent labeling process" for this initial dataset is a bootstrap choice, not a permanent policy — future rounds may prefer richer, assessment-confirmed production labels once enough real volume exists, but that is out of scope for this feature's first dataset.
- The pre-agreed numeric ship bar (Recall@5 ≥ 0.85 on the primary scenario group) is inherited unchanged from the existing production quality target; this feature does not renegotiate that number.
- Free-tier compute/storage availability and specific tooling choices (which LoRA library, which generation providers) are implementation details left to whoever executes this feature, not decisions this specification locks in.
- The existing CI regression-comparison tooling (per-group eligibility/tolerance rules, exit-code semantics) is treated as already correct and sufficient for gating a fine-tuned candidate; this feature does not modify that tooling's code, only uses it. That tooling compares a run against whichever groups a *promoted baseline* already contains — it does not discover new groups on its own — so a manual baseline re-promotion after the held-out group is promoted (User Story 1) is a real, human, out-of-band prerequisite this feature depends on, in the same spirit as `evaluations/baselines/`'s existing promotion step always being manual (spec-005's FR-013), not a gap in the tooling itself.
