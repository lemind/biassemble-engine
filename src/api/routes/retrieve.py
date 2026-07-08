import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import settings
from src.db.queries import HEALTH_STATS, STATS_BY_CHUNK_TYPE, STATS_BY_SOURCE, STATS_BY_VERSION
from src.evaluation.evaluate import run_evaluation
from src.providers.base import EmbeddingProvider
from src.retrieval import retriever
from src.retrieval.retriever import IndexNotFoundError
from src.selection.vector_only import VectorOnlyStrategy
from src.schemas.internal import RetrievedBias
from src.schemas.request import RetrieveRequest
from src.schemas.response import BiasResult, RetrieveResponse

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def _verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_rag_key: str | None = Header(default=None, alias="X-RAG-Key"),
) -> None:
    token = x_rag_key or (credentials.credentials if credentials else None)
    if token != settings.rag_api_key:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})


def _to_bias_result(b: RetrievedBias) -> BiasResult:
    return BiasResult(
        id=b.bias_id,
        name=b.name,
        retrieval_score=b.retrieval_score,
        definition=b.definition,
        examples=b.examples,
        indicators=b.indicators,
        false_positives=b.false_positives,
        related_biases=b.related_biases,
    )


@router.post("/retrieve-biases", response_model=RetrieveResponse)
async def retrieve_biases(
    body: RetrieveRequest,
    request: Request,
    _: None = Depends(_verify_token),
) -> RetrieveResponse:
    provider: EmbeddingProvider = request.app.state.provider
    pool: asyncpg.Pool | None = request.app.state.pool

    if pool is None:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable"})

    try:
        biases, meta = await asyncio.wait_for(
            retriever.retrieve(body, provider, pool, request.app.state.selection_strategy),
            timeout=settings.request_timeout_ms / 1000,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail={"error": "request_timeout"})
    except IndexNotFoundError:
        raise HTTPException(
            status_code=503,
            detail={"error": "index_not_found", "taxonomy_version": settings.taxonomy_version},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "retrieval_failed", "detail": str(exc)},
        ) from exc

    biases_out = [_to_bias_result(b) for b in biases] if biases else request.app.state.roster
    return RetrieveResponse(
        biases=biases_out,
        retrieved_chunks=meta.candidate_chunks,
        taxonomy_version=meta.taxonomy_version,
        embedding_model=meta.embedding_model,
        request_id=meta.retrieval_id,
    )


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    provider: EmbeddingProvider = request.app.state.provider
    pool: asyncpg.Pool | None = request.app.state.pool

    rows_indexed: int | None = None
    last_indexed_at = None
    db_connected = False

    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(HEALTH_STATS, settings.taxonomy_version)
            rows_indexed = row["rows_indexed"]
            last_indexed_at = row["last_indexed_at"]
            db_connected = True
        except Exception:
            pass

    return {
        "status": "ok",
        "model_loaded": True,
        "embedding_model": provider.model_name,
        "embedding_dimension": settings.embedding_dimension,
        "provider_dimension": provider.dimension,
        "taxonomy_version": settings.taxonomy_version,
        "rows_indexed": rows_indexed,
        "last_indexed_at": last_indexed_at,
        "database_connected": db_connected,
    }


@router.get("/stats")
async def stats(request: Request) -> dict[str, Any]:
    provider: EmbeddingProvider = request.app.state.provider
    pool: asyncpg.Pool | None = request.app.state.pool

    indexed_rows = 0
    built_at = None
    chunk_count_by_type: dict[str, int] = {}
    sources: dict[str, int] = {}
    rows_per_taxonomy_version: dict[str, int] = {}

    if pool is not None:
        try:
            async with pool.acquire() as conn:
                health_row = await conn.fetchrow(HEALTH_STATS, settings.taxonomy_version)
                indexed_rows = health_row["rows_indexed"]
                built_at = health_row["last_indexed_at"]

                rows = await conn.fetch(STATS_BY_CHUNK_TYPE, settings.taxonomy_version)
                chunk_count_by_type = {r["chunk_type"]: r["cnt"] for r in rows}

                rows = await conn.fetch(STATS_BY_SOURCE, settings.taxonomy_version)
                sources = {r["source"]: r["cnt"] for r in rows}

                rows = await conn.fetch(STATS_BY_VERSION)
                rows_per_taxonomy_version = {r["taxonomy_version"]: r["cnt"] for r in rows}
        except Exception:
            pass

    return {
        "taxonomy_version": settings.taxonomy_version,
        "embedding_model": provider.model_name,
        "embedding_dimension": provider.dimension,
        "indexed_rows": indexed_rows,
        "chunk_count_by_type": chunk_count_by_type,
        "rows_per_taxonomy_version": rows_per_taxonomy_version,
        "sources": sources,
        "built_at": built_at,
        "git_sha": os.environ.get("GIT_SHA"),
    }


# In-memory job store — single-process uvicorn on HF Space, no multiprocessing needed.
_eval_jobs: dict[str, dict[str, Any]] = {}
_JOBS_DIR = Path("/tmp/eval_jobs")


