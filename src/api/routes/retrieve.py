import asyncio
import json
import os
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import settings
from src.db.queries import HEALTH_STATS, STATS_BY_CHUNK_TYPE, STATS_BY_SOURCE, STATS_BY_VERSION
from src.evaluation.evaluate import run_evaluation
from src.providers.base import EmbeddingProvider
from src.retrieval import retriever
from src.retrieval.retriever import IndexNotFoundError
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


@router.post("/evaluate")
async def evaluate(
    request: Request,
    _: None = Depends(_verify_token),
) -> StreamingResponse:
    """Run the full evaluation suite and stream the EvalRun JSON back.

    Sends newline heartbeats every 5 s while computing so the HF Space proxy
    does not close the idle connection (NLI takes ~90 s per scenario × 13
    scenarios = ~20 min total). The final line of the response body is the
    JSON result (or {"error": ...} on failure). Leading newlines are valid
    JSON whitespace so the caller can parse the body directly with json.loads.
    """
    provider: EmbeddingProvider = request.app.state.provider
    pool: asyncpg.Pool | None = request.app.state.pool
    log = structlog.get_logger()

    if pool is None:
        log.error("evaluate_aborted", reason="pool_is_none")
        raise HTTPException(status_code=503, detail={"error": "database_unavailable"})

    eval_dir = Path("evaluations")
    if not eval_dir.exists():
        log.error("evaluate_aborted", reason="eval_dir_not_found", path=str(eval_dir.resolve()))
        raise HTTPException(status_code=503, detail={"error": "eval_dir_not_found"})

    strategy = request.app.state.selection_strategy

    async def _stream():
        log.info("evaluate_started", strategy=settings.selection_strategy)
        t0 = time.monotonic()
        task = asyncio.create_task(run_evaluation(
            provider=provider,
            pool=pool,
            eval_dir=eval_dir,
            baselines_dir=eval_dir / "baselines",
            run_date=date.today().isoformat(),
            taxonomy_version=settings.taxonomy_version,
            strategy=strategy,
        ))
        deadline = t0 + float(settings.evaluate_timeout_s)

        try:
            while not task.done():
                if time.monotonic() > deadline:
                    log.error("evaluate_timeout", elapsed_s=round(time.monotonic() - t0))
                    # Status code is already committed to 200 by StreamingResponse;
                    # callers must inspect the body for {"error": ...}.
                    yield json.dumps({"error": "evaluation_timeout"}).encode()
                    return
                yield b"\n"
                await asyncio.sleep(5)

            elapsed = round(time.monotonic() - t0)
            try:
                run = task.result()
            except BaseException as exc:
                # BaseException catches CancelledError (not a subclass of Exception
                # since Python 3.8) in addition to regular evaluation failures.
                log.error("evaluate_failed", error=str(exc), elapsed_s=elapsed)
                yield json.dumps({"error": "evaluation_failed", "detail": str(exc)}).encode()
                return

            log.info("evaluate_complete", elapsed_s=elapsed)
            yield json.dumps(asdict(run)).encode()
        finally:
            # Ensure the background task is cancelled and fully awaited on any
            # exit path (timeout return, client disconnect, exception). Without
            # this the NLI thread keeps running after the response is closed.
            if not task.done():
                task.cancel()
            try:
                await task
            except BaseException:
                pass

    # X-Accel-Buffering: no disables nginx proxy buffering so heartbeat chunks
    # are flushed to the client immediately rather than held in the proxy buffer.
    return StreamingResponse(
        _stream(),
        media_type="application/json",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
