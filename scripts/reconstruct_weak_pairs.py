#!/usr/bin/env python
"""Reconstruct real weak-supervision pairs from biassemble-core's production data.

Joins core.reasoning_traces.trace -> bias_hypotheses[].supporting_excerpts (real
story fragments) to core.retrieval_comparisons.final_list (assessment-confirmed
labels) via run_id — ADR-005 §1a. Output tagged source:"real_weak", never
"real": these are quoted fragments, not complete stories (data-model.md's
WeakSupervisionPair).

Same Supabase project as biassemble-engine's own DATABASE_URL (same pooler
host/project ref, verified this session) — no separate credential needed.
Queries MUST be schema-qualified (core.reasoning_traces, core.retrieval_
comparisons), not bare table names — these tables live in that project's
`core` schema, not `public` (Supabase's default search_path).

Two real data-quality issues found and handled here, neither documented before
this script was written:
  1. Some supporting_excerpts are junk placeholders ("A: no info", empty, or
     otherwise too short to be real story content) — filtered out.
  2. core.retrieval_comparisons.final_list stores human-readable Title Case
     names ("Negativity Bias"), not catalog bias_ids ("negativity_bias") —
     normalized (lowercase, non-alphanumeric -> underscore). Any id that still
     doesn't match the live catalog after normalization is DROPPED from that
     row (not the whole row, not coerced to a guessed mapping) — e.g.
     "Cherry-Picking" has no catalog equivalent and "Overconfidence Effect"
     is plausibly overconfidence_bias but that's an interpretive leap this
     script does not make automatically.

Usage:
    uv run python scripts/reconstruct_weak_pairs.py --output evaluations/sft/weak_supervision_pairs.jsonl
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import asyncpg

from scripts.validate_bias_catalog import _load_valid_bias_ids_once
from src.config import settings

_MIN_EXCERPT_LEN = 10
_JUNK_EXCERPTS = {"a: no info", "no info", "n/a", ""}


def _is_junk_excerpt(excerpt: str) -> bool:
    text = excerpt.strip()
    return text.lower() in _JUNK_EXCERPTS or len(text) < _MIN_EXCERPT_LEN


def _normalize_bias_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


_JOIN_QUERY = """
    SELECT rt.run_id, rt.trace, rc.final_list
    FROM core.reasoning_traces rt
    JOIN core.retrieval_comparisons rc ON rc.run_id = rt.run_id
    WHERE rc.final_list IS NOT NULL AND jsonb_array_length(rc.final_list) > 0
"""


async def _fetch_joined_rows() -> list[dict]:
    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        return [dict(r) for r in await conn.fetch(_JOIN_QUERY)]
    finally:
        await conn.close()


def build_pairs(rows: list[dict], valid_ids: set[str]) -> tuple[list[dict], dict[str, list[str]]]:
    pairs = []
    dropped_names: dict[str, list[str]] = {}

    for row in rows:
        trace = json.loads(row["trace"]) if isinstance(row["trace"], str) else row["trace"]
        excerpts = []
        for hyp in trace.get("bias_hypotheses", []):
            for e in hyp.get("supporting_excerpts", []):
                if not _is_junk_excerpt(e):
                    excerpts.append(e.strip())
        if not excerpts:
            continue

        raw_names = json.loads(row["final_list"]) if isinstance(row["final_list"], str) else row["final_list"]
        bias_ids = []
        bad = []
        for name in raw_names:
            norm = _normalize_bias_name(name)
            if norm in valid_ids:
                bias_ids.append(norm)
            else:
                bad.append(name)
        if bad:
            dropped_names[str(row["run_id"])] = bad

        pairs.append(
            {
                "run_id": str(row["run_id"]),
                "story_excerpts": excerpts,
                "bias_ids": bias_ids,
                "source": "real_weak",
            }
        )

    return pairs, dropped_names


async def _main_async(output_path: Path) -> None:
    print("Loading live bias catalog ...")
    valid_ids = await _load_valid_bias_ids_once()
    print(f"Catalog: {len(valid_ids)} valid ids")

    print("Querying core.reasoning_traces JOIN core.retrieval_comparisons ...")
    rows = await _fetch_joined_rows()
    print(f"Joined rows (non-empty final_list): {len(rows)}")

    pairs, dropped_names = build_pairs(rows, valid_ids)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for pair in pairs:
            f.write(json.dumps(pair) + "\n")

    print(f"Wrote {len(pairs)} weak-supervision pairs to {output_path}")
    if dropped_names:
        print("Dropped unmappable label(s) (row kept, only the bad name removed):")
        for run_id, names in dropped_names.items():
            print(f"  {run_id}: {names}")
    empty_label_pairs = [p["run_id"] for p in pairs if not p["bias_ids"]]
    if empty_label_pairs:
        print(f"WARNING: {len(empty_label_pairs)} pair(s) ended up with bias_ids=[] after dropping unmappable names: {empty_label_pairs}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(_main_async(args.output))


if __name__ == "__main__":
    main()
