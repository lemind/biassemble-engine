import json
import pytest

from src.evaluation.evaluate import (
    K,
    GroupMetrics,
    ScenarioResult,
    _aggregate,
    compute_deltas,
    load_scenarios,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


# ── recall_at_k ───────────────────────────────────────────────────────────────

def test_recall_all_found():
    assert recall_at_k(["A", "B", "C"], ["A", "B", "C"]) == pytest.approx(1.0)


def test_recall_partial():
    assert recall_at_k(["A", "B"], ["A", "B", "C"]) == pytest.approx(2 / 3)


def test_recall_none_found():
    assert recall_at_k(["X", "Y"], ["A", "B"]) == pytest.approx(0.0)


def test_recall_empty_expected_retrieved_empty():
    # negative scenario: nothing expected, nothing retrieved → success
    assert recall_at_k([], []) == pytest.approx(1.0)


def test_recall_empty_expected_retrieved_not_empty():
    # negative scenario: nothing expected but something retrieved → failure
    assert recall_at_k(["A"], []) == pytest.approx(0.0)


# ── precision_at_k ────────────────────────────────────────────────────────────

def test_precision_perfect():
    assert precision_at_k(["A", "B"], ["A", "B", "C"]) == pytest.approx(1.0)


def test_precision_partial():
    assert precision_at_k(["A", "X", "Y"], ["A", "B"]) == pytest.approx(1 / 3)


def test_precision_retrieved_empty_expected_empty():
    assert precision_at_k([], []) == pytest.approx(1.0)


# ── mrr ───────────────────────────────────────────────────────────────────────

def test_mrr_first_hit_at_rank_1():
    assert mrr(["A", "B", "C"], ["A"]) == pytest.approx(1.0)


def test_mrr_first_hit_at_rank_3():
    assert mrr(["X", "Y", "A"], ["A"]) == pytest.approx(1 / 3)


def test_mrr_no_hit():
    assert mrr(["X", "Y"], ["A", "B"]) == pytest.approx(0.0)


def test_mrr_empty_expected():
    assert mrr([], []) == pytest.approx(1.0)


# ── ndcg_at_k ─────────────────────────────────────────────────────────────────

def test_ndcg_perfect():
    assert ndcg_at_k(["A", "B"], ["A", "B"]) == pytest.approx(1.0)


def test_ndcg_partial_order_matters():
    # A at rank 1 better than A at rank 2
    score_rank1 = ndcg_at_k(["A", "X"], ["A", "B"])
    score_rank2 = ndcg_at_k(["X", "A"], ["A", "B"])
    assert score_rank1 > score_rank2


def test_ndcg_no_hit():
    assert ndcg_at_k(["X", "Y"], ["A", "B"]) == pytest.approx(0.0)


def test_ndcg_empty_expected_empty_retrieved():
    assert ndcg_at_k([], []) == pytest.approx(1.0)


def test_ndcg_empty_expected_retrieved_not_empty():
    assert ndcg_at_k(["A"], []) == pytest.approx(0.0)


# ── load_scenarios ────────────────────────────────────────────────────────────

def test_load_scenarios_skips_capability_probes(tmp_path):
    (tmp_path / "positive").mkdir()
    (tmp_path / "capability_probes").mkdir()
    (tmp_path / "regression").mkdir()

    (tmp_path / "positive" / "s1.json").write_text(json.dumps({
        "scenario_id": "pos_001", "group": "positive",
        "story": "A story.", "story_analysis": None,
        "expected_bias_ids": ["confirmation_bias"],
    }))
    (tmp_path / "capability_probes" / "p1.json").write_text(json.dumps({
        "scenario_id": "probe_001", "group": "capability_probes",
        "story": "Satire.", "story_analysis": None,
        "expected_bias_ids": [],
    }))

    scenarios = load_scenarios(tmp_path)
    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "pos_001"


def test_load_scenarios_parses_fields(tmp_path):
    (tmp_path / "positive").mkdir()
    (tmp_path / "positive" / "s1.json").write_text(json.dumps({
        "scenario_id": "pos_001", "group": "positive",
        "story": "The story.", "story_analysis": None,
        "expected_bias_ids": ["A", "B"],
    }))
    scenarios = load_scenarios(tmp_path)
    s = scenarios[0]
    assert s.expected_bias_ids == ["A", "B"]
    assert s.story_analysis is None


# ── _aggregate ────────────────────────────────────────────────────────────────

def _make_result(group: str, expected: list[str], retrieved: list[str]) -> ScenarioResult:
    top_k = retrieved[:K]
    return ScenarioResult(
        scenario_id="test",
        group=group,
        expected=expected,
        retrieved=retrieved,
        recall_at_k=recall_at_k(top_k, expected),
        precision_at_k=precision_at_k(top_k, expected),
        mrr=mrr(retrieved, expected),
        ndcg_at_k=ndcg_at_k(top_k, expected),
    )


def test_aggregate_empty_rate():
    results = [
        _make_result("negative", [], []),         # empty → counts
        _make_result("negative", [], ["A"]),       # not empty → doesn't count
        _make_result("negative", [], []),
    ]
    gm = _aggregate(results)["negative"]
    assert gm.empty_rate == pytest.approx(2 / 3)


def test_aggregate_mean_recall():
    results = [
        _make_result("positive", ["A", "B"], ["A"]),       # recall = 0.5
        _make_result("positive", ["A", "B"], ["A", "B"]),  # recall = 1.0
    ]
    gm = _aggregate(results)["positive"]
    assert gm.recall_at_k == pytest.approx(0.75)


# ── compute_deltas ────────────────────────────────────────────────────────────

def test_compute_deltas_improvement():
    current = {"positive": GroupMetrics(
        group="positive", count=3,
        recall_at_k=0.9, precision_at_k=0.8, mrr=0.95, ndcg_at_k=0.85, empty_rate=0.0,
    )}
    baseline = {"group_metrics": {"positive": {
        "recall_at_k": 0.8, "precision_at_k": 0.7, "mrr": 0.9, "ndcg_at_k": 0.8, "empty_rate": 0.0,
    }}}
    deltas = compute_deltas(current, baseline)
    assert deltas["positive"]["recall_at_k"] == pytest.approx(0.1)


def test_compute_deltas_missing_group_skipped():
    current = {"positive": GroupMetrics(
        group="positive", count=1,
        recall_at_k=0.9, precision_at_k=0.8, mrr=0.9, ndcg_at_k=0.8, empty_rate=0.0,
    )}
    baseline = {"group_metrics": {}}  # no positive group in baseline
    deltas = compute_deltas(current, baseline)
    assert "positive" not in deltas
