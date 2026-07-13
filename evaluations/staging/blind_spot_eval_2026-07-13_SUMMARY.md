# Blind-spot eval batch — 2026-07-13

Staged results from running 80 DeepSeek-generated eval stories (8 batches, in-field vs out-of-field domain axis) through the deployed `llm_union` engine (`google_gemma-3-4b-it`, HF Space `Leminds/biassemble-engine`). **Not yet promoted** to `evaluations/<group>/` — spot-check before merging.

Raw per-story results: `blind_spot_eval_2026-07-13.json` (same directory).

## Data-quality flags

- **Invalid expected_bias_id**: `adv_005` (mycology, adversarial, out_of_field) proposed `scarcity_bias`, which is **not** in the 38-id catalog. Dropped from scoring for that story (scored against `bandwagon_effect` only). Needs a decision: map to an existing id (closest: none — `scarcity_bias`/urgency framing isn't currently covered) or drop the label.
- **Duplicate source file**: `deepseek_json_20260713_bb12d7.json` was a truncated duplicate of `deepseek_json_20260713_bb12d7 (1).json` (cut off mid-story-4). Used the `(1)` version only; the truncated one was skipped entirely, not double-counted.
- **Errors**: 0 / 80 requests failed (all HTTP 200, valid JSON).

## Summary — in-field vs out-of-field

| Group | Familiarity | N | Avg recall | Hit | Partial | Miss | False positive | Avg latency (s) |
|---|---|---|---|---|---|---|---|---|
| adversarial | in_field | 10 | 0.800 | 6 | 4 | 0 | 0 | 21.1 |
| adversarial | out_of_field | 10 | 0.700 | 5 | 4 | 1 | 0 | 19.4 |
| edge | in_field | 10 | 0.500 | 5 | 0 | 5 | 0 | 17.0 |
| edge | out_of_field | 10 | 0.500 | 5 | 0 | 5 | 0 | 13.3 |
| negative | in_field | 10 | n/a | 0 | 0 | 0 | 10 | 13.9 |
| negative | out_of_field | 10 | n/a | 0 | 0 | 0 | 10 | 11.4 |
| positive | in_field | 10 | 0.450 | 2 | 5 | 3 | 0 | 19.9 |
| positive | out_of_field | 10 | 0.300 | 0 | 6 | 4 | 0 | 18.1 |

**Reading the blind-spot axis:**
- `positive`: out-of-field recall 0.300 vs in-field 0.450 — worse on novel domains, as expected (engine's LLM-union has less to anchor on when vocabulary is unfamiliar).
- `adversarial`: out-of-field 0.700 vs in-field 0.800 — smaller gap; manipulation tactics (authority, bandwagon, framing) apparently transfer across domains better than the more abstract reasoning-error biases in `positive`/`edge`.
- `edge`: 0.500 vs 0.500 (identical) — each story carries exactly one expected id, so this is 5/10 vs 5/10 binary hits; coincidental tie, not evidence of no gap. Needs a bigger N before trusting this axis for `edge`.
- `negative`: 100% false-positive rate in **both** buckets — confirms the known, accepted architecture gap (no neutral-gate at the engine; downstream LLM in biassemble-core is supposed to reject these). Not a blind-spot finding, a re-confirmation of a known limit.

## Per-story detail

| scenario_id | domain | familiarity | expected | retrieved | verdict |
|---|---|---|---|---|---|
| neg_006 | astronomy | out_of_field | — | narrative_fallacy, status_quo_bias | false_positive |
| neg_007 | mycology | out_of_field | — | affect_heuristic, ambiguity_effect, anchoring_bias, authority_bias, availability_heuristic, bandwagon_effect, base_rate_neglect, choice_supportive_bias, confirmation_bias, curse_of_knowledge, decoy_effect, dunning_kruger_effect, escalation_of_commitment, framing_effect, fundamental_attribution_error, gamblers_fallacy, halo_effect, hindsight_bias, hot_hand_fallacy, illusion_of_control, in_group_bias, loss_aversion, narrative_fallacy, negativity_bias, omission_bias, optimism_bias, overconfidence_bias, planning_fallacy, projection_bias, recency_bias, representativeness_heuristic, self_serving_bias, spotlight_effect, status_quo_bias, stereotyping_bias, sunk_cost_fallacy, survivorship_bias, zero_risk_bias | false_positive |
| neg_008 | woodworking | out_of_field | — | representativeness_heuristic, status_quo_bias | false_positive |
| neg_009 | competitive_sailing | out_of_field | — | narrative_fallacy, status_quo_bias | false_positive |
| neg_010 | bird_banding | out_of_field | — | affect_heuristic, ambiguity_effect, anchoring_bias, authority_bias, availability_heuristic, bandwagon_effect, base_rate_neglect, choice_supportive_bias, confirmation_bias, curse_of_knowledge, decoy_effect, dunning_kruger_effect, escalation_of_commitment, framing_effect, fundamental_attribution_error, gamblers_fallacy, halo_effect, hindsight_bias, hot_hand_fallacy, illusion_of_control, in_group_bias, loss_aversion, narrative_fallacy, negativity_bias, omission_bias, optimism_bias, overconfidence_bias, planning_fallacy, projection_bias, recency_bias, representativeness_heuristic, self_serving_bias, spotlight_effect, status_quo_bias, stereotyping_bias, sunk_cost_fallacy, survivorship_bias, zero_risk_bias | false_positive |
| neg_011 | aquarium_keeping | out_of_field | — | affect_heuristic, ambiguity_effect, anchoring_bias, authority_bias, availability_heuristic, bandwagon_effect, base_rate_neglect, choice_supportive_bias, confirmation_bias, curse_of_knowledge, decoy_effect, dunning_kruger_effect, escalation_of_commitment, framing_effect, fundamental_attribution_error, gamblers_fallacy, halo_effect, hindsight_bias, hot_hand_fallacy, illusion_of_control, in_group_bias, loss_aversion, narrative_fallacy, negativity_bias, omission_bias, optimism_bias, overconfidence_bias, planning_fallacy, projection_bias, recency_bias, representativeness_heuristic, self_serving_bias, spotlight_effect, status_quo_bias, stereotyping_bias, sunk_cost_fallacy, survivorship_bias, zero_risk_bias | false_positive |
| neg_012 | textile_conservation | out_of_field | — | planning_fallacy, base_rate_neglect | false_positive |
| neg_013 | historical_linguistics | out_of_field | — | representativeness_heuristic, base_rate_neglect | false_positive |
| neg_014 | bonsai_cultivation | out_of_field | — | status_quo_bias | false_positive |
| neg_015 | paleontology | out_of_field | — | narrative_fallacy, status_quo_bias | false_positive |
| neg_016 | technical | in_field | — | recency_bias, optimism_bias, planning_fallacy, escalation_of_commitment, sunk_cost_fallacy, anchoring_bias, gamblers_fallacy, ambiguity_effect, status_quo_bias, loss_aversion | false_positive |
| neg_017 | educational | in_field | — | planning_fallacy, status_quo_bias, overconfidence_bias, ambiguity_effect, optimism_bias, escalation_of_commitment, loss_aversion, stereotyping_bias, self_serving_bias | false_positive |
| neg_018 | financial | in_field | — | framing_effect, base_rate_neglect, status_quo_bias, self_serving_bias, choice_supportive_bias, hot_hand_fallacy, affect_heuristic | false_positive |
| neg_019 | medical | in_field | — | recency_bias, availability_heuristic, framing_effect, overconfidence_bias | false_positive |
| neg_020 | management | in_field | — | status_quo_bias, narrative_fallacy, zero_risk_bias | false_positive |
| neg_021 | legal | in_field | — | representativeness_heuristic, confirmation_bias, curse_of_knowledge, status_quo_bias, base_rate_neglect, ambiguity_effect, omission_bias, bandwagon_effect, stereotyping_bias, authority_bias | false_positive |
| neg_022 | social | in_field | — | planning_fallacy, status_quo_bias, escalation_of_commitment, decoy_effect | false_positive |
| neg_023 | consumer | in_field | — | availability_heuristic, framing_effect, optimism_bias, gamblers_fallacy, loss_aversion, halo_effect, anchoring_bias, zero_risk_bias, dunning_kruger_effect | false_positive |
| neg_024 | political | in_field | — | status_quo_bias, framing_effect, availability_heuristic, representativeness_heuristic, zero_risk_bias, survivorship_bias | false_positive |
| neg_025 | family | in_field | — | overconfidence_bias, negativity_bias, spotlight_effect, narrative_fallacy, optimism_bias | false_positive |
| adv_004 | astronomy | out_of_field | authority_bias | confirmation_bias, authority_bias, representativeness_heuristic, recency_bias, narrative_fallacy | hit |
| adv_005 | mycology | out_of_field | bandwagon_effect, scarcity_bias ⚠invalid:scarcity_bias | availability_heuristic, bandwagon_effect, framing_effect, confirmation_bias, in_group_bias, recency_bias | hit |
| adv_006 | woodworking | out_of_field | authority_bias | recency_bias, authority_bias, narrative_fallacy, availability_heuristic, in_group_bias | hit |
| adv_007 | competitive_sailing | out_of_field | bandwagon_effect, authority_bias | authority_bias, availability_heuristic, bandwagon_effect, framing_effect, recency_bias, representativeness_heuristic | hit |
| adv_008 | bird_banding | out_of_field | recency_bias, fundamental_attribution_error | confirmation_bias, authority_bias, availability_heuristic, recency_bias, in_group_bias, narrative_fallacy | partial |
| adv_009 | aquarium_keeping | out_of_field | authority_bias, bandwagon_effect | confirmation_bias, bandwagon_effect, availability_heuristic, framing_effect, recency_bias, representativeness_heuristic | partial |
| adv_010 | textile_conservation | out_of_field | authority_bias | representativeness_heuristic, authority_bias, confirmation_bias, framing_effect | hit |
| adv_011 | historical_linguistics | out_of_field | overconfidence_bias, authority_bias | authority_bias, availability_heuristic, confirmation_bias, negativity_bias, representativeness_heuristic | partial |
| adv_012 | bonsai_cultivation | out_of_field | authority_bias, bandwagon_effect | framing_effect, narrative_fallacy, recency_bias, confirmation_bias, availability_heuristic, representativeness_heuristic, sunk_cost_fallacy | miss |
| adv_013 | paleontology | out_of_field | overconfidence_bias, fundamental_attribution_error | confirmation_bias, fundamental_attribution_error, hindsight_bias, negativity_bias | partial |
| adv_014 | legal | in_field | fundamental_attribution_error | halo_effect, fundamental_attribution_error, availability_heuristic, narrative_fallacy, negativity_bias, affect_heuristic, representativeness_heuristic, base_rate_neglect, stereotyping_bias | hit |
| adv_015 | consumer | in_field | authority_bias, bandwagon_effect | representativeness_heuristic, authority_bias, availability_heuristic, framing_effect, narrative_fallacy | partial |
| adv_016 | political | in_field | framing_effect | fundamental_attribution_error, framing_effect, confirmation_bias, negativity_bias, affect_heuristic, escalation_of_commitment, loss_aversion, hindsight_bias, base_rate_neglect, optimism_bias | hit |
| adv_017 | management | in_field | authority_bias | authority_bias, fundamental_attribution_error, framing_effect, confirmation_bias, narrative_fallacy, omission_bias, curse_of_knowledge, base_rate_neglect, in_group_bias, dunning_kruger_effect | hit |
| adv_018 | financial | in_field | bandwagon_effect, recency_bias | bandwagon_effect, authority_bias, representativeness_heuristic, self_serving_bias, escalation_of_commitment, choice_supportive_bias, dunning_kruger_effect, gamblers_fallacy, narrative_fallacy, hindsight_bias | partial |
| adv_019 | educational | in_field | negativity_bias | escalation_of_commitment, affect_heuristic, framing_effect, confirmation_bias, availability_heuristic, base_rate_neglect, negativity_bias | hit |
| adv_020 | social | in_field | negativity_bias, availability_heuristic | authority_bias, confirmation_bias, representativeness_heuristic, base_rate_neglect, availability_heuristic, framing_effect, ambiguity_effect, survivorship_bias, fundamental_attribution_error, stereotyping_bias | partial |
| adv_021 | medical | in_field | authority_bias | framing_effect, base_rate_neglect, curse_of_knowledge, authority_bias, confirmation_bias, stereotyping_bias, anchoring_bias, zero_risk_bias, affect_heuristic | hit |
| adv_022 | technical | in_field | bandwagon_effect, authority_bias | narrative_fallacy, sunk_cost_fallacy, authority_bias, representativeness_heuristic, bandwagon_effect, ambiguity_effect, escalation_of_commitment, survivorship_bias, affect_heuristic, status_quo_bias | hit |
| adv_023 | family | in_field | hindsight_bias, projection_bias | base_rate_neglect, hindsight_bias, confirmation_bias, self_serving_bias | partial |
| edge_003 | astronomy | out_of_field | overconfidence_bias | base_rate_neglect, confirmation_bias, curse_of_knowledge, planning_fallacy, recency_bias, hindsight_bias | miss |
| edge_004 | mycology | out_of_field | status_quo_bias | negativity_bias, confirmation_bias, planning_fallacy | miss |
| edge_005 | woodworking | out_of_field | overconfidence_bias | planning_fallacy, confirmation_bias, recency_bias, representativeness_heuristic | miss |
| edge_006 | competitive_sailing | out_of_field | recency_bias | hindsight_bias, base_rate_neglect, confirmation_bias | miss |
| edge_007 | bird_banding | out_of_field | authority_bias | confirmation_bias, curse_of_knowledge, fundamental_attribution_error, base_rate_neglect, overconfidence_bias, stereotyping_bias | miss |
| edge_008 | aquarium_keeping | out_of_field | availability_heuristic | confirmation_bias, availability_heuristic, representativeness_heuristic, base_rate_neglect | hit |
| edge_009 | textile_conservation | out_of_field | availability_heuristic | fundamental_attribution_error, availability_heuristic, confirmation_bias | hit |
| edge_010 | historical_linguistics | out_of_field | representativeness_heuristic | base_rate_neglect, confirmation_bias, representativeness_heuristic, stereotyping_bias | hit |
| edge_011 | bonsai_cultivation | out_of_field | representativeness_heuristic | representativeness_heuristic, base_rate_neglect, confirmation_bias | hit |
| edge_012 | paleontology | out_of_field | representativeness_heuristic | base_rate_neglect, representativeness_heuristic, confirmation_bias | hit |
| edge_013 | political | in_field | availability_heuristic | confirmation_bias, base_rate_neglect, representativeness_heuristic, authority_bias, in_group_bias, availability_heuristic, negativity_bias, fundamental_attribution_error, bandwagon_effect | hit |
| edge_014 | educational | in_field | halo_effect | recency_bias, in_group_bias, authority_bias, confirmation_bias, base_rate_neglect, representativeness_heuristic, halo_effect | hit |
| edge_015 | financial | in_field | recency_bias | curse_of_knowledge, framing_effect, status_quo_bias, halo_effect, loss_aversion, self_serving_bias, decoy_effect, recency_bias, negativity_bias, survivorship_bias | hit |
| edge_016 | medical | in_field | status_quo_bias | fundamental_attribution_error, confirmation_bias, authority_bias, negativity_bias, stereotyping_bias, overconfidence_bias, dunning_kruger_effect, availability_heuristic, base_rate_neglect, representativeness_heuristic | miss |
| edge_017 | social | in_field | availability_heuristic | availability_heuristic, confirmation_bias, hindsight_bias, recency_bias, representativeness_heuristic, overconfidence_bias, planning_fallacy, narrative_fallacy, status_quo_bias, negativity_bias | hit |
| edge_018 | technical | in_field | planning_fallacy | choice_supportive_bias, overconfidence_bias, representativeness_heuristic, confirmation_bias, authority_bias, dunning_kruger_effect, ambiguity_effect | miss |
| edge_019 | management | in_field | base_rate_neglect | availability_heuristic, confirmation_bias, planning_fallacy, framing_effect, overconfidence_bias, gamblers_fallacy, anchoring_bias, base_rate_neglect, loss_aversion, stereotyping_bias | hit |
| edge_020 | legal | in_field | base_rate_neglect | curse_of_knowledge, representativeness_heuristic, confirmation_bias, availability_heuristic, stereotyping_bias, hindsight_bias, halo_effect, affect_heuristic, anchoring_bias, fundamental_attribution_error | miss |
| edge_021 | consumer | in_field | authority_bias | availability_heuristic, optimism_bias, confirmation_bias, representativeness_heuristic, projection_bias, in_group_bias, negativity_bias, recency_bias, self_serving_bias | miss |
| edge_022 | family | in_field | projection_bias | authority_bias, confirmation_bias, status_quo_bias, stereotyping_bias | miss |
| pos_005 | mycology | out_of_field | overconfidence_bias, availability_heuristic | availability_heuristic, confirmation_bias, hindsight_bias, base_rate_neglect, curse_of_knowledge, negativity_bias | partial |
| pos_006 | bird_banding | out_of_field | recency_bias, overconfidence_bias | recency_bias, fundamental_attribution_error, confirmation_bias, in_group_bias, planning_fallacy | partial |
| pos_007 | aquarium_keeping | out_of_field | availability_heuristic, sunk_cost_fallacy | curse_of_knowledge, authority_bias, confirmation_bias, escalation_of_commitment, planning_fallacy | miss |
| pos_008 | woodworking | out_of_field | sunk_cost_fallacy, confirmation_bias | availability_heuristic, confirmation_bias, escalation_of_commitment, in_group_bias | partial |
| pos_009 | competitive_sailing | out_of_field | overconfidence_bias, availability_heuristic | hindsight_bias, confirmation_bias, availability_heuristic, fundamental_attribution_error, in_group_bias, representativeness_heuristic | partial |
| pos_010 | historical_linguistics | out_of_field | confirmation_bias, overconfidence_bias | base_rate_neglect, confirmation_bias, authority_bias, framing_effect, in_group_bias, negativity_bias, representativeness_heuristic | partial |
| pos_011 | textile_conservation | out_of_field | availability_heuristic, overconfidence_bias | authority_bias, curse_of_knowledge, confirmation_bias, hindsight_bias | miss |
| pos_012 | bonsai_cultivation | out_of_field | status_quo_bias, projection_bias | hindsight_bias, authority_bias, confirmation_bias, negativity_bias | miss |
| pos_013 | astronomy | out_of_field | overconfidence_bias, confirmation_bias | confirmation_bias, fundamental_attribution_error, negativity_bias, hindsight_bias, spotlight_effect, base_rate_neglect, illusion_of_control, ambiguity_effect, availability_heuristic, gamblers_fallacy | partial |
| pos_014 | paleontology | out_of_field | overconfidence_bias, representativeness_heuristic | hindsight_bias, fundamental_attribution_error, authority_bias, confirmation_bias | miss |
| pos_015 | financial | in_field | loss_aversion, confirmation_bias | loss_aversion, escalation_of_commitment, negativity_bias, sunk_cost_fallacy, gamblers_fallacy, anchoring_bias, self_serving_bias, survivorship_bias, choice_supportive_bias, omission_bias | partial |
| pos_016 | medical | in_field | overconfidence_bias, confirmation_bias | framing_effect, authority_bias, base_rate_neglect, curse_of_knowledge, stereotyping_bias, overconfidence_bias, representativeness_heuristic, halo_effect, survivorship_bias, gamblers_fallacy | partial |
| pos_017 | management | in_field | sunk_cost_fallacy, status_quo_bias | escalation_of_commitment, confirmation_bias, optimism_bias, narrative_fallacy, framing_effect, self_serving_bias, planning_fallacy, sunk_cost_fallacy, overconfidence_bias, projection_bias | partial |
| pos_018 | legal | in_field | overconfidence_bias, representativeness_heuristic | halo_effect, gamblers_fallacy, stereotyping_bias, affect_heuristic, overconfidence_bias, authority_bias, base_rate_neglect, in_group_bias, confirmation_bias, representativeness_heuristic | hit |
| pos_019 | social | in_field | overconfidence_bias, hindsight_bias | hindsight_bias, self_serving_bias, authority_bias, confirmation_bias, curse_of_knowledge, in_group_bias | partial |
| pos_020 | political | in_field | confirmation_bias, availability_heuristic | escalation_of_commitment, confirmation_bias, base_rate_neglect, in_group_bias, authority_bias, negativity_bias, fundamental_attribution_error, survivorship_bias, affect_heuristic, halo_effect | partial |
| pos_021 | consumer | in_field | choice_supportive_bias, confirmation_bias | negativity_bias, base_rate_neglect, confirmation_bias, overconfidence_bias, availability_heuristic, framing_effect, choice_supportive_bias, zero_risk_bias, bandwagon_effect | hit |
| pos_022 | educational | in_field | status_quo_bias, overconfidence_bias | authority_bias, confirmation_bias, dunning_kruger_effect, self_serving_bias, stereotyping_bias, framing_effect, fundamental_attribution_error, halo_effect, recency_bias, loss_aversion | miss |
| pos_023 | family | in_field | status_quo_bias, projection_bias | curse_of_knowledge, confirmation_bias, availability_heuristic, negativity_bias, base_rate_neglect, hindsight_bias | miss |
| pos_024 | technical | in_field | availability_heuristic, overconfidence_bias | fundamental_attribution_error, confirmation_bias, recency_bias, authority_bias, base_rate_neglect, negativity_bias, hindsight_bias, self_serving_bias | miss |
