from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    # Fail fast when Postgres is unreachable. Without connect_timeout, psycopg retries the
    # connection until the OS gives up, so a request against a dead database hangs for minutes
    # instead of erroring. A health check that hangs is worse than one that fails: a load
    # balancer holds the connection open rather than marking the instance unhealthy.
    connect_args={"connect_timeout": settings.db_connect_timeout},
    # Same reasoning for waiting on a pool slot.
    pool_timeout=settings.db_pool_timeout,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
