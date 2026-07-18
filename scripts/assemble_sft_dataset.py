#!/usr/bin/env python
"""Merge weak-supervision pairs + labeled synthetic stories into the SFT
training dataset, enforcing every rule in contracts/sft-dataset-schema.md.

Two CLI modes:
  --coverage-report-only   writes evaluations/sft/coverage_report.json and
                            exits WITHOUT touching sft_dataset.jsonl at all —
                            used to check whether a candidate batch would pass
                            before committing to it (tasks.md T015's
                            iterate-until-passing loop).
  --output <path>          writes both coverage_report.json AND the dataset
                            file, but ONLY if every rule passes. On failure,
                            writes the report only — never a partial/
                            incomplete dataset file.

Never reads evaluations/blind_spot/ — the "no blind-spot overlap" rule is
enforced by construction, not a runtime content check (data-model.md).

Usage:
    uv run python scripts/assemble_sft_dataset.py \
        --weak-supervision evaluations/sft/weak_supervision_pairs.jsonl \
        --synthetic "evaluations/staging/sft_raw_batches/labeled_v2_chunk_*.jsonl" \
        --coverage-report-only
"""

import argparse
import collections
import glob
import hashlib
import json
import sys
from pathlib import Path

from scripts.validate_bias_catalog import load_valid_bias_ids

REQUIRED_GROUPS = {"positive", "negative", "edge", "adversarial"}
PER_BIAS_FLOOR = 15
NEGATIVE_FRACTION_FLOOR = 0.18
SYNTHETIC_VOLUME_FLOOR = 300


def load_weak_supervision(path: Path) -> list[dict]:
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    out = []
    for r in rows:
        out.append(
            {
                "story": "\n\n".join(r["story_excerpts"]),
                "bias_ids": r["bias_ids"],
                "source": "real_weak",
                "spot_checked": True,  # real, assessment-confirmed production outcomes
                "group": None,  # real_weak pairs aren't tagged to a scenario-group shape
                "generator_model": None,
                "generation_prompt_version": None,
                "teacher_model": None,
                "label_prompt_version": None,
            }
        )
    return out


def load_synthetic(pattern: str) -> list[dict]:
    paths = sorted(glob.glob(pattern))
    if not paths:
        print(f"WARNING: no files matched synthetic pattern {pattern!r}", file=sys.stderr)
    out = []
    seen_stories = set()
    for p in paths:
        for line in Path(p).read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            story = r["story"].strip()
            if story in seen_stories:
                continue  # defensive dedup; consolidation should have already caught this
            seen_stories.add(story)
            out.append(
                {
                    "story": r["story"],
                    "bias_ids": r["bias_ids"],
                    "source": "synthetic",
                    "spot_checked": False,  # T014 human spot-check has not run yet
                    "group": r.get("group"),
                    "generator_model": r.get("provider_tag"),
                    "generation_prompt_version": r.get("batch_tag"),
                    "teacher_model": r.get("teacher_model"),
                    "label_prompt_version": r.get("label_prompt_version"),
                }
            )
    return out


def compute_dataset_version(rows: list[dict]) -> str:
    """Deterministic content hash — same rows in any order hash the same."""
    canonical = sorted(json.dumps(r, sort_keys=True) for r in rows)
    return "sha256:" + hashlib.sha256("\n".join(canonical).encode()).hexdigest()


