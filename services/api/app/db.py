from contextlib import asynccontextmanager

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .settings import settings

pool = AsyncConnectionPool(
    conninfo=settings.database_url,
    min_size=1,
    max_size=10,
    kwargs={"row_factory": dict_row},
    open=False,
)


@asynccontextmanager
async def connection():
    async with pool.connection() as conn:
        await conn.execute("SELECT trace_finalize_temporal_commits()")
        await conn.commit()
        yield conn
        await conn.commit()
        await conn.execute("SELECT trace_finalize_temporal_commits()")
