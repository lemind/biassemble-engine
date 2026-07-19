#!/usr/bin/env python
"""Run the bias retrieval evaluation against live Supabase.

Usage:
    ENGINE_URL="" HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_evaluation.py
    ENGINE_URL="" HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_evaluation.py --promote
    ENGINE_URL="" HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_evaluation.py --diagnostics
"""
import argparse
import asyncio
import json
import os
import shutil
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

# httpx crashes on socks:// proxy scheme. Save and clear before any imports
# that trigger httpx client creation. Restore after so psql subprocess inherits them.
_PROXY_VARS = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
_saved_proxy = {k: os.environ.pop(k) for k in _PROXY_VARS if k in os.environ}

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
import httpx

from src.config import settings
from src.evaluation.evaluate import EvalRun, GroupMetrics, ScenarioResult, run_evaluation, run_evaluation_sync, _aggregate, load_baseline, compute_deltas, K as _EVAL_K

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
    from src.providers.sentence_transformer import SentenceTransformerProvider

    RUNS_DIR.mkdir(exist_ok=True)
    BASELINES_DIR.mkdir(exist_ok=True)

    print(f"taxonomy_version={settings.taxonomy_version}  model={settings.embedding_model}")
    provider = SentenceTransformerProvider(settings.embedding_model)

    # When psql_search=True, the asyncpg pool is never used for vector search
    # (psql subprocess handles it). Skip pool creation to avoid TCP connections
    # that hang through the local SOCKS proxy.
    if settings.psql_search:
        pool = None
    else:
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
        if pool is not None:
            await pool.close()

    _print_run(run)

    run_path = RUNS_DIR / f"run_{run.run_date}.json"
    run_path.write_text(json.dumps(asdict(run), indent=2))
    print(f"\nSaved → {run_path}")

    if promote:
        baseline_path = BASELINES_DIR / f"baseline_{run.run_date}.json"
        shutil.copy(run_path, baseline_path)
        print(f"Promoted → {baseline_path}")


async def _load_catalog_once():
    """One-off asyncpg connection for the llm_union eval catalog — separate from
    the psql-subprocess path the rest of this sync eval loop uses."""
    import asyncpg

    from src.llm.prompt import load_catalog

    conn = await asyncio.wait_for(
        asyncpg.connect(settings.database_url, statement_cache_size=0), timeout=10
    )
    try:
        pool_like = _SingleConnPool(conn)
        return await load_catalog(pool_like, settings.taxonomy_version)
    finally:
        await conn.close()


