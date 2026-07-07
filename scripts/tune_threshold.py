#!/usr/bin/env python
"""Sweep similarity_threshold from 0.25 to 0.60 and report retrieval metrics.

Usage:
    HF_HUB_OFFLINE=1 .venv/bin/python scripts/tune_threshold.py

Embeds all scenario stories once, fetches DB candidates once per scenario via
psql (lightweight query — no full_document/chunk_text to avoid TOAST timeouts),
then re-runs deduplication at each candidate threshold with no extra DB queries.
Reports neg_empty, pos_recall@5, and adv_empty side by side.

Pick the highest threshold where neg_empty = 100% that does not crush
pos_recall@5 below the pre-feature baseline. Set it in .env manually.
"""
import csv
import io
import os
import subprocess
import sys
from pathlib import Path

# httpx (used by huggingface_hub) crashes on socks:// scheme.
# psql subprocess needs the proxy vars to route traffic to Supabase.
# Save them now, clear for the Python process (httpx), re-inject per subprocess.
_PROXY_VARS = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
_saved_proxy = {k: os.environ.pop(k) for k in _PROXY_VARS if k in os.environ}

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.db.queries import fmt_vector
from src.evaluation.evaluate import K, load_baseline, load_scenarios, recall_at_k
from src.providers.sentence_transformer import SentenceTransformerProvider
from src.retrieval.query_builder import get_query_strategy
from src.retrieval.searcher import _lightweight_search_query
from src.schemas.request import RetrieveRequest, StoryAnalysis

EVAL_DIR = Path("evaluations")
BASELINES_DIR = EVAL_DIR / "baselines"
THRESHOLDS = [round(0.25 + i * 0.025, 3) for i in range(15)]  # 0.250 … 0.600

_NLI_WEIGHTS = [0.5, 0.7, 0.9]
_NLI_GATES = [0.70, 0.75, 0.80]
_COMB_THRESHOLDS = [0.50, 0.55, 0.60, 0.65]


def _fetch_candidates(scenario, provider) -> list[tuple[str, float]]:
    """Return [(bias_id, score), ...] for a scenario, fetched via psql."""
    strategy = get_query_strategy(settings.query_strategy)
    analysis = StoryAnalysis(**scenario.story_analysis) if scenario.story_analysis else None
    req = RetrieveRequest(story=scenario.story, story_analysis=analysis)
    query_text = strategy.build(req.story, req.story_analysis)
    embedding = provider.embed_query(query_text)

    sql = _lightweight_search_query(fmt_vector(embedding), settings.taxonomy_version, settings.search_top_k)
    result = subprocess.run(
        ["psql", settings.database_url, "--no-psqlrc", "--csv", "-c", sql],
        capture_output=True, text=True, timeout=90,
        env={**os.environ, **_saved_proxy},
    )
    if result.returncode != 0:
        print(f"  psql error for {scenario.scenario_id}: {result.stderr.strip()}", file=sys.stderr)
        return []
    return [(r["bias_id"], float(r["retrieval_score"])) for r in csv.DictReader(io.StringIO(result.stdout))]


def _apply_threshold(raw: list[tuple[str, float]], threshold: float) -> list[str]:
    """Filter by threshold, dedup by max score per bias_id, return top-K bias_ids."""
    surviving = [(bid, score) for bid, score in raw if score >= threshold]
    if not surviving:
        return []
    best: dict[str, float] = {}
    for bid, score in surviving:
        if bid not in best or score > best[bid]:
            best[bid] = score
    sorted_biases = sorted(best.items(), key=lambda x: x[1], reverse=True)
    return [bid for bid, _ in sorted_biases[:settings.return_top_k]]


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
        for s, raw in scenario_candidates:
            retrieved = _apply_threshold(raw, threshold)
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


def _rate(by_group: dict, group: str, metric: str) -> str:
    rs = by_group.get(group, [])
    if not rs:
        return "   N/A"
    if metric == "empty":
        v = sum(1 for r in rs if not r["retrieved"]) / len(rs)
    else:
        v = sum(r["recall"] for r in rs) / len(rs)
    return f"{v:>7.3f}"


