#!/usr/bin/env python
"""Reconstruct real story text for the blind-spot batch and promote it into a
real, held-out evaluation group.

evaluations/staging/blind_spot_eval_2026-07-13.json is an eval-RESULTS file
(scenario_id/domain/expected_bias_ids/retrieved_bias_ids/verdict) — it has no
"story" field at all. The actual story text for all 80 scenarios only exists in
8 raw DeepSeek export files on local disk (not in this repo), joinable back to
the results file by (group, domain) in list order per source_file batch
(verified directly during planning — see specs/006-fine-tune-llm/research.md).

Output: one evaluations/blind_spot/<scenario_id>.json per row, matching the
existing scenario-file shape exactly (evaluations/positive/*.json's convention)
so src/evaluation/evaluate.py's loader needs no changes.

CRITICAL: every output file's "group" field is the literal string "blind_spot",
NOT the batch's original per-story label — src/evaluation/evaluate.py's
load_scenarios reads `group` from each file's own JSON key (not the directory
name) and aggregates on that same field. Reusing the original labels would
silently merge these 80 scenarios into the *existing* four groups' metrics
instead of creating a separately-scored group (data-model.md's load-bearing
correction).

Usage:
    uv run python scripts/reconstruct_blind_spot_stories.py \
        --results evaluations/staging/blind_spot_eval_2026-07-13.json \
        --raw-dir ~/Downloads \
        --output-dir evaluations/blind_spot/
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_RAW_FILENAME_RE = re.compile(r"^deepseek_json_20260713_(.+)\.json$")


def _normalize_key(raw_stem: str) -> str:
    """'bb12d7 (1)' -> 'bb12d7(1)' — matches the results file's compact
    source_file values (no space before the parenthesis). Normalizing this way
    means the truncated duplicate 'deepseek_json_20260713_bb12d7.json' (no
    "(1)") never matches any results row's source_file ('bb12d7(1)' only) —
    it's naturally excluded without special-casing."""
    return raw_stem.replace(" ", "")


def _load_raw_batches(raw_dir: Path) -> dict[str, list[dict]]:
    """Skip files that fail to parse rather than crashing the whole load — the
    known truncated duplicate (deepseek_json_20260713_bb12d7.json, no "(1)") is
    genuinely malformed JSON (cut off mid-story) and is never referenced by any
    results row's source_file ("bb12d7(1)" only) anyway, per
    _normalize_key's docstring. A missing REQUIRED key still fails loudly via
    reconstruct()'s own check below — this only tolerates unused, broken extras."""
    batches: dict[str, list[dict]] = {}
    for path in sorted(raw_dir.glob("deepseek_json_20260713_*.json")):
        m = _RAW_FILENAME_RE.match(path.name)
        if not m:
            continue
        key = _normalize_key(m.group(1))
        try:
            batches[key] = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"WARNING: skipping unparseable raw file {path.name}: {exc}", file=sys.stderr)
    return batches


def reconstruct(
    results_path: Path, raw_dir: Path, output_dir: Path
) -> tuple[list[dict], dict[str, list[str]]]:
    results = json.loads(results_path.read_text())
    raw_batches = _load_raw_batches(raw_dir)

    required_keys = {"6a25e8", "7da4ba", "7e1b94", "8c4f45", "99e66a", "ace574", "bb12d7(1)", "c5c14a"}
    missing = required_keys - set(raw_batches.keys())
    if missing:
        print(f"ERROR: missing raw source file(s) for key(s): {sorted(missing)}", file=sys.stderr)
        print(f"Expected under {raw_dir}, matching deepseek_json_20260713_<key>.json", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    per_source_index: dict[str, int] = defaultdict(int)
    written = []
    dropped_labels: dict[str, list[str]] = {}

    for row in results:
        source_file = row["source_file"]
        idx = per_source_index[source_file]
        per_source_index[source_file] += 1

        raw_batch = raw_batches.get(source_file)
        if raw_batch is None:
            print(f"ERROR: {row['scenario_id']} references unknown source_file {source_file!r}", file=sys.stderr)
            sys.exit(1)
        if idx >= len(raw_batch):
            print(f"ERROR: {row['scenario_id']} index {idx} out of range for source_file {source_file!r} ({len(raw_batch)} rows)", file=sys.stderr)
            sys.exit(1)

        raw = raw_batch[idx]
        if raw.get("group") != row["group"] or raw.get("domain") != row["domain"]:
            print(
                f"ERROR: join misalignment for {row['scenario_id']}: "
                f"results=({row['group']!r},{row['domain']!r}) vs raw[{idx}]=({raw.get('group')!r},{raw.get('domain')!r})",
                file=sys.stderr,
            )
            sys.exit(1)

        invalid_ids = row.get("invalid_expected_ids", [])
        expected_bias_ids = [b for b in row["expected_bias_ids"] if b not in invalid_ids]
        if invalid_ids:
            dropped_labels[row["scenario_id"]] = invalid_ids

        scenario = {
            "scenario_id": row["scenario_id"],
            "group": "blind_spot",
            "original_subgroup": row["group"],
            "story": raw["story"],
            "story_analysis": None,
            "expected_bias_ids": expected_bias_ids,
            "domain": row["domain"],
            "domain_familiarity": row["domain_familiarity"],
        }

        out_path = output_dir / f"{row['scenario_id']}.json"
        out_path.write_text(json.dumps(scenario, indent=2) + "\n")
        written.append(scenario)

    return written, dropped_labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    raw_dir = args.raw_dir.expanduser()
    written, dropped_labels = reconstruct(args.results, raw_dir, args.output_dir)

    print(f"Wrote {len(written)} scenarios to {args.output_dir}")
    if dropped_labels:
        print("Dropped invalid label(s) (row kept, only the bad id removed):")
        for scenario_id, ids in dropped_labels.items():
            print(f"  {scenario_id}: {ids}")


if __name__ == "__main__":
    main()
