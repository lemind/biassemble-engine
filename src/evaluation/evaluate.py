"""Evaluation pipeline for bias retrieval.

Loads scenario files from evaluations/, runs the retriever per scenario,
computes Recall@K, Precision@K, MRR, nDCG@K, and empty_rate per group.
Compares against the latest baseline if one exists.

Groups included in scoring: positive, negative, adversarial, edge.
Groups skipped: capability_probes (tests capabilities the retriever doesn't have),
                regression (populated on-demand after bug fixes).
"""

import asyncio
import csv
import io
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import structlog

from src.config import settings
from src.db.queries import fmt_vector
from src.providers.base import EmbeddingProvider
from src.retrieval.query_builder import get_query_strategy
from src.nli.combiner import combine
from src.retrieval.retriever import IndexNotFoundError, retrieve
from src.retrieval.searcher import _dedup_bias_rows, _diagnostics_search_query, _lightweight_search_query
from src.schemas.internal import RetrievedBias
from src.schemas.request import RetrieveRequest, StoryAnalysis

K = 5

_SKIP_GROUPS = {"capability_probes", "regression", "runs", "baselines", "diagnostics"}


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
    retrieved_with_diagnostics: list[dict] | None = None
    nli_scores: dict[str, float] | None = None
    vector_scores: dict[str, float] | None = None
    combined_scores: dict[str, float] | None = None
    admitted_by: dict[str, list[str]] | None = None
    missed_by: dict[str, list[str]] | None = None


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
    selection_strategy: str | None = None
    hypotheses_version: str | None = None
    hypotheses: dict[str, str] | None = None     # {bias_id: hypothesis_text} snapshot


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


# ── NLI helpers ──────────────────────────────────────────────────────────────

def _psql_query(sql: str, scenario_id: str = "?") -> list[dict]:
    """Run a SQL query via psql subprocess with retry on timeout.

    Proxy vars are restored into os.environ by main_sync() before this is called.
    Retries up to 3 times with 5s backoff — proxy connections drop between
    sequential queries and re-establishing them adds latency.
    Raises RuntimeError on persistent failure.
    """
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["psql", settings.database_url, "--no-psqlrc", "--csv", "-c", sql],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(f"psql error: {result.stderr.strip()}")
            return list(csv.DictReader(io.StringIO(result.stdout)))
        except subprocess.TimeoutExpired:
            if attempt < 2:
                print(f"\n  timeout for {scenario_id}, retrying in 5s...", flush=True)
                time.sleep(5)
            else:
                raise RuntimeError(f"psql timed out for {scenario_id} after 3 attempts")
    return []  # unreachable


def _compute_missed_by(
    expected: list[str],
    admitted_set: set[str],
    nli_scores: dict[str, float],
    vec_raw: dict[str, float],
    vec_norm: dict[str, float],
    combined_scores: dict[str, float],
    config,
) -> dict[str, list[str]]:
    """For each expected bias not admitted, list which gates failed to fire.

    VECTOR gate uses two labels: "VECTOR:absent" (bias not returned by vector
    search at all) vs "VECTOR:below" (returned but normalized score < vec_gate).
    This distinguishes a missing-from-index failure from a scoring failure.
    """
    missed: dict[str, list[str]] = {}
    for bid in expected:
        if bid not in admitted_set:
            gates: list[str] = []
            if nli_scores.get(bid, 0.0) < config.nli_gate:
                gates.append("NLI")
            if bid not in vec_raw:
                gates.append("VECTOR:absent")
            elif vec_norm.get(bid, 0.0) < config.vec_gate:
                gates.append("VECTOR:below")
            if combined_scores.get(bid, 0.0) < config.combined_threshold:
                gates.append("COMBINED")
            missed[bid] = gates
    return missed