def sweep_weights() -> None:
    """Sweep W_NLI × NLI_GATE × COMBINED_THRESHOLD over the full eval set.

    NLI inference runs once per scenario (expensive); combiner re-applies 36 configs
    in-memory. W_VEC = 1 - W_NLI. VEC_GATE stays at settings.vec_gate throughout.
    """
    from src.nli.classifier import NLIClassifier
    from src.nli.combiner import CombinerConfig, combine
    from src.nli.hypothesis_loader import load_hypotheses

    print(f"taxonomy_version={settings.taxonomy_version}  model={settings.embedding_model}")
    provider = SentenceTransformerProvider(settings.embedding_model)
    scenarios = load_scenarios(EVAL_DIR)

    print(f"Fetching vector candidates for {len(scenarios)} scenarios ...")
    scenario_vec: list[tuple] = []
    for i, s in enumerate(scenarios, 1):
        raw = _fetch_candidates(s, provider)
        # Mirror production path: apply similarity_threshold before passing to
        # combine() so normalization uses the same set of biases as the live service.
        vec_raw: dict[str, float] = {}
        for bid, score in raw:
            if score >= settings.similarity_threshold and (bid not in vec_raw or score > vec_raw[bid]):
                vec_raw[bid] = score
        scenario_vec.append((s, vec_raw))
        print(f"  {i}/{len(scenarios)}  {s.scenario_id}", end="\r")
    print()

    print("Loading NLI model (first run ~30s) ...")
    hypotheses = load_hypotheses(settings.hypotheses_path)
    nli_classifier = NLIClassifier()
    print(f"NLI model ready. Running inference for {len(scenarios)} scenarios ...")
    nli_scores_list: list[dict[str, float]] = []
    for i, (s, _) in enumerate(scenario_vec, 1):
        result = nli_classifier.classify(s.story, hypotheses)
        nli_scores_list.append(result.scores)
        print(f"  {i}/{len(scenarios)}  {s.scenario_id}", end="\r")
    print()

    col = "{:>6}  {:>9}  {:>9}  {:>10}  {:>8}  {:>8}  {:>9}"
    print("\n" + col.format("w_nli", "nli_gate", "comb_thr", "neg_empty", "pos_r@5", "adv_r@5", "edge_r@5"))
    print("─" * 74)

    for w_nli in _NLI_WEIGHTS:
        for nli_gate in _NLI_GATES:
            for comb_thr in _COMB_THRESHOLDS:
                config = CombinerConfig(
                    w_nli=w_nli, w_vec=round(1.0 - w_nli, 1),
                    nli_gate=nli_gate, vec_gate=settings.vec_gate,
                    combined_threshold=comb_thr,
                )
                by_group: dict[str, list[dict]] = {}
                for (s, vec_raw), nli_scores in zip(scenario_vec, nli_scores_list):
                    output = combine(nli_scores, vec_raw, config)
                    admitted = output.admitted[:K]
                    by_group.setdefault(s.group, []).append({
                        "retrieved": admitted,
                        "recall": recall_at_k(admitted, s.expected_bias_ids),
                    })

                is_current = (
                    abs(w_nli - settings.w_nli) < 0.001
                    and abs(nli_gate - settings.nli_gate) < 0.001
                    and abs(comb_thr - settings.combined_threshold) < 0.001
                )
                flag = " ← current" if is_current else ""
                print(col.format(
                    f"{w_nli:.1f}", f"{nli_gate:.2f}", f"{comb_thr:.2f}",
                    _rate(by_group, "negative", "empty"),
                    _rate(by_group, "positive", "recall"),
                    _rate(by_group, "adversarial", "recall"),
                    _rate(by_group, "edge", "recall"),
                ) + flag)

    print("\nDone. Set W_NLI, NLI_GATE, COMBINED_THRESHOLD in .env to the winning config.")


if __name__ == "__main__":
    import argparse as _argparse
    _parser = _argparse.ArgumentParser()
    _parser.add_argument("--sweep-weights", action="store_true", help="Sweep NLI weight configs instead of threshold")
    _args = _parser.parse_args()

    if _args.sweep_weights:
        sweep_weights()
    else:
        main()