class _SingleConnPool:
    """Wraps a single asyncpg connection with the `.acquire()` async-context-manager
    interface load_catalog() expects from a real pool — avoids opening a full pool
    for one query."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc) -> None:
        return None


def main_sync(promote: bool, diagnostics: bool = False, strategy: str = "vector_only") -> None:
    """Fully synchronous path — used locally when PSQL_SEARCH=true.

    No asyncio: avoids event-loop conflicts with loky/joblib semaphores left
    by SentenceTransformer on Python 3.14. psql subprocess connects directly.
    --strategy nli_only / nli_union loads NLIClassifier + hypotheses at startup.
    """
    from src.providers.sentence_transformer import SentenceTransformerProvider

    RUNS_DIR.mkdir(exist_ok=True)
    BASELINES_DIR.mkdir(exist_ok=True)

    print(f"taxonomy_version={settings.taxonomy_version}  model={settings.embedding_model}  strategy={strategy}")
    if diagnostics:
        print("diagnostics mode — fetching chunk metadata per scenario")
    provider = SentenceTransformerProvider(settings.embedding_model)
    # Restore proxy vars now that httpx client is created — psql subprocess needs them.
    os.environ.update(_saved_proxy)

    nli_kwargs: dict = {}
    if strategy in ("nli_only", "nli_union"):
        from pathlib import Path as _Path
        from src.nli.classifier import NLIClassifier
        from src.nli.combiner import CombinerConfig
        from src.nli.hypothesis_loader import load_hypotheses

        print("Loading hypotheses and NLI model (first run ~30s) ...")
        hypotheses = load_hypotheses(settings.hypotheses_path)
        hypotheses_version = _Path(settings.hypotheses_path).stem

        nli_classifier = NLIClassifier()
        print(f"NLI model loaded: {settings.nli_model}")
        hypotheses_snapshot = {bid: hyp for bid, hyp in hypotheses}

        if strategy == "nli_only":
            w_nli, w_vec, vec_gate = 1.0, 0.0, 1.1  # disable vector gate for pure NLI eval
        else:
            w_nli, w_vec, vec_gate = settings.w_nli, settings.w_vec, settings.vec_gate

        combiner_config = CombinerConfig(
            w_nli=w_nli, w_vec=w_vec,
            nli_gate=settings.nli_gate,
            vec_gate=vec_gate,
            combined_threshold=settings.combined_threshold,
        )
        nli_kwargs = dict(
            nli_classifier=nli_classifier,
            hypotheses=hypotheses,
            hypotheses_version=hypotheses_version,
            combiner_config=combiner_config,
            hypotheses_snapshot=hypotheses_snapshot,
            selection_strategy=strategy,
        )

    llm_kwargs: dict = {}
    if strategy == "llm_union":
        from src.llm.generator import LLMGenerator

        # Catalog load is the only asyncpg use on this sync path — a single
        # short-lived connection just for one lightweight query, not the bulk
        # vector-search pattern that hangs through the local SOCKS proxy.
        print("Loading bias catalog (asyncpg, one-off) ...")
        catalog = asyncio.run(_load_catalog_once())
        print(f"Catalog loaded: {len(catalog)} biases")

        print("Loading GGUF model (first run downloads + ~1s load) ...")
        generator = LLMGenerator(
            model_repo=settings.llm_model_repo,
            gguf_file=settings.llm_gguf_file,
            context_tokens=settings.llm_context_tokens,
            threads=settings.llm_threads,
            max_output_tokens=settings.llm_max_output_tokens,
            temperature=settings.llm_temperature,
        )
        print(f"LLM model loaded: {settings.llm_model_repo}/{settings.llm_gguf_file}")
        llm_kwargs = dict(
            llm_generator=generator,
            llm_catalog=catalog,
            selection_strategy=strategy,
        )

    run = run_evaluation_sync(
        provider=provider,
        eval_dir=EVAL_DIR,
        baselines_dir=BASELINES_DIR,
        run_date=date.today().isoformat(),
        taxonomy_version=settings.taxonomy_version,
        diagnostics=diagnostics,
        **nli_kwargs,
        **llm_kwargs,
    )

    _print_run(run)

    run_path = RUNS_DIR / f"run_{run.run_date}.json"
    run_path.write_text(json.dumps(asdict(run), indent=2))
    print(f"\nSaved → {run_path}")

    if diagnostics:
        diag_dir = EVAL_DIR / "diagnostics"
        diag_dir.mkdir(exist_ok=True)
        diag_path = diag_dir / f"diagnostics_{run.run_date}.json"
        diag_data = [
            {
                "scenario_id": r.scenario_id,
                "group": r.group,
                "expected": r.expected,
                "retrieved": r.retrieved,
                "recall_at_k": r.recall_at_k,
                "retrieved_with_diagnostics": r.retrieved_with_diagnostics,
            }
            for r in run.scenario_results
        ]
        diag_path.write_text(json.dumps(diag_data, indent=2))
        print(f"Diagnostics → {diag_path}")

    if promote:
        baseline_path = BASELINES_DIR / f"baseline_{run.run_date}.json"
        shutil.copy(run_path, baseline_path)
        print(f"Promoted → {baseline_path}")


def _make_eval_run(data: dict) -> EvalRun:
    try:
        scenario_results = [ScenarioResult(**r) for r in data["scenario_results"]]
        group_metrics = {k: GroupMetrics(**v) for k, v in data["group_metrics"].items()}
    except TypeError as exc:
        raise ValueError(
            f"ScenarioResult/GroupMetrics schema mismatch — "
            f"is local code in sync with the deployed service? ({exc})"
        ) from exc
    return EvalRun(
        run_date=data["run_date"],
        taxonomy_version=data["taxonomy_version"],
        embedding_model=data["embedding_model"],
        k=data["k"],
        scenario_results=scenario_results,
        group_metrics=group_metrics,
        deltas=data.get("deltas"),
        selection_strategy=data.get("selection_strategy"),
        hypotheses_version=data.get("hypotheses_version"),
        hypotheses=data.get("hypotheses"),
    )


_EVAL_GROUPS = ["positive", "negative", "adversarial", "edge"]


def _poll_group(url: str, headers: dict, group: str) -> list[dict]:
    """POST /evaluate?groups=<group>, poll until done, return scenario_results list."""
    import time as _time

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{url}?groups={group}", headers=headers)
    if resp.status_code != 202:
        print(f"\nERROR {resp.status_code}: {resp.text}")
        raise SystemExit(1)
    job_id = resp.json()["job_id"]
    poll_url = f"{url}/{job_id}"
    print(f"  job_id={job_id}")
    print(f"  if client crashes, fetch manually:")
    print(f'    curl -s \\')
    print(f'      -H "Authorization: Bearer $(cat ~/.cache/huggingface/token)" \\')
    _env_path = Path(__file__).parent.parent / ".env"
    print(f'      -H "X-RAG-Key: $(grep ^RAG_API_KEY {_env_path} | cut -d= -f2)" \\')
    print(f'      "{poll_url}"')

    _poll_timeout = httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0)
    consecutive_timeouts = 0
    last_partial: list = []
    while True:
        _time.sleep(10)
        try:
            with httpx.Client(timeout=_poll_timeout) as client:
                resp = client.get(poll_url, headers=headers)
            consecutive_timeouts = 0
        except (httpx.ReadTimeout, httpx.ConnectTimeout):
            consecutive_timeouts += 1
            print(f"\n  timeout ×{consecutive_timeouts}", end="", flush=True)
            continue
        if resp.status_code == 404:
            if last_partial:
                print(f"\n  Space restarted — {len(last_partial)} scenarios recovered from client cache")
                print(f"  to retry missing scenarios re-run: PYTHONUNBUFFERED=1 .venv/bin/python scripts/run_evaluation.py --strategy nli_union --promote")
                return last_partial
            print(f"\n  job not found — Space may have restarted before any scenario completed")
            print(f"  re-run: PYTHONUNBUFFERED=1 .venv/bin/python scripts/run_evaluation.py --strategy nli_union --promote")
            raise SystemExit(1)
        if resp.status_code == 500:
            print(f"\nERROR: {resp.json().get('error', resp.text)}")
            raise SystemExit(1)
        data = resp.json()
        status = data.get("status")
        done = data.get("scenarios_done", 0)
        total = data.get("scenarios_total", 0)
        last_partial = data.get("partial", last_partial)
        if status == "running":
            print(f" {done}/{total}", end="", flush=True)
            continue
        if status == "partial":
            # /tmp survived Space restart — job is dead but disk has partial data
            print(f"\n  Space restarted — recovered {len(last_partial)}/{total} scenarios from Space disk")
            print(f"  to retry missing scenarios re-run: PYTHONUNBUFFERED=1 .venv/bin/python scripts/run_evaluation.py --strategy nli_union --promote")
            return last_partial
        # done
        return data.get("scenario_results", [])


def main_remote(promote: bool) -> None:
    """Call POST /evaluate on the deployed service one group at a time, merge results."""
    RUNS_DIR.mkdir(exist_ok=True)
    BASELINES_DIR.mkdir(exist_ok=True)

    base_url = f"{settings.engine_url.rstrip('/')}/evaluate"
    hf_token = Path.home() / ".cache/huggingface/token"
    headers = {"X-RAG-Key": settings.rag_api_key}
    if hf_token.exists():
        headers["Authorization"] = f"Bearer {hf_token.read_text().strip()}"

    all_scenario_results: list[dict] = []

    for group in _EVAL_GROUPS:
        print(f"\n[{group}]", end=" ", flush=True)
        results = _poll_group(base_url, headers, group)
        all_scenario_results.extend(results)
        print(f"  → {len(results)} scenarios", flush=True)

    # Reconstruct a full EvalRun from merged scenario results
    from datetime import date as _date

    run_date = _date.today().isoformat()
    scenario_results_objs = [ScenarioResult(**r) for r in all_scenario_results]
    group_metrics = _aggregate(scenario_results_objs)
    baseline = load_baseline(BASELINES_DIR)
    deltas = compute_deltas(group_metrics, baseline) if baseline else None

    run = EvalRun(
        run_date=run_date,
        taxonomy_version=settings.taxonomy_version,
        embedding_model=settings.embedding_model,
        k=_EVAL_K,
        scenario_results=scenario_results_objs,
        group_metrics=group_metrics,
        deltas=deltas,
        selection_strategy="nli_union",
        hypotheses_version=None,
        hypotheses=None,
    )

    print()
    _print_run(run)

    data = asdict(run)
    run_path = RUNS_DIR / f"run_{run.run_date}.json"
    run_path.write_text(json.dumps(data, indent=2))
    print(f"\nSaved → {run_path}")

    if promote:
        baseline_path = BASELINES_DIR / f"baseline_{run.run_date}.json"
        shutil.copy(run_path, baseline_path)
        print(f"Promoted → {baseline_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--promote", action="store_true", help="Copy run to baselines/")
    parser.add_argument("--diagnostics", action="store_true", help="Fetch chunk metadata per scenario and write diagnostics JSON")
    parser.add_argument(
        "--strategy",
        choices=["vector_only", "nli_only", "nli_union", "llm_union"],
        default="vector_only",
        help="Selection strategy: nli_only (W_VEC=0), nli_union (weighted), "
        "llm_union (generative LLM), vector_only (default)",
    )
    args = parser.parse_args()

    if args.diagnostics and args.strategy != "vector_only":
        print(
            "ERROR: --diagnostics is only supported with --strategy vector_only; "
            "NLI/LLM paths do not produce chunk-level diagnostics"
        )
        raise SystemExit(1)

    if args.diagnostics and (settings.engine_url or not settings.psql_search):
        print("WARNING: --diagnostics is only supported with PSQL_SEARCH=true and ENGINE_URL unset; flag ignored")

    if args.strategy != "vector_only" and not settings.psql_search:
        print(
            "ERROR: --strategy nli_only/nli_union/llm_union requires "
            "PSQL_SEARCH=true for local evaluation"
        )
        raise SystemExit(1)

    if args.strategy != "vector_only" and settings.engine_url:
        print(
            "ERROR: unset ENGINE_URL for local nli_only/nli_union/llm_union evaluation "
            "(e.g. ENGINE_URL= .venv/bin/python scripts/run_evaluation.py --strategy ...)"
        )
        raise SystemExit(1)

    if settings.engine_url:
        main_remote(args.promote)
    elif settings.psql_search:
        main_sync(args.promote, args.diagnostics, args.strategy)
    else:
        asyncio.run(main(args.promote))
