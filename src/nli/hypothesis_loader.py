from pathlib import Path

import yaml

TAXONOMY_SIZE = 38


def load_hypotheses(path: str) -> list[tuple[str, str]]:
    """Load and validate bias hypotheses from a YAML file.

    Each entry must have a bias_id and either a single 'hypothesis' string or a
    'hypotheses' list of strings (multi-phrasing).  Multi-phrasing entries are
    flattened to one (bias_id, hypothesis) tuple per phrasing so the classifier
    can take the max entailment score across phrasings.

    Returns a list of (bias_id, hypothesis) tuples in file order.
    Raises ValueError at startup if the file is missing, malformed, or does not
    contain exactly 38 unique bias_ids.
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

    result: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {i} is not a mapping: {path}")
        bias_id = entry.get("bias_id")
        if not bias_id or not isinstance(bias_id, str):
            raise ValueError(f"Entry {i} missing or invalid 'bias_id': {path}")
        bias_id = bias_id.strip()

        # Support single 'hypothesis' string or 'hypotheses' list (multi-phrasing).
        single = entry.get("hypothesis")
        multi = entry.get("hypotheses")
        if single and multi:
            raise ValueError(f"Entry {i} ({bias_id}): use 'hypothesis' OR 'hypotheses', not both: {path}")
        if single:
            if not isinstance(single, str):
                raise ValueError(f"Entry {i} ({bias_id}) 'hypothesis' must be a string: {path}")
            phrasings = [single.strip()]
        elif multi:
            if not isinstance(multi, list) or not all(isinstance(h, str) for h in multi):
                raise ValueError(f"Entry {i} ({bias_id}) 'hypotheses' must be a list of strings: {path}")
            phrasings = [h.strip() for h in multi]
        else:
            raise ValueError(f"Entry {i} ({bias_id}) missing 'hypothesis' or 'hypotheses': {path}")

        seen_ids.add(bias_id)
        for phrasing in phrasings:
            result.append((bias_id, phrasing))

    if len(seen_ids) != TAXONOMY_SIZE:
        raise ValueError(
            f"Expected exactly {TAXONOMY_SIZE} unique bias_ids, got {len(seen_ids)}: {path}"
        )

    return result
