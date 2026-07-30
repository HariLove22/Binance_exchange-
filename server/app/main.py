import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import account, admin, auth, futures, health, kyc, margin, market, p2p, trade, wallet, ws
from app.core.config import settings
from app.services import trigger_monitor


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
    """Turn any database failure into a readable 503 instead of an unhandled 500.

    This matters for more than tidiness. Starlette's ServerErrorMiddleware sits *outside*
    CORSMiddleware, so an unhandled exception produces a 500 with no CORS headers at all —
    the browser blocks it and the frontend reports an opaque "can't reach the server"
    instead of the real cause. An app-level handler runs *inside* the middleware stack, so
    this response keeps its CORS headers and the client can actually read it.
    """
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": "Database unavailable — is Postgres running? (docker compose up -d)"
        },
    )


app.include_router(health.router, prefix=settings.api_v1_prefix)
app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(wallet.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router, prefix=settings.api_v1_prefix)
app.include_router(market.router, prefix=settings.api_v1_prefix)
app.include_router(trade.router, prefix=settings.api_v1_prefix)
app.include_router(p2p.router, prefix=settings.api_v1_prefix)
app.include_router(margin.router, prefix=settings.api_v1_prefix)
app.include_router(futures.router, prefix=settings.api_v1_prefix)
app.include_router(account.router, prefix=settings.api_v1_prefix)
app.include_router(kyc.router, prefix=settings.api_v1_prefix)
app.include_router(ws.router, prefix=settings.api_v1_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": f"{settings.api_v1_prefix}/docs"}
