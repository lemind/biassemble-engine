import asyncpg
from fastapi import HTTPException, Request


async def init_pool_connection(conn: asyncpg.Connection) -> None:
    """Register a text codec for pgvector's 'vector' type.

    asyncpg introspects unknown types by issuing extra DB round-trips. The
    SOCKS proxy drops those secondary connections, so any query containing
    '::vector' hangs forever. Registering the codec with the known OID
    tells asyncpg to treat 'vector' as text and skip introspection entirely.

    OID 18265 is the 'vector' type OID in this Supabase instance. To verify:
        SELECT oid FROM pg_type WHERE typname = 'vector';
    """
    await conn.set_type_codec(
        "vector",
        encoder=str,
        decoder=str,
        schema="public",
        format="text",
    )


async def get_pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool | None = request.app.state.pool
    if pool is None:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable"})
    return pool
