import asyncio
from typing import Any
from uuid import uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import settings
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
) -> None:
    if credentials is None or credentials.credentials != settings.rag_api_key:
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
            retriever.retrieve(body, provider, pool),
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

    return RetrieveResponse(
        biases=[_to_bias_result(b) for b in biases],
        retrieved_chunks=meta.candidate_chunks,
        taxonomy_version=meta.taxonomy_version,
        embedding_model=meta.embedding_model,
        request_id=meta.retrieval_id,
    )


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    provider: EmbeddingProvider = request.app.state.provider
    pool: asyncpg.Pool | None = request.app.state.pool
    return {
        "status": "ok",
        "model_loaded": True,
        "embedding_model": provider.model_name,
        "embedding_dimension": settings.embedding_dimension,
        "provider_dimension": provider.dimension,
        "taxonomy_version": settings.taxonomy_version,
        "rows_indexed": 0,
        "last_indexed_at": None,
        "database_connected": pool is not None,
    }


@router.get("/stats")
async def stats(request: Request) -> dict[str, Any]:
    provider: EmbeddingProvider = request.app.state.provider
    return {
        "taxonomy_version": settings.taxonomy_version,
        "embedding_model": provider.model_name,
        "embedding_dimension": provider.dimension,
        "indexed_rows": 0,
        "chunk_count_by_type": {},
        "rows_per_taxonomy_version": {},
        "sources": {},
        "built_at": None,
        "git_sha": None,
    }
