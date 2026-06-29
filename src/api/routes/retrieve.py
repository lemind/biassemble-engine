from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import settings
from src.providers.base import EmbeddingProvider
from src.schemas.request import RetrieveRequest
from src.schemas.response import RetrieveResponse

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def _verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if credentials is None or credentials.credentials != settings.rag_api_key:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})


@router.post("/retrieve-biases", response_model=RetrieveResponse)
async def retrieve_biases(
    body: RetrieveRequest,
    request: Request,
    _: None = Depends(_verify_token),
) -> RetrieveResponse:
    provider: EmbeddingProvider = request.app.state.provider
    return RetrieveResponse(
        biases=[],
        retrieved_chunks=0,
        taxonomy_version=settings.taxonomy_version,
        embedding_model=provider.model_name,
        request_id=body.request_id or str(uuid4()),
    )


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    provider: EmbeddingProvider = request.app.state.provider
    return {
        "status": "ok",
        "model_loaded": True,
        "embedding_model": provider.model_name,
        "embedding_dimension": settings.embedding_dimension,
        "provider_dimension": provider.dimension,
        "taxonomy_version": settings.taxonomy_version,
        "rows_indexed": 0,
        "last_indexed_at": None,
        "database_connected": True,
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
