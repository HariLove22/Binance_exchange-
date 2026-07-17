from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@router.get("/health/db")
async def health_db(
    response: Response, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Report database reachability.

    Returns 503 rather than letting the driver error escape as an unhandled 500. Two reasons,
    both learned the hard way:

    Starlette's ServerErrorMiddleware sits *outside* CORSMiddleware, so an unhandled exception
    produces a response with no CORS headers at all. The browser then blocks it, and the
    frontend cannot read the status — a real failure surfaces as an opaque network error. Every
    error a browser client needs to read has to be a returned response, not a raised exception.

    And a health check that throws is reporting the wrong thing anyway: "the database is down"
    is a known, expected state, not a crash.
    """
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "error",
            "database": "unreachable",
            "detail": type(exc).__name__,
        }
    return {"status": "ok", "database": "reachable"}