def _persist_job(job_id: str, result: dict) -> None:
    try:
        _JOBS_DIR.mkdir(exist_ok=True)
        (_JOBS_DIR / f"{job_id}.json").write_text(json.dumps(result))
    except Exception:
        pass


def _load_job(job_id: str) -> dict | None:
    try:
        p = _JOBS_DIR / f"{job_id}.json"
        if p.exists():
            return {"status": "done", "result": json.loads(p.read_text())}
    except Exception:
        pass
    return None


@router.post("/evaluate", status_code=202)
async def evaluate_start(
    request: Request,
    _: None = Depends(_verify_token),
    strategy: str | None = None,
    groups: str | None = None,
) -> dict[str, Any]:
    """Start evaluation in the background and return a job_id immediately.

    HF Space's proxy hard-kills connections after ~90 s, making synchronous or
    streaming long-running responses unreliable. Instead: POST returns 202 with
    a job_id; the client polls GET /evaluate/{job_id} every 10 s with short
    timeouts until the result arrives.

    strategy: override the server's SELECTION_STRATEGY env var for this run.
    Use ?strategy=vector for a quick smoke test (no NLI inference).
    """
    provider: EmbeddingProvider = request.app.state.provider
    pool: asyncpg.Pool | None = request.app.state.pool
    log = structlog.get_logger()

    if pool is None:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable"})

    eval_dir = Path("evaluations")
    if not eval_dir.exists():
        raise HTTPException(status_code=503, detail={"error": "eval_dir_not_found"})

    job_id = str(uuid.uuid4())
    _eval_jobs[job_id] = {"status": "running", "partial": [], "scenarios_done": 0, "scenarios_total": 0}
    if strategy == "vector":
        resolved_strategy = VectorOnlyStrategy(provider, pool)
    else:
        resolved_strategy = request.app.state.selection_strategy
    only_groups = set(groups.split(",")) if groups else None

    from dataclasses import asdict as _asdict

    def _on_scenario_done(sr, done: int, total: int) -> None:
        job = _eval_jobs.get(job_id)
        if job and job.get("status") == "running":
            partial = job.get("partial", []) + [_asdict(sr)]
            job["partial"] = partial
            job["scenarios_done"] = done
            job["scenarios_total"] = total
            _persist_job(job_id, {"status": "partial", "partial": partial, "scenarios_done": done, "scenarios_total": total})

    async def _run() -> None:
        log.info("evaluate_started", job_id=job_id, strategy=settings.selection_strategy)
        t0 = time.monotonic()
        try:
            run = await asyncio.wait_for(
                run_evaluation(
                    provider=provider,
                    pool=pool,
                    eval_dir=eval_dir,
                    baselines_dir=eval_dir / "baselines",
                    run_date=date.today().isoformat(),
                    taxonomy_version=settings.taxonomy_version,
                    strategy=resolved_strategy,
                    on_scenario_done=_on_scenario_done,
                    only_groups=only_groups,
                ),
                timeout=float(settings.evaluate_timeout_s),
            )
            elapsed = round(time.monotonic() - t0)
            gm = {g: m for g, m in (asdict(run).get("group_metrics") or {}).items()}
            log.info(
                "evaluate_complete",
                job_id=job_id,
                elapsed_s=elapsed,
                pos_r5=round(gm.get("positive", {}).get("recall_at_k", 0), 3),
                neg_empty=round(gm.get("negative", {}).get("empty_rate", 0), 3),
                adv_r5=round(gm.get("adversarial", {}).get("recall_at_k", 0), 3),
                edge_r5=round(gm.get("edge", {}).get("recall_at_k", 0), 3),
            )
            result = asdict(run)
            _eval_jobs[job_id] = {"status": "done", "result": result}
            _persist_job(job_id, result)
        except asyncio.TimeoutError:
            log.error("evaluate_timeout", job_id=job_id, elapsed_s=round(time.monotonic() - t0))
            _eval_jobs[job_id] = {"status": "failed", "error": "evaluation_timeout"}
        except Exception as exc:
            log.error("evaluate_failed", job_id=job_id, error=str(exc), elapsed_s=round(time.monotonic() - t0))
            _eval_jobs[job_id] = {"status": "failed", "error": str(exc)}

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "running"}


@router.get("/evaluate/{job_id}")
async def evaluate_result(
    job_id: str,
    _: None = Depends(_verify_token),
) -> dict[str, Any]:
    """Poll for evaluation result. Returns {"status": "running"} while in progress,
    the full EvalRun JSON when done, or 404 if the job_id is unknown."""
    job = _eval_jobs.get(job_id) or _load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"})
    if job["status"] in ("running", "partial"):
        return {
            "status": job["status"],
            "scenarios_done": job.get("scenarios_done", 0),
            "scenarios_total": job.get("scenarios_total", 0),
            "partial": job.get("partial", []),
        }
    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail={"error": job["error"]})
    return job["result"]
