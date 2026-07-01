#!/usr/bin/env python
"""Run the bias retrieval evaluation against live Supabase.

Usage:
    uv run python scripts/run_evaluation.py
    uv run python scripts/run_evaluation.py --promote
"""
import argparse
import asyncio
import json
import shutil
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

from src.config import settings
from src.evaluation.evaluate import EvalRun, GroupMetrics, run_evaluation
from src.providers.sentence_transformer import SentenceTransformerProvider

EVAL_DIR = Path("evaluations")
RUNS_DIR = EVAL_DIR / "runs"
BASELINES_DIR = EVAL_DIR / "baselines"


def _delta_str(v: float) -> str:
    if abs(v) < 0.0005:
        return ""
    return f"  ({'+'if v > 0 else ''}{v:.3f} vs baseline)"


def _print_run(run: EvalRun) -> None:
    col = "{:<15} {:<14} {:<28} {:<28} {:>5} {:>5} {:>6}"
    print("\n" + col.format("Scenario", "Group", "Expected", "Retrieved", "R@5", "MRR", "nDCG"))
    print("─" * 103)

    for r in run.scenario_results:
        exp = ", ".join(r.expected[:2]) + ("…" if len(r.expected) > 2 else "")
        ret = ", ".join(r.retrieved[:2]) + ("…" if len(r.retrieved) > 2 else "")
        err = f" ⚠ {r.error}" if r.error else ""
        print(col.format(
            r.scenario_id, r.group,
            exp[:28], ret[:28],
            f"{r.recall_at_k:.2f}", f"{r.mrr:.2f}", f"{r.ndcg_at_k:.2f}",
        ) + err)

    d = run.deltas or {}
    print(f"\n{'─' * 60}")
    for group, gm in run.group_metrics.items():
        gd = d.get(group, {})
        print(f"\n  {group}  ({gm.count} scenarios)")
        print(f"    Recall@{run.k}:    {gm.recall_at_k:.3f}{_delta_str(gd.get('recall_at_k', 0))}")
        print(f"    Precision@{run.k}: {gm.precision_at_k:.3f}{_delta_str(gd.get('precision_at_k', 0))}")
        print(f"    MRR:         {gm.mrr:.3f}{_delta_str(gd.get('mrr', 0))}")
        print(f"    nDCG@{run.k}:     {gm.ndcg_at_k:.3f}{_delta_str(gd.get('ndcg_at_k', 0))}")
        print(f"    empty_rate:  {gm.empty_rate:.0%}{_delta_str(gd.get('empty_rate', 0))}")


async def main(promote: bool) -> None:
    RUNS_DIR.mkdir(exist_ok=True)
    BASELINES_DIR.mkdir(exist_ok=True)

    print(f"taxonomy_version={settings.taxonomy_version}  model={settings.embedding_model}")
    provider = SentenceTransformerProvider(settings.embedding_model)
    pool = await asyncpg.create_pool(settings.database_url, statement_cache_size=0)

    try:
        run = await run_evaluation(
            provider=provider,
            pool=pool,
            eval_dir=EVAL_DIR,
            baselines_dir=BASELINES_DIR,
            run_date=date.today().isoformat(),
            taxonomy_version=settings.taxonomy_version,
        )
    finally:
        await pool.close()

    _print_run(run)

    run_path = RUNS_DIR / f"run_{run.run_date}.json"
    run_path.write_text(json.dumps(asdict(run), indent=2))
    print(f"\nSaved → {run_path}")

    if promote:
        baseline_path = BASELINES_DIR / f"baseline_{run.run_date}.json"
        shutil.copy(run_path, baseline_path)
        print(f"Promoted → {baseline_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--promote", action="store_true", help="Copy run to baselines/")
    args = parser.parse_args()
    asyncio.run(main(args.promote))
