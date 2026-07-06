from pathlib import Path

import yaml

TAXONOMY_SIZE = 38


def load_hypotheses(path: str) -> list[tuple[str, str]]:
    """Load and validate bias hypotheses from a YAML file.

    Returns a list of (bias_id, hypothesis) tuples in file order.
    Raises ValueError at startup if the file is missing, malformed, or does not
    contain exactly 38 entries with valid bias_id and hypothesis fields.
    """
    p = Path(path)
    if not p.exists():
        raise ValueError(f"Hypotheses file not found: {path}")

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Hypotheses YAML parse error in {path}: {exc}") from exc

    if not isinstance(data, dict) or "hypotheses" not in data:
        raise ValueError(f"Hypotheses file must have a top-level 'hypotheses' key: {path}")

    entries = data["hypotheses"]
    if not isinstance(entries, list):
        raise ValueError(f"'hypotheses' must be a list: {path}")
    if len(entries) != TAXONOMY_SIZE:
        raise ValueError(f"Expected exactly {TAXONOMY_SIZE} hypotheses, got {len(entries)}: {path}")

    result: list[tuple[str, str]] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {i} is not a mapping: {path}")
        bias_id = entry.get("bias_id")
        hypothesis = entry.get("hypothesis")
        if not bias_id or not isinstance(bias_id, str):
            raise ValueError(f"Entry {i} missing or invalid 'bias_id': {path}")
        if not hypothesis or not isinstance(hypothesis, str):
            raise ValueError(f"Entry {i} missing or invalid 'hypothesis': {path}")
        result.append((bias_id.strip(), hypothesis.strip()))

    seen = [bid for bid, _ in result]
    if len(seen) != len(set(seen)):
        dupes = [bid for bid in set(seen) if seen.count(bid) > 1]
        raise ValueError(f"Duplicate bias_ids in {path}: {dupes}")

    return result