def _retrieve_sync_nli(
    scenario: "Scenario",
    provider: EmbeddingProvider,
    nli_classifier,
    hypotheses: list[tuple[str, str]],
    combiner_config,
) -> tuple[list[str], dict | None, str | None]:
    """NLI eval path: psql vector fetch + NLI classify + combiner.

    Returns (admitted_ids, nli_meta, error).
    nli_meta carries nli_scores, vector_scores (normalized), combined_scores,
    admitted_by, and missed_by for diagnostic logging.
    """
    try:
        strategy = get_query_strategy(settings.query_strategy)
        analysis = StoryAnalysis(**scenario.story_analysis) if scenario.story_analysis else None
        req = RetrieveRequest(story=scenario.story, story_analysis=analysis)
        query_text = strategy.build(req.story, req.story_analysis)
        embedding = provider.embed_query(query_text)

        sql = _lightweight_search_query(fmt_vector(embedding), settings.taxonomy_version, settings.search_top_k)
        rows = _psql_query(sql, scenario.scenario_id)

        # Mirror production path: apply similarity_threshold so normalization
        # uses the same set of biases as NLIUnionStrategy → VectorOnlyStrategy.
        vec_raw: dict[str, float] = {}
        for row in rows:
            bid = row["bias_id"]
            score = float(row["retrieval_score"])
            if score >= settings.similarity_threshold and (bid not in vec_raw or score > vec_raw[bid]):
                vec_raw[bid] = score

        nli_result = nli_classifier.classify(scenario.story, hypotheses)
        output = combine(nli_result.scores, vec_raw, combiner_config)
        admitted_ids = output.admitted[:K]

        nli_meta = {
            "nli_scores": nli_result.scores,
            "vector_scores": output.vector_scores,
            "combined_scores": output.combined_scores,
            "admitted_by": output.admitted_by,
            "missed_by": _compute_missed_by(
                scenario.expected_bias_ids, set(output.admitted),
                nli_result.scores, vec_raw, output.vector_scores, output.combined_scores,
                combiner_config,
            ),
        }
        return admitted_ids, nli_meta, None
    except Exception as exc:
        return [], None, str(exc)


# ── Main pipeline ─────────────────────────────────────────────────────────────

def _retrieve_sync(
    scenario: "Scenario",
    provider: EmbeddingProvider,
    diagnostics: bool = False,
) -> tuple[list[str], list[dict] | None, str | None]:
    """Synchronous retrieval path via psql subprocess — used when psql_search=True.

    Uses a lightweight query normally. When diagnostics=True, uses a richer query
    that includes chunk_type, source_section, and domain (from metadata JSONB).
    Returns (bias_ids, diag_rows_or_None, error).
    """
    try:
        strategy = get_query_strategy(settings.query_strategy)
        analysis = StoryAnalysis(**scenario.story_analysis) if scenario.story_analysis else None
        req = RetrieveRequest(story=scenario.story, story_analysis=analysis)
        query_text = strategy.build(req.story, req.story_analysis)
        embedding = provider.embed_query(query_text)

        vec = fmt_vector(embedding)
        if diagnostics:
            sql = _diagnostics_search_query(vec, settings.taxonomy_version, settings.search_top_k)
        else:
            sql = _lightweight_search_query(vec, settings.taxonomy_version, settings.search_top_k)
        rows = _psql_query(sql, scenario.scenario_id)
        if not rows:
            return [], None, "index_not_found"

        bias_ids = _dedup_bias_rows(rows, settings.similarity_threshold, settings.return_top_k)
        diag_rows = [
            {
                "bias_id": r["bias_id"],
                "chunk_type": r.get("chunk_type", ""),
                "source_section": r.get("source_section", ""),
                "domain": r.get("domain") or None,
                "retrieval_score": float(r["retrieval_score"]),
            }
            for r in rows
        ] if diagnostics else None
        return bias_ids, diag_rows, None
    except Exception as exc:
        return [], None, str(exc)


