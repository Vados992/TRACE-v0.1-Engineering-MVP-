from contextlib import asynccontextmanager

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .settings import settings

pool = AsyncConnectionPool(
    conninfo=settings.database_url,
    min_size=settings.db_pool_min_size,
    max_size=settings.db_pool_max_size,
    timeout=settings.db_pool_timeout_seconds,
    kwargs={"row_factory": dict_row},
    open=False,
)


@asynccontextmanager
async def connection():
    async with pool.connection() as conn:
        await conn.execute("SELECT trace_finalize_temporal_commits()")
        await conn.commit()
        await conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(settings.db_statement_timeout_ms),),
        )
        yield conn
        await conn.commit()
        await conn.execute("SELECT trace_finalize_temporal_commits()")
