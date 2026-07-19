# Training Data Generation Prompt — Biassemble Fine-Tune (v2)

**Feeds**: `specs/006-fine-tune-llm` T012 (`scripts/generate_sft_stories.py`, not yet implemented) — this file is the human-in-the-loop version of that script's generation logic, run manually across multiple LLM providers until T012 exists to automate it. Whatever `generation_prompt_version` gets recorded in `SyntheticStoryRecord`/`SftExample` rows (data-model.md) should point back to this file's version (`v2`).

**v1** existed only in chat, never saved as a file — not reconstructed here since v2 supersedes it entirely; no functional loss.

### Changes from v1
Adversarial label semantics corrected (see Decision Block below — turned out to be a citation fix, not a new decision), narrator-person rule added, second length band, per-run rotation slots, verification pipeline attached.

### How to use this file
Read the **Decision Block** once (nothing to decide — it's already true, just know it before generating). Then loop: fill the **Rotation Slots** → run the **Prompt** in a provider → run the **Pipeline** on the output → update your rotation state → repeat. See **Run Instructions** at the bottom for the concrete step-by-step.

---

## Decision Block (already settled — cite, don't re-decide)

**Adversarial semantics**: this dataset labels adversarial stories WITH the bias ids the narrator's rhetoric exploits (`target_bias_ids` non-empty, never `[]`). **This is not a new choice for this feature — it's already the established convention in this repo**, confirmed by direct inspection:

- `hypotheses/v2.yaml`'s own header comments (lines 5-8) document exactly this: `framing_effect` covers "deploying gain/loss language rhetorically," `availability_heuristic` covers "rhetorical invocation to override base rates," `affect_heuristic` covers "directing audience to trust feelings over data."
- Both real adversarial eval scenarios already do this: `evaluations/adversarial/manipulative_narrative.json` → `["availability_heuristic", "affect_heuristic", "framing_effect"]`; `evaluations/adversarial/politician_speech.json` → `["confirmation_bias", "framing_effect", "overconfidence_bias"]`.

Nothing to write into an ADR — the convention already exists and this prompt just follows it. (If it's ever useful to have a one-line pointer from `adr/005` to this file, that's a separate, small ask — not done here.)

---

## The Generation Prompt

One batch = 40 stories. Fill the three `{{ROTATION}}` slots and `{{BATCH_ID}}` before each run — see Run Instructions for what goes in them.

```
Generate 40 short synthetic training stories for a cognitive-bias detection system. Output ONLY a JSON array of 40 objects, nothing else — no intro text, no explanation, no markdown fences.

The 38 valid bias ids (use ONLY these exact strings, nothing else):
affect_heuristic, ambiguity_effect, anchoring_bias, authority_bias, availability_heuristic, bandwagon_effect, base_rate_neglect, choice_supportive_bias, confirmation_bias, curse_of_knowledge, decoy_effect, dunning_kruger_effect, escalation_of_commitment, framing_effect, fundamental_attribution_error, gamblers_fallacy, halo_effect, hindsight_bias, hot_hand_fallacy, illusion_of_control, in_group_bias, loss_aversion, narrative_fallacy, negativity_bias, omission_bias, optimism_bias, overconfidence_bias, planning_fallacy, projection_bias, recency_bias, representativeness_heuristic, self_serving_bias, spotlight_effect, status_quo_bias, stereotyping_bias, sunk_cost_fallacy, survivorship_bias, zero_risk_bias

COVERAGE FOR THIS BATCH: Prioritize these under-represented bias ids (fill from corpus coverage counter before each run): {{ROTATION_BIASES — e.g. omission_bias, curse_of_knowledge, zero_risk_bias, projection_bias, decoy_effect, ambiguity_effect, spotlight_effect, choice_supportive_bias}}. Distribute the rest as evenly as reasonably possible. Do NOT use confirmation_bias, anchoring_bias, sunk_cost_fallacy, authority_bias, or availability_heuristic more than twice each in this batch.

ANTI-CHEATING RULE: Do not pick a bias id first and then write a story to fit it. Instead, first imagine a realistic, specific situation, then decide the minimal set of bias ids that genuinely explain the reasoning shown. Every target_bias_ids entry must be directly and clearly supported by the story — no speculative or weak labels. If a situation shows no clear bias, it belongs in the negative group, not in positive with a stretched label.

NARRATOR PERSON (train/serve match — production input is personal stories):
- "positive" and "edge": predominantly FIRST PERSON ("I", "my", "we") — at least 8 of 10 in each group. The narrator is inside the reasoning and unaware of the flaw: no self-diagnosis, no hindsight framing like "I realize now".
- "adversarial": first or second person — the narrator addresses an audience.
- "negative": impersonal, objective, no narrator judgment.

Split the 40 stories like this:
- 10 stories, group "positive": clearly exhibits 1-3 bias ids. Prefer realistic everyday situations over textbook demonstrations.
- 10 stories, group "edge": exhibits 1-2 bias ids, but subtly — a case a careful reviewer might genuinely debate. The story should remain plausible even if a reviewer ultimately decides no bias is present. (These labels receive mandatory human review downstream — still label your honest best judgment.)
- 10 stories, group "adversarial": the narrator intentionally tries to persuade, sell, recruit, convince, or manipulate the audience (a speech, an ad, a pitch, a social media post) exploiting 1-2 bias ids. Label the ids the rhetoric EXPLOITS in the audience. The exploitation must arise naturally from the rhetoric, never be stated.
- 10 stories, group "negative": genuinely mundane, low-narrative-tension content with ZERO bias — a schedule, a recipe, a product changelog, a weather report, a historical summary, meeting notes, a maintenance log. No personal opinions, recommendations, predictions, preferences, or evaluative language (never "the technician wisely..." or "this was the right call") — objective informational content only. No character makes any notable judgment call. target_bias_ids must be [] for every one of these.

LENGTH BANDS (production stories vary widely — match that):
- 7 of 10 in each of positive/edge/adversarial: 2-4 sentences, 50-90 words.
- 3 of 10 in each of positive/edge/adversarial: 120-250 words, multi-paragraph allowed — a fuller narrative where the bias emerges across the account rather than in one sentence.
- negative: 40-120 words.

Rules for "positive"/"edge"/"adversarial" stories:
- Specific and realistic — not cartoonish. Show the bias through behavior and reasoning. NEVER use the words "bias," "fallacy," "heuristic," or "effect," and never name the bias directly.
- Domains FOR THIS BATCH — use primarily this rotation set, spread across it: {{ROTATION_DOMAINS — pick ~10 per run from: finance, management, consumer, legal, medical, social, family, education, technical, political, astronomy, mycology, woodworking, competitive sailing, bird banding, textile conservation, historical linguistics, bonsai cultivation, paleontology, aquarium keeping, beekeeping, community theater, long-haul trucking, wildlife rescue, ceramics, orienteering}}. At least 4 of the 30 biased stories must be in out-of-field (non-business, non-medical) domains.
- Avoid repeating sentence openings, narrative structure, or wording across stories — don't let multiple stories start with "When...", "After...", or "I realized...". Additionally, avoid these openings entirely this batch (used in prior batches): {{ROTATION_BANNED_OPENINGS — maintained list, e.g. "Last week", "My colleague", "For years"}}.
- Each story's style_tag must be one of: diary, incident_report, email, forum_post, interview, newspaper, field_notes, maintenance_log, lab_notebook, witness_statement, lecture_notes, chat_message, voice_memo_transcript, support_ticket. Use a good spread; no style more than 5 times per batch.
- Vary tone/formality (tone_tags free text: regretful, clinical, urgent, wry, defensive, matter-of-fact, enthusiastic, weary).

Output format — a JSON array of exactly 40 objects, each shaped like:
{"id": "pos_001", "story": "...", "group": "positive", "domain": "finance", "target_bias_ids": ["anchoring_bias", "sunk_cost_fallacy"], "style_tags": ["diary"], "tone_tags": ["regretful"]}

Use sequential ids per group with the batch prefix {{BATCH_ID}}: {{BATCH_ID}}_pos_001-010, {{BATCH_ID}}_edge_001-010, {{BATCH_ID}}_adv_001-010, {{BATCH_ID}}_neg_001-010.

Generate the 40 stories now.
```

---

## Pipeline (around every batch — the labels are ground truth, treat them like audit findings)

1. **Schema gate (script, not eyes):** parse JSON; reject-and-retry on fences, count ≠ 40, invalid bias ids, wrong group sizes, person-rule violations detectable by pronoun heuristic, length-band violations. Never hand-fix a malformed batch.
2. **Blind quorum relabel:** strip labels, send stories to a DIFFERENT model family with "list the bias ids present (or none)". Agreement → keep. Disagreement on positive/adversarial → drop or human-review. This is the audit review-quorum discipline pointed at our own data. **Known gap, not applied to the existing 879-row synthetic corpus**: T013 ended up using a single consistent teacher model (DeepSeek) for all labeling, with a 20-row manual spot-check as the only quality gate (see `candidate-2026-07-18-results.md`'s "single-teacher labeling... known concentration risk" note) — this step's cross-model quorum check was never actually run against that corpus. Label errors from any systematic DeepSeek blind spot would be invisible in the current dataset and would need this step applied retroactively (or a second labeling pass compared against the first) to surface. Apply it for real on the next batch rather than assuming it's already covered.
3. **Edge group: 100% human review.** Ten stories, minutes. Ambiguity labeled by one AI's opinion is not ground truth. ~~Option (recommended): route reviewed edge stories to the EVAL pool, not training.~~ **Superseded by `contracts/sft-dataset-schema.md`'s group-coverage rule** (enforced by `scripts/assemble_sft_dataset.py`, `REQUIRED_GROUPS = {"positive","negative","edge","adversarial"}`): the assembled dataset requires `edge`-group rows to actually be *in* training, not routed to eval — the two were never reconciled when this recommendation was written, and the real 907-row dataset kept edge stories in training, not eval, because the schema contract requires it. If a future batch wants edge routed to eval instead, that requires relaxing the schema's `REQUIRED_GROUPS` rule first, not just following this line — don't let the two documents disagree silently again.
4. **Cross-corpus dedup:** embed all accepted stories; drop anything > ~0.90 cosine against the accumulated training corpus.
5. **Leakage gate (iron rule):** every accepted story checked against the read-only eval set AND against any production stories destined for eval — > ~0.85 cosine = cut. The eval set never sees its own paraphrases in training.
6. **Coverage counter:** update per-bias counts across the whole corpus; the counter fills next batch's `{{ROTATION_BIASES}}`. Even coverage is measured, not hoped.
7. **Model rotation:** alternate generation between at least two model families across batches (fingerprint defense). Record generator model + prompt version per story in metadata. **Field-semantics note**: `scripts/assemble_sft_dataset.py` actually populates `generation_prompt_version` from each row's `batch_tag` (e.g. `"b1"`, `"b5"`), not this file's own version string (`"v2"`). For the current dataset this distinction happens to not matter in practice — every batch (`b1`-`b6`) was generated under this same v2 prompt, so there's no real v1/v2 mixing to lose track of — but the field as populated cannot answer "which *prompt template version* generated this row" if a future dataset actually mixes prompt versions across batches. Fix before that happens: either rename the field to reflect what it actually stores (batch identity), or add a second field for literal prompt-template version.
8. **Volume note:** 40 stories is one seed. For 38 classes, plan ~15-25 verified batches before fine-tuning; check per-class minimums (aim ≥ 25-30 positive examples per bias post-verification) before starting a training run.

---

## Run Instructions

**State to track between batches** (a plain text note or spreadsheet is fine at this stage — no tooling required):
- `coverage_counter`: running count of accepted stories per bias id, across all batches so far. Recompute after every batch's pipeline step 6.
- `banned_openings`: growing list of sentence openings already overused (feed into the next batch's `{{ROTATION_BANNED_OPENINGS}}`).
- `batch_log`: which provider generated each `{{BATCH_ID}}`, so step 7's model rotation is actually verifiable, not just assumed.

**Per-batch loop:**

1. **Fill the rotation slots.** `{{ROTATION_BIASES}}` = the 8-10 lowest counts in `coverage_counter` right now. `{{ROTATION_DOMAINS}}` = pick ~10 from the list, rotating away from whatever you used last batch. `{{ROTATION_BANNED_OPENINGS}}` = your running list. `{{BATCH_ID}}` = a short tag identifying provider + sequence, e.g. `gpt1`, `claude1`, `deepseek1`.
2. **Paste the filled prompt into one provider.** Alternate providers batch-to-batch (pipeline step 7) — don't run 5 batches through the same model in a row.
3. **Save the raw output** as `{{BATCH_ID}}.json` (e.g. `gpt1.json`) in a scratch location — not `evaluations/sft/` yet, these aren't validated.
4. **Run the pipeline steps against that file, in order** — right now, before T012/T013/T016 exist as real scripts, steps 1 (schema gate) and 2 (blind quorum relabel) are the ones worth doing manually or by asking me to do them per batch: I can parse and validate the JSON against the schema/group-size/length-band rules (step 1) and, separately, re-read the stories blind (no labels shown) and give my own bias-id judgment for comparison against the batch's own labels (step 2's quorum check, using me as the "different model family" — if the batch came from GPT, I'm already a different family; if it came from me, ask GPT or DeepSeek to do this pass instead). Steps 4-5 (embedding-based dedup/leakage) need actual embeddings and can wait until enough batches exist to make that worthwhile, or until `scripts/assemble_sft_dataset.py` (T016) exists to do it properly — don't hand-eyeball cosine similarity.
5. **Human-review the 10 edge stories** (step 3) — always, every batch, no shortcuts.
6. **Update `coverage_counter` and `banned_openings`** from what survived review.
7. **Repeat** with a different `{{BATCH_ID}}`/provider until `coverage_counter` shows every bias id at or above its target minimum (~25-30 positive examples per id, pipeline step 8) — expect this to take on the order of 15-25 batches total, not one or two.

**When you're ready for a batch**, send me the raw output file or paste its content and tell me which pipeline step you want run on it — I'll do the schema gate and/or blind relabel pass rather than you doing it by eye.
