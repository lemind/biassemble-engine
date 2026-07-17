"""Unit tests for scripts/assemble_sft_dataset.py's coverage-checking logic.

Pure function over hand-built row lists — no live files, no DB, no network.
Mirrors the free/deterministic style of tests/test_check_regression.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.assemble_sft_dataset import (
    NEGATIVE_FRACTION_FLOOR,
    PER_BIAS_FLOOR,
    REQUIRED_GROUPS,
    SYNTHETIC_VOLUME_FLOOR,
    compute_coverage_report,
    compute_dataset_version,
)

# Small fixture catalog so tests don't depend on the real 38-id list.
FIXTURE_VALID_IDS = {"anchoring_bias", "sunk_cost_fallacy", "loss_aversion"}


def _synthetic_row(bias_ids, group="positive"):
    return {
        "story": f"story about {bias_ids} {group} {id(bias_ids)}",
        "bias_ids": bias_ids,
        "source": "synthetic",
        "spot_checked": False,
        "group": group,
        "generator_model": "test",
        "generation_prompt_version": "v1",
        "teacher_model": "test-teacher",
        "label_prompt_version": "v1",
    }


def _weak_row(bias_ids):
    return {
        "story": f"excerpt about {bias_ids} {id(bias_ids)}",
        "bias_ids": bias_ids,
        "source": "real_weak",
        "spot_checked": True,
        "group": None,
        "generator_model": None,
        "generation_prompt_version": None,
        "teacher_model": None,
        "label_prompt_version": None,
    }


def _make_passing_dataset():
    """Build a minimal fixture that clears every rule against FIXTURE_VALID_IDS
    (floor=15 per bias, volume=300 synthetic, negative>=20%) by directly
    constructing counts, not by looping SYNTHETIC_VOLUME_FLOOR times by hand."""
    synthetic = []
    groups = ["positive", "negative", "edge", "adversarial"]
    # 240 rows carrying all 3 fixture biases each -> 240 >= 15 per bias
    for i in range(240):
        synthetic.append(_synthetic_row(["anchoring_bias", "sunk_cost_fallacy", "loss_aversion"], groups[i % 4]))
    # 65 negative rows, not exactly 60 -- leaves headroom above the 20% floor
    # so an extra real_weak row (counted in the denominator) doesn't tip a
    # fixture meant to pass into failing by a fraction of a percent.
    for i in range(65):
        synthetic.append(_synthetic_row([], "negative"))
    return synthetic


def test_passes_when_every_rule_cleared():
    synthetic = _make_passing_dataset()
    weak = [_weak_row(["anchoring_bias"])]
    report = compute_coverage_report(weak, synthetic, FIXTURE_VALID_IDS)
    assert report["pass"] is True
    assert report["total_rows"] == len(synthetic) + len(weak)


def test_fails_on_per_bias_floor():
    synthetic = _make_passing_dataset()
    # Remove all but 5 occurrences of loss_aversion by rebuilding without it
    synthetic = [
        _synthetic_row(["anchoring_bias", "sunk_cost_fallacy"], r["group"]) if "loss_aversion" in r["bias_ids"] and synthetic.index(r) >= 5 else r
        for r in synthetic
    ]
    report = compute_coverage_report([], synthetic, FIXTURE_VALID_IDS)
    assert report["pass"] is False
    assert "loss_aversion" in report["_diagnostics"]["under_floor_biases"]


def test_fails_on_missing_group():
    synthetic = [_synthetic_row(["anchoring_bias"], "positive") for _ in range(SYNTHETIC_VOLUME_FLOOR)]
    report = compute_coverage_report([], synthetic, FIXTURE_VALID_IDS)
    assert report["pass"] is False
    assert set(report["_diagnostics"]["missing_groups"]) == REQUIRED_GROUPS - {"positive"}


def test_fails_on_negative_fraction_below_floor():
    synthetic = _make_passing_dataset()
    # Convert all negative rows to positive to drop negative_fraction to 0
    synthetic = [
        _synthetic_row(["anchoring_bias"], "positive") if r["group"] == "negative" else r
        for r in synthetic
    ]
    report = compute_coverage_report([], synthetic, FIXTURE_VALID_IDS)
    assert report["pass"] is False
    assert report["negative_fraction"] < NEGATIVE_FRACTION_FLOOR


def test_fails_on_synthetic_volume_below_floor():
    synthetic = [_synthetic_row(["anchoring_bias"], "positive") for _ in range(10)]
    report = compute_coverage_report([], synthetic, FIXTURE_VALID_IDS)
    assert report["pass"] is False
    assert report["_diagnostics"]["synthetic_volume"] == 10


def test_real_weak_rows_count_toward_per_bias_floor_but_not_volume_floor():
    # 300 synthetic rows with zero anchoring_bias, but 20 real_weak rows carry it —
    # per-bias floor should be satisfied by the combination, but synthetic volume
    # floor is unaffected by real_weak count (real_weak is additive, not counted).
    synthetic = _make_passing_dataset()
    synthetic = [_synthetic_row([b for b in r["bias_ids"] if b != "anchoring_bias"], r["group"]) for r in synthetic]
    weak = [_weak_row(["anchoring_bias"]) for _ in range(20)]
    report = compute_coverage_report(weak, synthetic, FIXTURE_VALID_IDS)
    assert report["counts_by_source"]["real_weak"] == 20
    assert report["_diagnostics"]["synthetic_volume"] == len(synthetic)


def test_real_weak_group_is_none_and_excluded_from_group_coverage():
    weak = [_weak_row(["anchoring_bias"])]
    report = compute_coverage_report(weak, [], FIXTURE_VALID_IDS)
    # real_weak rows have group=None and must not appear as a counted group
    assert None not in report["counts_by_group"]


def test_catalog_violation_detected():
    synthetic = [_synthetic_row(["not_a_real_id"], "positive")]
    report = compute_coverage_report([], synthetic, FIXTURE_VALID_IDS)
    assert report["pass"] is False
    assert len(report["_diagnostics"]["catalog_violations"]) == 1


def test_negative_row_has_empty_bias_ids_and_counts_toward_negative_fraction():
    synthetic = [_synthetic_row([], "negative"), _synthetic_row(["anchoring_bias"], "positive")]
    report = compute_coverage_report([], synthetic, FIXTURE_VALID_IDS)
    assert report["negative_fraction"] == 0.5


def test_dataset_version_is_deterministic_regardless_of_row_order():
    rows_a = [_weak_row(["anchoring_bias"]), _weak_row(["loss_aversion"])]
    rows_b = list(reversed(rows_a))
    assert compute_dataset_version(rows_a) == compute_dataset_version(rows_b)


def test_dataset_version_changes_when_content_changes():
    rows_a = [_weak_row(["anchoring_bias"])]
    rows_b = [_weak_row(["loss_aversion"])]
    assert compute_dataset_version(rows_a) != compute_dataset_version(rows_b)


def test_per_bias_floor_constant_matches_contract():
    # contracts/sft-dataset-schema.md rule 3: ~15 per bias
    assert PER_BIAS_FLOOR == 15


def test_synthetic_volume_floor_constant_matches_contract():
    # contracts/sft-dataset-schema.md rule 5: >=300 synthetic rows
    assert SYNTHETIC_VOLUME_FLOOR == 300
