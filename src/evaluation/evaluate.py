"""Evaluation pipeline for bias retrieval.

Loads scenario files from evaluations/, runs the retriever per scenario,
computes Recall@K, Precision@K, MRR, nDCG@K, and empty_rate per group.
Compares against the latest baseline if one exists.

Groups included in scoring: positive, negative, adversarial, edge.
Groups skipped: capability_probes (tests capabilities the retriever doesn't have),
                regression (populated on-demand after bug fixes).
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from src.providers.base import EmbeddingProvider
from src.retrieval.retriever import IndexNotFoundError, retrieve
from src.schemas.request import RetrieveRequest, StoryAnalysis

K = 5

_SKIP_GROUPS = {"capability_probes", "regression"}


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Scenario:
    scenario_id: str
    group: str
    story: str
    story_analysis: dict | None
    expected_bias_ids: list[str]


@dataclass
class ScenarioResult:
    scenario_id: str
    group: str
    expected: list[str]
    retrieved: list[str]
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    error: str | None = None


@dataclass
class GroupMetrics:
    group: str
    count: int
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    empty_rate: float   # fraction of scenarios where retrieved == []


@dataclass
class EvalRun:
    run_date: str
    taxonomy_version: str
    embedding_model: str
    k: int
    scenario_results: list[ScenarioResult]
    group_metrics: dict[str, GroupMetrics]
    deltas: dict[str, dict[str, float]] | None   # None when no baseline exists


# ── Metric functions ──────────────────────────────────────────────────────────

def recall_at_k(retrieved: list[str], expected: list[str]) -> float:
    """Fraction of expected biases found in the top-K retrieved list."""
    if not expected:
        return 1.0 if not retrieved else 0.0
    return len(set(retrieved) & set(expected)) / len(expected)


def precision_at_k(retrieved: list[str], expected: list[str]) -> float:
    """Fraction of top-K retrieved biases that are in expected."""
    if not retrieved:
        return 1.0 if not expected else 0.0
    return len(set(retrieved) & set(expected)) / len(retrieved)


def mrr(retrieved: list[str], expected: list[str]) -> float:
    """Reciprocal rank of the first relevant result. 1.0 for empty/empty match."""
    expected_set = set(expected)
    for i, r in enumerate(retrieved, 1):
        if r in expected_set:
            return 1.0 / i
    return 1.0 if not expected else 0.0


def ndcg_at_k(retrieved: list[str], expected: list[str]) -> float:
    """Normalised Discounted Cumulative Gain at K.

    Rewards finding expected biases at higher ranks. IDCG is the best possible
    DCG given the expected set size and K — i.e. all expected biases in the
    first min(|expected|, K) positions.
    """
    expected_set = set(expected)
    dcg = sum(
        1.0 / math.log2(i + 1)
        for i, r in enumerate(retrieved, 1)
        if r in expected_set
    )
    ideal_hits = min(len(expected), K)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    if idcg == 0:
        return 1.0 if not retrieved else 0.0
    return dcg / idcg


# ── I/O helpers ───────────────────────────────────────────────────────────────

def load_scenarios(eval_dir: Path) -> list[Scenario]:
    """Load all scenario JSON files, skipping non-scored groups."""
    scenarios: list[Scenario] = []
    for group_dir in sorted(eval_dir.iterdir()):
        if not group_dir.is_dir() or group_dir.name in _SKIP_GROUPS:
            continue
        for f in sorted(group_dir.glob("*.json")):
            data = json.loads(f.read_text())
            scenarios.append(Scenario(
                scenario_id=data["scenario_id"],
                group=data["group"],
                story=data["story"],
                story_analysis=data.get("story_analysis"),
                expected_bias_ids=data["expected_bias_ids"],
            ))
    return scenarios


def load_baseline(baselines_dir: Path) -> dict | None:
    """Load the most recent baseline JSON, or None if no baseline exists."""
    candidates = sorted(baselines_dir.glob("baseline_*.json"))
    return json.loads(candidates[-1].read_text()) if candidates else None


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate(results: list[ScenarioResult]) -> dict[str, GroupMetrics]:
    groups: dict[str, list[ScenarioResult]] = {}
    for r in results:
        groups.setdefault(r.group, []).append(r)

    return {
        group: GroupMetrics(
            group=group,
            count=len(rs),
            recall_at_k=sum(r.recall_at_k for r in rs) / len(rs),
            precision_at_k=sum(r.precision_at_k for r in rs) / len(rs),
            mrr=sum(r.mrr for r in rs) / len(rs),
            ndcg_at_k=sum(r.ndcg_at_k for r in rs) / len(rs),
            empty_rate=sum(1 for r in rs if not r.retrieved) / len(rs),
        )
        for group, rs in groups.items()
    }


def compute_deltas(
    current: dict[str, GroupMetrics],
    baseline: dict,
) -> dict[str, dict[str, float]]:
    """Subtract baseline metric values from current to show improvement/regression."""
    baseline_groups = baseline.get("group_metrics", {})
    deltas: dict[str, dict[str, float]] = {}
    for group, gm in current.items():
        if group not in baseline_groups:
            continue
        b = baseline_groups[group]
        deltas[group] = {
            "recall_at_k":    gm.recall_at_k    - b.get("recall_at_k", 0),
            "precision_at_k": gm.precision_at_k - b.get("precision_at_k", 0),
            "mrr":            gm.mrr            - b.get("mrr", 0),
            "ndcg_at_k":      gm.ndcg_at_k      - b.get("ndcg_at_k", 0),
            "empty_rate":     gm.empty_rate      - b.get("empty_rate", 0),
        }
    return deltas


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run_evaluation(
    provider: EmbeddingProvider,
    pool: asyncpg.Pool,
    eval_dir: Path,
    baselines_dir: Path,
    run_date: str,
    taxonomy_version: str,
) -> EvalRun:
    """Run all scored scenarios and return a fully populated EvalRun."""
    scenarios = load_scenarios(eval_dir)
    results: list[ScenarioResult] = []

    for scenario in scenarios:
        try:
            analysis = StoryAnalysis(**scenario.story_analysis) if scenario.story_analysis else None
            req = RetrieveRequest(story=scenario.story, story_analysis=analysis)
            biases, _ = await retrieve(req, provider, pool)
            retrieved_ids = [b.bias_id for b in biases]
            error = None
        except IndexNotFoundError:
            retrieved_ids = []
            error = "index_not_found"
        except Exception as exc:
            retrieved_ids = []
            error = str(exc)

        top_k = retrieved_ids[:K]
        expected = scenario.expected_bias_ids
        results.append(ScenarioResult(
            scenario_id=scenario.scenario_id,
            group=scenario.group,
            expected=expected,
            retrieved=retrieved_ids,
            recall_at_k=recall_at_k(top_k, expected),
            precision_at_k=precision_at_k(top_k, expected),
            mrr=mrr(retrieved_ids, expected),
            ndcg_at_k=ndcg_at_k(top_k, expected),
            error=error,
        ))

    group_metrics = _aggregate(results)
    baseline = load_baseline(baselines_dir)
    deltas = compute_deltas(group_metrics, baseline) if baseline else None

    return EvalRun(
        run_date=run_date,
        taxonomy_version=taxonomy_version,
        embedding_model=provider.model_name,
        k=K,
        scenario_results=results,
        group_metrics=group_metrics,
        deltas=deltas,
    )