def compute_coverage_report(
    weak_rows: list[dict], synthetic_rows: list[dict], valid_ids: set[str]
) -> dict:
    all_rows = weak_rows + synthetic_rows

    # Rule 1: catalog membership — defensive re-check, upstream should have
    # already enforced this (T003/label_sft_stories.py), but re-validate here
    # too rather than trust blindly.
    catalog_violations = [
        r for r in all_rows if any(b not in valid_ids for b in r["bias_ids"])
    ]

    counts_by_source = collections.Counter(r["source"] for r in all_rows)
    counts_by_group = collections.Counter(r["group"] for r in synthetic_rows if r["group"])
    per_bias_counts = collections.Counter()
    for r in all_rows:
        for b in r["bias_ids"]:
            per_bias_counts[b] += 1
    negative_count = sum(1 for r in all_rows if not r["bias_ids"])
    negative_fraction = negative_count / len(all_rows) if all_rows else 0.0

    # Rule 2: group coverage — synthetic rows must span all four shapes.
    missing_groups = REQUIRED_GROUPS - set(counts_by_group.keys())

    # Rule 3: per-bias floor across the WHOLE dataset (real_weak + synthetic).
    under_floor = {b: per_bias_counts.get(b, 0) for b in valid_ids if per_bias_counts.get(b, 0) < PER_BIAS_FLOOR}

    # Rule 5: synthetic volume floor (real_weak is additive, not counted toward this).
    synthetic_volume = counts_by_source.get("synthetic", 0)

    passed = (
        not catalog_violations
        and not missing_groups
        and not under_floor
        and negative_fraction >= NEGATIVE_FRACTION_FLOOR
        and synthetic_volume >= SYNTHETIC_VOLUME_FLOOR
    )

    report = {
        "dataset_version": compute_dataset_version(all_rows),
        "total_rows": len(all_rows),
        "counts_by_source": dict(counts_by_source),
        "counts_by_group": dict(counts_by_group),
        "per_bias_counts": {b: per_bias_counts.get(b, 0) for b in sorted(valid_ids)},
        "negative_fraction": negative_fraction,
        "pass": passed,
        # diagnostic detail, not part of the formal CoverageReport shape but
        # useful for a failed-attempt diagnosis without recomputing by hand
        "_diagnostics": {
            "catalog_violations": [r["story"][:60] for r in catalog_violations],
            "missing_groups": sorted(missing_groups),
            "under_floor_biases": under_floor,
            "synthetic_volume": synthetic_volume,
            "synthetic_volume_floor": SYNTHETIC_VOLUME_FLOOR,
        },
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weak-supervision", required=True, type=Path)
    parser.add_argument("--synthetic", required=True, help="glob pattern for labeled synthetic jsonl files")
    parser.add_argument("--output", type=Path, help="dataset output path; omit for --coverage-report-only")
    parser.add_argument("--coverage-report-only", action="store_true")
    parser.add_argument(
        "--coverage-report-path",
        type=Path,
        default=Path("evaluations/sft/coverage_report.json"),
    )
    args = parser.parse_args()

    if not args.coverage_report_only and not args.output:
        print("ERROR: --output is required unless --coverage-report-only is set", file=sys.stderr)
        sys.exit(2)

    valid_ids = load_valid_bias_ids()
    weak_rows = load_weak_supervision(args.weak_supervision)
    synthetic_rows = load_synthetic(args.synthetic)

    report = compute_coverage_report(weak_rows, synthetic_rows, valid_ids)

    args.coverage_report_path.parent.mkdir(parents=True, exist_ok=True)
    args.coverage_report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Wrote {args.coverage_report_path}")
    print(f"  total_rows={report['total_rows']} pass={report['pass']}")
    print(f"  counts_by_source={report['counts_by_source']}")
    print(f"  negative_fraction={report['negative_fraction']:.1%}")
    diag = report["_diagnostics"]
    if diag["missing_groups"]:
        print(f"  MISSING GROUPS: {diag['missing_groups']}")
    if diag["under_floor_biases"]:
        print(f"  {len(diag['under_floor_biases'])} bias(es) under the {PER_BIAS_FLOOR}-floor:")
        for b, c in sorted(diag["under_floor_biases"].items(), key=lambda x: x[1]):
            print(f"    {b}: {c}")
    print(f"  synthetic volume: {diag['synthetic_volume']} / {diag['synthetic_volume_floor']} floor")

    if args.coverage_report_only:
        return

    if not report["pass"]:
        print("NOT writing dataset file — coverage report failed. See above.", file=sys.stderr)
        sys.exit(1)

    all_rows = weak_rows + synthetic_rows
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")
    print(f"Wrote {len(all_rows)} rows -> {args.output}")


if __name__ == "__main__":
    main()
