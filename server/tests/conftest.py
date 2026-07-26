"""Shared test fixtures.

Tests run against a **real Postgres** — a throwaway database the suite creates and migrates
itself, not the dev database.

Real Postgres because the schema's whole job is enforcing invariants: CHECK constraints, partial
unique indexes, plpgsql triggers. None of that exists on SQLite or in a mock, so a suite that
mocked the database would pass while the constraints it claims to test were never created.

A *separate* database because the dev one carries seed data (a chain called ETHEREUM, an asset
called USDT) and those columns are globally unique — a test creating a realistic ETHEREUM row
would collide with the seeded one for a reason unrelated to what it tests.

The test DB name is forced via the environment **before** app config is imported, so both the app
and Alembic (which read `settings.database_url`) target it. Kamni's `alembic/env.py` reads the URL
straight from settings, so this is how we redirect it without touching that file.
"""

import os

# Must run before any `app.*` import, because config caches settings at import time.
os.environ["POSTGRES_DB"] = os.environ.get("POSTGRES_DB_TEST", "binance_test")

import asyncio  # noqa: E402
import sys  # noqa: E402
import warnings  # noqa: E402
from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from pathlib import Path  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402

SERVER_ROOT = Path(__file__).resolve().parent.parent


def _admin_url() -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/postgres"
    )


@pytest.fixture(scope="session")
def event_loop_policy():
    """Force a SelectorEventLoop on Windows — psycopg's async mode cannot run on ProactorEventLoop.

    Python 3.14 deprecates the policy system (removal in 3.16) in favour of `loop_factory`, but
    pytest-asyncio 1.2 still customises the loop through a policy, so a policy is what it wants.
    The deprecation is suppressed narrowly so any other deprecation still fails the suite.
    """
    if sys.platform != "win32":
        return asyncio.get_event_loop_policy()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*EventLoopPolicy.*")
        return asyncio.WindowsSelectorEventLoopPolicy()


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Create (if absent) and migrate the test database. Returns its URL."""
    admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": settings.postgres_db}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{settings.postgres_db}"'))
    admin.dispose()

    # Migrate with real migrations, not create_all — the triggers live in the migration, so
    # create_all would build a schema missing exactly the constraints these tests verify.
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    command.upgrade(config, "head")
    return settings.database_url


@pytest.fixture(scope="session")
def engine(migrated_db: str):
    return create_async_engine(migrated_db, echo=False)


@pytest.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """A session bound to a transaction that is always rolled back.

    The session joins an already-open outer transaction, so a test can `flush()` to make Postgres
    evaluate constraints and triggers without any of it surviving. Savepoints keep the failed-
    constraint tests from consuming the outer transaction.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )()
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
