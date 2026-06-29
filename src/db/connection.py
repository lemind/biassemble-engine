import asyncpg
from fastapi import HTTPException, Request


async def get_pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool | None = request.app.state.pool
    if pool is None:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable"})
    return pool
