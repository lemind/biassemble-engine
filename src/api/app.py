from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from fastapi import FastAPI

import structlog

from src.api.routes import retrieve
from src.config import settings
from src.db.queries import ROSTER_QUERY
from src.observability import configure_logging
from src.providers.sentence_transformer import SentenceTransformerProvider
from src.schemas.response import BiasResult
from src.selection.nli_union import NLIUnionStrategy
from src.selection.vector_only import VectorOnlyStrategy


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging(settings.log_level)
    provider = SentenceTransformerProvider(settings.embedding_model)
    if provider.dimension != settings.embedding_dimension:
        raise RuntimeError(
            f"Embedding dimension mismatch: "
            f"model={provider.dimension}, config={settings.embedding_dimension}"
        )
    try:
        # statement_cache_size=0 required: Supabase routes through pgbouncer in
        # transaction mode, which doesn't support asyncpg's prepared statements.
        pool: asyncpg.Pool | None = await asyncpg.create_pool(
            settings.database_url, statement_cache_size=0
        )
    except Exception:
        pool = None
    app.state.provider = provider
    app.state.pool = pool
    if settings.selection_strategy == "nli_union":
        structlog.get_logger().warning(
            "nli_union strategy selected — NLI module not yet wired (Phase 4); requests will raise NotImplementedError"
        )
        app.state.selection_strategy = NLIUnionStrategy(None, None)
    else:
        app.state.selection_strategy = VectorOnlyStrategy(provider, pool)

    roster: list[BiasResult] = []
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(ROSTER_QUERY, settings.taxonomy_version)
            roster = [
                BiasResult(
                    id=r["bias_id"],
                    name=r["name"] or r["bias_id"],
                    retrieval_score=0.0,
                    definition=r["definition"] or "",
                    examples="",
                    indicators="",
                    false_positives="",
                    related_biases="",
                )
                for r in rows
            ]
        except Exception:
            pass
    app.state.roster = roster

    yield
    if pool is not None:
        await pool.close()


app = FastAPI(lifespan=lifespan)
app.include_router(retrieve.router)
