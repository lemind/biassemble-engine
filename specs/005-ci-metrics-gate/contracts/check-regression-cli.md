# Contract: `scripts/check_regression.py` CLI

**Version**: v1 | **Dependencies**: Python stdlib only (no torch/asyncpg/etc.)

---

## Invocation

```
python scripts/check_regression.py --run <run.json> --baseline <baseline.json>
```

| Flag | Required | Meaning |
|---|---|---|
| `--run` | yes | Path to an `EvalRun`-shaped JSON file (what `run_evaluation.py` writes to `evaluations/runs/run_<date>.json`, or what `GET /evaluate/{job_id}` returns once `status == "done"`) |
| `--baseline` | yes | Path to a `baseline_*.json` file — same shape `load_baseline()` in `evaluate.py` already reads |

No network access, no database access, no model loading. Reads two local files, prints a report, exits.

---

## Output (stdout)

Human-readable table, **one row per (group, metric) pair** — `recall_at_k` and `precision_at_k` are gated independently for `positive`/`edge`/`adversarial` (two rows each), `empty_rate` alone for `negative` (one row), so seven rows total against today's four scenario groups. Real numbers below are pulled directly from `evaluations/baselines/baseline_2026-07-09.json` (the latest promoted baseline as of this writing), shown as a no-op comparison (run == baseline) except where noted:

```
GROUP          METRIC          BASELINE   CURRENT    DELTA     TOLERANCE  ELIGIBLE  RESULT
positive       recall_at_k     0.875      0.875      +0.000    0.250      yes       pass
positive       precision_at_k  0.588      0.588      +0.000    0.250      yes       pass
negative       empty_rate      1.000      0.800      -0.200    0.200      yes       pass (within noise)
edge           recall_at_k     0.833      0.833      +0.000    0.500      yes       pass
edge           precision_at_k  0.400      0.400      +0.000    0.500      no        reported only (ineligible)
adversarial    recall_at_k     0.333      0.000      -0.333    0.500      no        reported only (ineligible)
adversarial    precision_at_k  0.267      0.267      +0.000    0.500      no        reported only (ineligible)
```

Note `edge`/`precision_at_k`: same group as the eligible `edge`/`recall_at_k` row directly above it, same `tolerance=0.500` (it only depends on `count`), but **ineligible** — its own baseline (`0.400`) is below tolerance, so a single-story swing in precision can't be told apart from precision's signal being gone entirely (ADR §4's per-metric eligibility split, worked out with this exact group as the example). Eligibility is never a per-group blanket — `edge` is simultaneously blocking on recall and reported-only on precision.

Every `(group, metric)` pair is always printed (spec.md FR-007) — including ineligible and passing ones — so nothing is hidden from whoever reads the CI log.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | No eligible `(group, metric)` pair regressed past tolerance. (An ineligible pair may still show a regression in the table — that's expected, not an error; see the `adversarial` rows above.) |
| `1` | At least one eligible `(group, metric)` pair dropped past its tolerance (`delta < -tolerance`, strict — ADR §4). Same comparison for every pair; only which metric applies (`recall_at_k` **and** `precision_at_k`, checked independently, vs. `empty_rate` for `negative`) changes. |
| `2` | Usage/input error — a required file is missing, unreadable, or not valid JSON in the expected shape. Distinct from `1` so CI logs can tell "the gate caught a regression" apart from "the gate itself is broken," per spec.md's edge case about not conflating "could not evaluate" with "evaluated and found a problem." |

Callers (both `retrieval-gate.yml` and `production-drift.yml`) treat only exit code `1` as "block/flag a regression" — exit `2` should be treated as an infrastructure failure of the workflow itself (e.g. surfaced as a failed step with a distinct message), not silently reported as a quality finding.

---

## Non-goals

- Does not run the evaluation itself (that's `run_evaluation.py` / the deployed `/evaluate` endpoint's job).
- Does not write or promote a baseline (FR-013) — read-only with respect to `evaluations/baselines/`.
- Does not know or care whether it's being invoked for a PR (Tier 2a) or a scheduled drift check (Tier 2b) — that distinction is entirely the calling workflow's responsibility (what it does with exit code `1`: block a merge, or just fail its own run visibly).
