import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.routes import admin, auth, health, market, trade, wallet, ws
from app.core.config import settings
from app.services import trigger_monitor

logger = logging.getLogger("app.errors")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The stop-order watcher: prices pending stops against the live feed and fires what crosses.
    monitor = asyncio.create_task(trigger_monitor.run())
    try:
        yield
    finally:
        monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url=f"{settings.api_v1_prefix}/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Turn a database failure into a readable response instead of an unhandled 500.

    An app-level handler is needed at all because Starlette's ServerErrorMiddleware sits
    *outside* CORSMiddleware: an unhandled 500 carries no CORS headers, so the browser blocks
    it and the frontend only sees an opaque "can't reach the server". Handling it here keeps
    the CORS headers and lets the client read the real status.

    Two very different failures were previously reported identically — that hid a schema/
    migration bug behind a "database down" message for far too long:

      • OperationalError  → couldn't connect (Postgres down, wrong host/port). A real 503.
      • everything else   → connected fine, but the query failed (missing column after a
                            merge, constraint violation, bad SQL). That is a 500, and the
                            hint is "run your migrations", not "start Postgres".

    The real exception is always logged so the actual cause is one glance away.
    """
    if isinstance(exc, OperationalError):
        logger.error("database unreachable: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Database unavailable — is Postgres running? (docker compose up -d)"},
        )

    logger.exception("database query failed")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Database query failed — the schema may be out of date. "
            "Run pending migrations: cd server && alembic upgrade head"
        },
    )


app.include_router(health.router, prefix=settings.api_v1_prefix)
app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(wallet.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router, prefix=settings.api_v1_prefix)
app.include_router(market.router, prefix=settings.api_v1_prefix)
app.include_router(trade.router, prefix=settings.api_v1_prefix)
app.include_router(ws.router, prefix=settings.api_v1_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": f"{settings.api_v1_prefix}/docs"}
