"""Unit tests for scripts/check_regression.py's tolerance/eligibility/regression logic.

Pure functions over hand-built GroupMetrics-shaped dicts — no eval infrastructure,
no network, no DB. Mirrors the free/deterministic style of tests/test_evaluate.py.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.check_regression import compute_finding, compute_findings, metrics_for_group

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_regression.py"


# ── (a) normal case — positive, N=4, baseline recall_at_k=0.875 ──────────────

def test_one_scenario_loss_passes_as_noise():
    baseline_gm = {"count": 4, "recall_at_k": 0.875, "precision_at_k": 0.5875}
    current_gm = {"count": 4, "recall_at_k": 0.625, "precision_at_k": 0.5875}  # Δ=-0.25, exactly -tolerance
    f = compute_finding("positive", "recall_at_k", baseline_gm, current_gm)
    assert f.eligible is True
    assert f.regressed is False  # strict <, not <=


def test_two_scenario_loss_fails():
    baseline_gm = {"count": 4, "recall_at_k": 0.875, "precision_at_k": 0.5875}
    current_gm = {"count": 4, "recall_at_k": 0.375, "precision_at_k": 0.5875}  # Δ=-0.50
    f = compute_finding("positive", "recall_at_k", baseline_gm, current_gm)
    assert f.eligible is True
    assert f.regressed is True


# ── (b) negative group gates on empty_rate, same direction as recall/precision ─

def test_negative_empty_rate_one_story_leak_passes_as_noise():
    baseline_gm = {"count": 5, "empty_rate": 1.0}
    current_gm = {"count": 5, "empty_rate": 0.8}  # Δ=-0.20, exactly -tolerance (1/5)
    f = compute_finding("negative", "empty_rate", baseline_gm, current_gm)
    assert f.eligible is True
    assert f.regressed is False


def test_negative_empty_rate_two_story_leak_fails():
    baseline_gm = {"count": 5, "empty_rate": 1.0}
    current_gm = {"count": 5, "empty_rate": 0.6}  # Δ=-0.40
    f = compute_finding("negative", "empty_rate", baseline_gm, current_gm)
    assert f.eligible is True
    assert f.regressed is True


def test_negative_gates_only_empty_rate():
    assert metrics_for_group("negative") == ["empty_rate"]


def test_non_negative_groups_gate_recall_and_precision_independently():
    for group in ("positive", "edge", "adversarial"):
        assert metrics_for_group(group) == ["recall_at_k", "precision_at_k"]


# ── (c) adversarial-shaped input never regresses, regardless of group name ───

def test_adversarial_real_shape_never_regresses_even_at_total_loss():
    baseline_gm = {"count": 2, "recall_at_k": 0.3333333333333333, "precision_at_k": 0.26666666666666666}
    current_gm = {"count": 2, "recall_at_k": 0.0, "precision_at_k": 0.0}  # total loss of signal
    for metric in ("recall_at_k", "precision_at_k"):
        f = compute_finding("adversarial", metric, baseline_gm, current_gm)
        assert f.eligible is False
        assert f.regressed is False  # ineligible, so never regressed no matter how far it drops


def test_ineligibility_is_computed_from_shape_not_hardcoded_to_adversarial_name():
    """Same 1/count >= baseline_value shape, different group name — must be
    ineligible too, proving the rule isn't a hardcoded 'adversarial' exception."""
    baseline_gm = {"count": 2, "recall_at_k": 0.3, "precision_at_k": 0.3}
    current_gm = {"count": 2, "recall_at_k": 0.0, "precision_at_k": 0.0}
    for metric in ("recall_at_k", "precision_at_k"):
        f = compute_finding("some_other_small_group", metric, baseline_gm, current_gm)
        assert f.eligible is False
        assert f.regressed is False


# ── (d) missing/malformed input files → exit 2, not 1 or a traceback ─────────

def test_missing_run_file_exits_2(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"group_metrics": {}}))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--run", str(tmp_path / "does_not_exist.json"), "--baseline", str(baseline)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2


def test_malformed_baseline_file_exits_2(tmp_path):
    run = tmp_path / "run.json"
    run.write_text(json.dumps({"group_metrics": {}}))
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{not valid json")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--run", str(run), "--baseline", str(baseline)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2


def test_baseline_missing_group_metrics_key_exits_2(tmp_path):
    run = tmp_path / "run.json"
    run.write_text(json.dumps({"group_metrics": {}}))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"some_other_key": {}}))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--run", str(run), "--baseline", str(baseline)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2


def test_no_regression_exits_0(tmp_path):
    gm = {"positive": {"count": 4, "recall_at_k": 0.875, "precision_at_k": 0.5875}}
    run = tmp_path / "run.json"
    run.write_text(json.dumps({"group_metrics": gm}))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"group_metrics": gm}))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--run", str(run), "--baseline", str(baseline)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


# ── (e) per-metric eligibility split — the real `edge` shape ──────────────────

def test_per_metric_eligibility_split_edge_shape():
    """edge's real baseline (evaluations/baselines/baseline_2026-07-09.json):
    recall_at_k=0.833 (eligible, tolerance=0.5) but precision_at_k=0.400
    (ineligible, same tolerance=0.5) — eligibility is per (group, metric),
    not inherited from the group as a whole."""
    baseline_gm = {"count": 2, "recall_at_k": 0.8333333333333334, "precision_at_k": 0.4}
    current_gm = {"count": 2, "recall_at_k": 0.8333333333333334, "precision_at_k": 0.4}

    recall_finding = compute_finding("edge", "recall_at_k", baseline_gm, current_gm)
    precision_finding = compute_finding("edge", "precision_at_k", baseline_gm, current_gm)

    assert recall_finding.tolerance == pytest.approx(precision_finding.tolerance)  # same count → same tolerance
    assert recall_finding.eligible is True
    assert precision_finding.eligible is False


def test_compute_findings_produces_two_rows_for_non_negative_one_for_negative():
    baseline_gm = {
        "positive": {"count": 4, "recall_at_k": 0.875, "precision_at_k": 0.5875},
        "negative": {"count": 5, "empty_rate": 1.0},
    }
    run_gm = baseline_gm  # no-op comparison
    findings = compute_findings(run_gm, baseline_gm)
    positive_findings = [f for f in findings if f.group == "positive"]
    negative_findings = [f for f in findings if f.group == "negative"]
    assert {f.metric for f in positive_findings} == {"recall_at_k", "precision_at_k"}
    assert {f.metric for f in negative_findings} == {"empty_rate"}


def test_compute_findings_skips_group_missing_from_run():
    baseline_gm = {"positive": {"count": 4, "recall_at_k": 0.875, "precision_at_k": 0.5875}}
    run_gm: dict = {}  # PR run didn't include this group (e.g. --groups filter)
    findings = compute_findings(run_gm, baseline_gm)
    assert findings == []
