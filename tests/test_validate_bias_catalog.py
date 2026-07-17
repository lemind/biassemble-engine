"""Unit tests for scripts/validate_bias_catalog.py's row-validation logic.

Pure function over a fixture valid_ids set — no live DB call in the test itself,
mirroring the free/deterministic style of tests/test_check_regression.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.validate_bias_catalog import validate_row

FIXTURE_VALID_IDS = {"anchoring_bias", "sunk_cost_fallacy", "loss_aversion"}


def test_all_valid_ids_pass():
    assert validate_row(["anchoring_bias", "loss_aversion"], FIXTURE_VALID_IDS) is True


def test_out_of_catalog_id_rejects_whole_row():
    # Not coerced, not silently dropped while keeping the valid entry — the whole
    # row is invalid (spec.md FR-005 / contracts/sft-dataset-schema.md rule 1).
    assert validate_row(["anchoring_bias", "not_a_real_id"], FIXTURE_VALID_IDS) is False


def test_human_readable_name_instead_of_id_rejected():
    assert validate_row(["Anchoring Bias"], FIXTURE_VALID_IDS) is False


def test_empty_bias_ids_is_valid():
    # Negative examples carry no bias_ids.
    assert validate_row([], FIXTURE_VALID_IDS) is True


def test_single_invalid_id_rejects():
    assert validate_row(["not_a_real_id"], FIXTURE_VALID_IDS) is False
