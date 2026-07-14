# Phase 1 Data Model: CI Metrics Gate for Retrieval Quality

No database schema changes — this feature is entirely file/process boundary. The "entities" below are the JSON shapes that cross those boundaries, most of which already exist and are being *consumed*, not newly designed.

## GroupMetrics (existing — `src/evaluation/evaluate.py`)

Already produced by `run_evaluation.py` / the deployed `/evaluate` endpoint. `check_regression.py` reads this shape, does not define it:

| Field | Type | Notes |
|---|---|---|
| `group` | str | `"positive"` \| `"negative"` \| `"edge"` \| `"adversarial"` |
| `count` | int | scenario count for the group — the denominator in the ADR §4 tolerance formula |
| `recall_at_k` | float [0,1] | group average |
| `precision_at_k` | float [0,1] | group average |
| `mrr` | float [0,1] | not gated by this feature (informational only, per ADR scope) |
| `ndcg_at_k` | float [0,1] | not gated by this feature (informational only, per ADR scope) |
| `empty_rate` | float [0,1] | group average; the gated metric for `negative` specifically |

## Baseline (existing — `evaluations/baselines/baseline_*.json`)

Already written by `run_evaluation.py --promote`. Shape: `{"group_metrics": {<group>: GroupMetrics, ...}, ...}` (see `compute_deltas()` in `evaluate.py`, which already reads `baseline.get("group_metrics", {})`). `check_regression.py` reads the same file `load_baseline()` already resolves — it does not introduce a new baseline format or a new promotion path (FR-013).

## RegressionFinding (new — produced by `check_regression.py`, one per `(group, metric)` pair)

The only new data shape this feature introduces. Not persisted — printed as the script's output and used for its exit code. **One finding per gated metric, not per group**: `positive`/`edge`/`adversarial` each produce two findings (`recall_at_k` and `precision_at_k`, gated independently — ADR §4), `negative` produces one (`empty_rate`). Seven findings total against today's four groups, not four.

| Field | Type | Notes |
|---|---|---|
| `group` | str | scenario group name |
| `metric` | str | `"recall_at_k"` or `"precision_at_k"` (both produced, as separate findings, for positive/edge/adversarial) or `"empty_rate"` (for negative) — never a group choosing between recall/precision, both always apply (ADR §2/§4) |
| `baseline_value` | float | the promoted baseline's value for `metric` — recall and precision have *different* baseline values within the same group, so their `eligible`/`regressed` outcomes can differ even though they share the same `tolerance` (see `edge` below) |
| `current_value` | float | this run's value for `metric` |
| `delta` | float | `current_value - baseline_value`. Negative = worse, for every `(group, metric)` pair — `empty_rate` (the `negative` group's gated metric) is oriented the same "higher is better" way as `recall_at_k`/`precision_at_k`, so there is no sign flip to get wrong; only which `metric` differs |
| `tolerance` | float | `1 / count` for this group — shared by both metrics of the same group, since `count` doesn't vary by metric |
| `eligible` | bool | `tolerance < baseline_value` (ADR §4), computed **per `(group, metric)` pair** — `False` today for both of `adversarial`'s metrics *and* `edge`'s `precision_at_k` (baseline `0.400` vs. `tolerance 0.500`), even though `edge`'s `recall_at_k` (baseline `0.833`) is eligible. A group is not uniformly eligible or ineligible. |
| `regressed` | bool | `True` only when `eligible` is `True` **and** `delta < -tolerance` (strict, not `<=` — see the "one scenario = noise" worked example in ADR §4; one comparison direction for every `(group, metric)` pair, `empty_rate` included) |

**Overall gate result** = `any(finding.regressed for finding in findings)`. A finding for an *ineligible* `(group, metric)` pair (both of `adversarial`'s, `edge`'s `precision_at_k`) is reported (all findings are always printed) but does not fail the gate — this is the direct implementation of spec.md FR-006/FR-007.

## State / lifecycle notes

- **No new persisted state.** `RegressionFinding` is computed fresh on every Tier 2a/2b run from two already-existing JSON files; nothing about this feature needs a database row, a cache, or a new file written to the repo.
- **Baseline promotion remains entirely outside this feature's write path** (FR-013) — `check_regression.py` only ever reads `evaluations/baselines/`, never writes to it. This is a design boundary worth stating plainly in the data model, not just the requirements: there is no code path in this feature that can promote a baseline, by construction, not by convention.
