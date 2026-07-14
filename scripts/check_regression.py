#!/usr/bin/env python
"""Compare an evaluation run against a promoted baseline; exit non-zero on regression.

Pure-stdlib, no ML/network dependencies — reads two already-produced JSON files
(the shapes `src/evaluation/evaluate.py`'s `GroupMetrics`/`compute_deltas` already
produce) and applies the regression rule from adr/004-ci-metrics-gate.md §4.

Usage:
    python scripts/check_regression.py --run evaluations/runs/run_2026-07-14.json \
                                        --baseline evaluations/baselines/baseline_2026-07-09.json

Exit codes:
    0  no eligible (group, metric) pair regressed past tolerance
    1  at least one eligible (group, metric) pair regressed
    2  usage/input error — missing, unreadable, or malformed --run/--baseline file
"""

import argparse
import json
import sys
from dataclasses import dataclass

# ── Regression rule (adr/004-ci-metrics-gate.md §4) ────────────────────────────

def metrics_for_group(group: str) -> list[str]:
    """Which metrics are gated for a given scenario group.

    `negative` gates on empty_rate (recall_at_k/precision_at_k are a renamed
    copy of the same 0/1-per-story indicator for that group — ADR §2). Every
    other group gates recall_at_k AND precision_at_k independently, not as a
    pair that both have to fail.
    """
    if group == "negative":
        return ["empty_rate"]
    return ["recall_at_k", "precision_at_k"]


@dataclass
class RegressionFinding:
    group: str
    metric: str
    baseline_value: float
    current_value: float
    delta: float
    tolerance: float
    eligible: bool
    regressed: bool


def compute_finding(group: str, metric: str, baseline_gm: dict, current_gm: dict) -> RegressionFinding:
    count = baseline_gm["count"]
    baseline_value = baseline_gm[metric]
    current_value = current_gm[metric]
    delta = current_value - baseline_value
    tolerance = 1.0 / count if count else 0.0
    # Eligibility is per (group, metric), not per group — recall_at_k and
    # precision_at_k share a tolerance but have different baseline values and
    # can land on opposite sides of this check (e.g. edge's precision_at_k).
    eligible = tolerance < baseline_value
    regressed = eligible and delta < -tolerance
    return RegressionFinding(
        group=group, metric=metric,
        baseline_value=baseline_value, current_value=current_value,
        delta=delta, tolerance=tolerance, eligible=eligible, regressed=regressed,
    )


class MissingGroupsError(Exception):
    """Raised when the run is missing one or more groups the baseline has.

    Silently skipping these (as an earlier version did) means a run that lost
    an entire group — e.g. a load_scenarios path mismatch, the exact class of
    bug this feature's own staging-skip fix was — reports zero findings for
    it and the gate exits 0, indistinguishable from a clean pass. That must be
    an error (exit 2), not a silent skip.
    """


def compute_findings(run_group_metrics: dict, baseline_group_metrics: dict) -> list[RegressionFinding]:
    """One finding per (group, metric) pair, iterating over the baseline's own
    groups (the agreed-good reference)."""
    missing = set(baseline_group_metrics) - set(run_group_metrics)
    if missing:
        raise MissingGroupsError(f"run is missing group(s) present in baseline: {sorted(missing)}")

    findings: list[RegressionFinding] = []
    for group, baseline_gm in baseline_group_metrics.items():
        current_gm = run_group_metrics[group]
        for metric in metrics_for_group(group):
            findings.append(compute_finding(group, metric, baseline_gm, current_gm))
    return findings


# ── I/O ──────────────────────────────────────────────────────────────────────

def _load_json(path: str, label: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not read {label} file {path!r}: {exc}", file=sys.stderr)
        sys.exit(2)


def _extract_group_metrics(data, label: str) -> dict:
    # data is whatever json.load() returned — could be a list, str, int, etc.,
    # not necessarily a dict. Check before calling .get(), which only exists on
    # dict — a non-dict root used to raise an uncaught AttributeError here,
    # exiting 1 (Python's default) and getting misread as "regression found"
    # instead of "could not evaluate".
    gm = data.get("group_metrics") if isinstance(data, dict) else None
    if not isinstance(gm, dict):
        print(f"error: {label} file has no 'group_metrics' object", file=sys.stderr)
        sys.exit(2)
    return gm


def _result_label(f: RegressionFinding) -> str:
    if not f.eligible:
        return "reported only (ineligible)"
    if f.regressed:
        return "REGRESSED"
    if f.delta < 0:
        return "pass (within noise)"
    return "pass"


def print_report(findings: list[RegressionFinding]) -> None:
    col = "{:<14} {:<15} {:>9} {:>9} {:>9} {:>10} {:>9}  {}"
    print(col.format("GROUP", "METRIC", "BASELINE", "CURRENT", "DELTA", "TOLERANCE", "ELIGIBLE", "RESULT"))
    for f in findings:
        print(col.format(
            f.group, f.metric,
            f"{f.baseline_value:.3f}", f"{f.current_value:.3f}",
            f"{f.delta:+.3f}", f"{f.tolerance:.3f}",
            "yes" if f.eligible else "no",
            _result_label(f),
        ))


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="Path to an EvalRun-shaped JSON file")
    parser.add_argument("--baseline", required=True, help="Path to a baseline_*.json file")
    args = parser.parse_args()

    run_data = _load_json(args.run, "run")
    baseline_data = _load_json(args.baseline, "baseline")
    run_gm = _extract_group_metrics(run_data, "run")
    baseline_gm = _extract_group_metrics(baseline_data, "baseline")

    try:
        findings = compute_findings(run_gm, baseline_gm)
    except (KeyError, TypeError, ZeroDivisionError, AttributeError, MissingGroupsError) as exc:
        print(f"error: malformed group_metrics entry: {exc}", file=sys.stderr)
        sys.exit(2)

    print_report(findings)

    if any(f.regressed for f in findings):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
