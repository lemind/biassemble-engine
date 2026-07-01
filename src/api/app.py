from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from fastapi import FastAPI

from src.api.routes import retrieve
from src.config import settings
from src.db.connection import init_pool_connection
from src.observability import configure_logging
from src.providers.sentence_transformer import SentenceTransformerProvider


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
            settings.database_url, statement_cache_size=0, init=init_pool_connection
        )
    except Exception:
        pool = None
    app.state.provider = provider
    app.state.pool = pool
    yield
    if pool is not None:
        await pool.close()


app = FastAPI(lifespan=lifespan)
app.include_router(retrieve.router)
