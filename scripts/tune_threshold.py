#!/usr/bin/env python
"""Sweep similarity_threshold from 0.25 to 0.60 and report retrieval metrics.

Usage:
    .venv/bin/python scripts/tune_threshold.py

Embeds all scenario stories once, fetches DB candidates once per scenario via
psql, then re-runs the reranker at each candidate threshold with no extra DB
queries. Reports neg_empty, pos_recall@5, and adv_empty side by side.

Pick the highest threshold where neg_empty = 100% that does not crush
pos_recall@5 below the pre-feature baseline. Set it in .env manually.
"""
import csv
import io
import os
import subprocess
import sys
from pathlib import Path

for _var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
    os.environ.pop(_var, None)

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.db.queries import fmt_vector
from src.evaluation.evaluate import K, load_baseline, load_scenarios, recall_at_k
from src.providers.sentence_transformer import SentenceTransformerProvider
from src.retrieval.query_builder import get_query_strategy
from src.retrieval.reranker import rerank
from src.retrieval.searcher import _build_search_query, _row_to_candidate_csv
from src.schemas.request import RetrieveRequest, StoryAnalysis

EVAL_DIR = Path("evaluations")
BASELINES_DIR = EVAL_DIR / "baselines"

THRESHOLDS = [round(0.25 + i * 0.025, 3) for i in range(15)]  # 0.250 … 0.600


def _fetch_candidates(scenario, provider) -> list:
    strategy = get_query_strategy(settings.query_strategy)
    analysis = StoryAnalysis(**scenario.story_analysis) if scenario.story_analysis else None
    req = RetrieveRequest(story=scenario.story, story_analysis=analysis)
    query_text = strategy.build(req.story, req.story_analysis)
    embedding = provider.embed_query(query_text)

    sql = _build_search_query(fmt_vector(embedding), settings.taxonomy_version, settings.search_top_k)
    result = subprocess.run(
        ["psql", settings.database_url, "--no-psqlrc", "--csv", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"  psql error for {scenario.scenario_id}: {result.stderr.strip()}", file=sys.stderr)
        return []
    return [_row_to_candidate_csv(r) for r in csv.DictReader(io.StringIO(result.stdout))]


def main() -> None:
    print(f"taxonomy_version={settings.taxonomy_version}  model={settings.embedding_model}")

    provider = SentenceTransformerProvider(settings.embedding_model)
    scenarios = load_scenarios(EVAL_DIR)
    print(f"Fetching candidates for {len(scenarios)} scenarios ...")

    scenario_candidates = []
    for i, s in enumerate(scenarios, 1):
        candidates = _fetch_candidates(s, provider)
        scenario_candidates.append((s, candidates))
        print(f"  {i}/{len(scenarios)}  {s.scenario_id}", end="\r")
    print()

    baseline = load_baseline(BASELINES_DIR)
    baseline_pos = baseline["group_metrics"].get("positive", {}).get("recall_at_k", None) if baseline else None

    print(f"\n{'threshold':>10}  {'neg_empty':>10}  {'pos_recall@5':>13}  {'adv_empty':>10}")
    print("─" * 52)

    recommended: float | None = None
    for threshold in THRESHOLDS:
        by_group: dict[str, list[dict]] = {}
        for s, candidates in scenario_candidates:
            biases = rerank(candidates, threshold, settings.return_top_k)
            retrieved = [b.bias_id for b in biases]
            by_group.setdefault(s.group, []).append({
                "retrieved": retrieved,
                "recall": recall_at_k(retrieved[:K], s.expected_bias_ids),
            })

        def _empty(group: str) -> float | None:
            rs = by_group.get(group, [])
            return sum(1 for r in rs if not r["retrieved"]) / len(rs) if rs else None

        def _recall(group: str) -> float | None:
            rs = by_group.get(group, [])
            return sum(r["recall"] for r in rs) / len(rs) if rs else None

        neg_empty = _empty("negative")
        pos_recall = _recall("positive")
        adv_empty = _empty("adversarial")

        is_current = abs(threshold - settings.similarity_threshold) < 0.001
        passes = (
            neg_empty == 1.0
            and pos_recall is not None
            and (baseline_pos is None or pos_recall >= baseline_pos - 0.001)
        )
        if passes:
            recommended = threshold  # keep overwriting → ends up at the highest passing threshold

        def _fmt_pct(v: float | None) -> str:
            return f"{v:>10.0%}" if v is not None else "       N/A"

        flag = " ← current" if is_current else ""
        pos_str = f"{pos_recall:>13.3f}" if pos_recall is not None else "          N/A"
        print(f"{threshold:>10.3f}  {_fmt_pct(neg_empty)}  {pos_str}  {_fmt_pct(adv_empty)}{flag}")

    print()
    if baseline_pos is not None:
        print(f"Baseline pos_recall@5: {baseline_pos:.3f}")
    if recommended is not None:
        print(f"Recommended SIMILARITY_THRESHOLD: {recommended:.3f}  (highest threshold where neg_empty=100% and pos_recall >= baseline)")
    else:
        print("No threshold found where neg_empty=100% — consider lowering the threshold range")


if __name__ == "__main__":
    main()