def run_evaluation_sync(
    provider: EmbeddingProvider,
    eval_dir: Path,
    baselines_dir: Path,
    run_date: str,
    taxonomy_version: str,
    diagnostics: bool = False,
    nli_classifier=None,
    hypotheses: list[tuple[str, str]] | None = None,
    hypotheses_version: str | None = None,
    combiner_config=None,
    hypotheses_snapshot: dict[str, str] | None = None,
    selection_strategy: str = "vector_only",
) -> EvalRun:
    """Fully synchronous evaluation — used locally when psql_search=True.

    When nli_classifier + hypotheses + combiner_config are provided, runs the NLI
    path (_retrieve_sync_nli) instead of the vector-only psql path. NLI diagnostic
    fields (nli_scores, vector_scores, combined_scores, admitted_by, missed_by) are
    populated on every ScenarioResult in NLI mode.
    """
    use_nli = nli_classifier is not None and hypotheses is not None and combiner_config is not None
    scenarios = load_scenarios(eval_dir)
    results: list[ScenarioResult] = []

    for scenario in scenarios:
        diag_rows: list[dict] | None = None
        nli_meta: dict | None = None
        if use_nli:
            retrieved_ids, nli_meta, error = _retrieve_sync_nli(
                scenario, provider, nli_classifier, hypotheses, combiner_config
            )
        else:
            retrieved_ids, diag_rows, error = _retrieve_sync(scenario, provider, diagnostics=diagnostics)

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
            retrieved_with_diagnostics=diag_rows,
            nli_scores=nli_meta["nli_scores"] if nli_meta else None,
            vector_scores=nli_meta["vector_scores"] if nli_meta else None,
            combined_scores=nli_meta["combined_scores"] if nli_meta else None,
            admitted_by=nli_meta["admitted_by"] if nli_meta else None,
            missed_by=nli_meta["missed_by"] if nli_meta else None,
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
        selection_strategy=selection_strategy,
        hypotheses_version=hypotheses_version,
        hypotheses=hypotheses_snapshot,
    )


async def run_evaluation(
    provider: EmbeddingProvider,
    pool: asyncpg.Pool | None,
    eval_dir: Path,
    baselines_dir: Path,
    run_date: str,
    taxonomy_version: str,
    strategy=None,
) -> EvalRun:
    """Run all scored scenarios and return a fully populated EvalRun.

    Uses synchronous psql subprocess when settings.psql_search=True (local dev
    with SOCKS proxy). Uses async asyncpg path otherwise (deployed service).
    """
    if pool is None and not settings.psql_search:
        raise ValueError("pool is required when psql_search=False")

    log = structlog.get_logger()
    scenarios = load_scenarios(eval_dir)
    total = len(scenarios)
    results: list[ScenarioResult] = []

    for i, scenario in enumerate(scenarios):
        t_scenario = time.monotonic()
        log.info("scenario_start", n=f"{i+1}/{total}", scenario_id=scenario.scenario_id, group=scenario.group)
        nli_meta: dict | None = None
        if settings.psql_search:
            retrieved_ids, _, error = await asyncio.to_thread(_retrieve_sync, scenario, provider)
        else:
            try:
                analysis = StoryAnalysis(**scenario.story_analysis) if scenario.story_analysis else None
                req = RetrieveRequest(story=scenario.story, story_analysis=analysis)
                biases, meta = await retrieve(req, provider, pool, strategy)
                retrieved_ids = [b.bias_id for b in biases]
                error = None
                if meta.nli_scores is not None:
                    nli_meta = {
                        "nli_scores": meta.nli_scores,
                        "vector_scores": meta.vector_scores,
                        "combined_scores": meta.combined_scores,
                        "admitted_by": None,
                        "missed_by": None,
                    }
            except IndexNotFoundError:
                retrieved_ids = []
                error = "index_not_found"
            except Exception as exc:
                retrieved_ids = []
                error = str(exc)
        log.info("scenario_done", n=f"{i+1}/{total}", scenario_id=scenario.scenario_id, latency_ms=round((time.monotonic() - t_scenario) * 1000))

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
            nli_scores=nli_meta["nli_scores"] if nli_meta else None,
            vector_scores=nli_meta["vector_scores"] if nli_meta else None,
            combined_scores=nli_meta["combined_scores"] if nli_meta else None,
            admitted_by=nli_meta["admitted_by"] if nli_meta else None,
            missed_by=nli_meta["missed_by"] if nli_meta else None,
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
