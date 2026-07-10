from src.llm.prompt import BiasCandidate, parse_biases

VALID_IDS = {"confirmation_bias", "sunk_cost_fallacy", "overconfidence_bias"}


def test_parse_biases_valid_json():
    raw = '[{"bias_id": "confirmation_bias", "confidence": 0.9, "evidence": "quote"}]'
    result = parse_biases(raw, VALID_IDS)
    assert result == [BiasCandidate(bias_id="confirmation_bias", confidence=0.9, evidence="quote")]


def test_parse_biases_drops_non_catalog_ids():
    raw = '[{"bias_id": "not_a_real_bias", "confidence": 0.8, "evidence": "x"}]'
    assert parse_biases(raw, VALID_IDS) == []


def test_parse_biases_empty_array_is_valid():
    assert parse_biases("[]", VALID_IDS) == []


def test_parse_biases_repairs_prose_around_json():
    raw = (
        'Sure, here is the analysis:\n'
        '[{"bias_id": "sunk_cost_fallacy", "confidence": 0.7, "evidence": "e"}]\n'
        'Hope that helps!'
    )
    result = parse_biases(raw, VALID_IDS)
    assert [c.bias_id for c in result] == ["sunk_cost_fallacy"]


def test_parse_biases_garbage_returns_empty_without_raising():
    assert parse_biases("not json at all { broken", VALID_IDS) == []


def test_parse_biases_missing_confidence_defaults():
    raw = '[{"bias_id": "overconfidence_bias", "evidence": "e"}]'
    result = parse_biases(raw, VALID_IDS)
    assert result[0].confidence == 0.5


def test_parse_biases_non_dict_items_are_dropped():
    raw = (
        '["confirmation_bias", '
        '{"bias_id": "sunk_cost_fallacy", "confidence": 0.6, "evidence": "e"}]'
    )
    result = parse_biases(raw, VALID_IDS)
    assert [c.bias_id for c in result] == ["sunk_cost_fallacy"]


def test_parse_biases_trailing_bracket_text_does_not_swallow_valid_json():
    # A naive greedy `\[.*\]` regex matches from the first '[' to the LAST ']' in
    # the whole response, including this trailing commentary — producing invalid
    # JSON ("Extra data") and silently dropping the valid, well-formed array.
    raw = (
        '[{"bias_id": "confirmation_bias", "confidence": 0.9, "evidence": "quote"}]\n'
        'Note: consider [context] when reviewing this further.'
    )
    result = parse_biases(raw, VALID_IDS)
    assert [c.bias_id for c in result] == ["confirmation_bias"]


def test_parse_biases_bracket_inside_string_value_does_not_break_extraction():
    raw = '[{"bias_id": "confirmation_bias", "confidence": 0.9, "evidence": "see [1]"}]'
    result = parse_biases(raw, VALID_IDS)
    assert result == [
        BiasCandidate(bias_id="confirmation_bias", confidence=0.9, evidence="see [1]")
    ]
