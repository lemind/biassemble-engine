from src.llm.prompt import BiasCandidate, parse_biases

VALID_IDS = {"confirmation_bias", "sunk_cost_fallacy", "overconfidence_bias"}


def test_parse_biases_valid_json():
    raw = '["confirmation_bias"]'
    result = parse_biases(raw, VALID_IDS)
    assert result == [BiasCandidate(bias_id="confirmation_bias", confidence=0.5)]


def test_parse_biases_drops_non_catalog_ids():
    raw = '["not_a_real_bias"]'
    assert parse_biases(raw, VALID_IDS) == []


def test_parse_biases_empty_array_is_valid():
    assert parse_biases("[]", VALID_IDS) == []


def test_parse_biases_repairs_prose_around_json():
    raw = (
        'Sure, here is the analysis:\n'
        '["sunk_cost_fallacy"]\n'
        'Hope that helps!'
    )
    result = parse_biases(raw, VALID_IDS)
    assert [c.bias_id for c in result] == ["sunk_cost_fallacy"]


def test_parse_biases_garbage_returns_empty_without_raising():
    assert parse_biases("not json at all { broken", VALID_IDS) == []


def test_parse_biases_multiple_ids():
    raw = '["confirmation_bias", "sunk_cost_fallacy"]'
    result = parse_biases(raw, VALID_IDS)
    assert [c.bias_id for c in result] == ["confirmation_bias", "sunk_cost_fallacy"]
    assert all(c.confidence == 0.5 for c in result)


def test_parse_biases_non_string_items_dropped():
    raw = '[42, null, "confirmation_bias", {"bias_id": "sunk_cost_fallacy"}]'
    result = parse_biases(raw, VALID_IDS)
    assert [c.bias_id for c in result] == ["confirmation_bias"]


def test_parse_biases_trailing_bracket_text_does_not_swallow_valid_json():
    # A naive greedy `\[.*\]` regex matches from the first '[' to the LAST ']' in
    # the whole response, including this trailing commentary — producing invalid
    # JSON ("Extra data") and silently dropping the valid, well-formed array.
    raw = (
        '["confirmation_bias"]\n'
        'Note: consider [context] when reviewing this further.'
    )
    result = parse_biases(raw, VALID_IDS)
    assert [c.bias_id for c in result] == ["confirmation_bias"]


def test_parse_biases_bracket_inside_string_value_does_not_break_extraction():
    raw = '["confirmation_bias", "see [1] sunk_cost_fallacy"]'
    result = parse_biases(raw, VALID_IDS)
    # second entry isn't a valid catalog id (it's a stray string containing a
    # bracket), so it's dropped by _validate_catalog — but extraction must not
    # choke on the embedded bracket while scanning for the array's true end.
    assert [c.bias_id for c in result] == ["confirmation_bias"]
