"""FastAPI dependency providers for the GHG Accounting API."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.db import get_db


@contextmanager
def handle_unique_violation(
    detail: str,
    correlation_id: str | None = None,
) -> Iterator[None]:
    """Context manager that translates a psycopg UniqueViolation to HTTP 409.

    Wraps a DB execute call so callers avoid string-matching on exception
    messages.  Uses SQLAlchemy's ``IntegrityError`` + psycopg
    ``UniqueViolation`` for accurate detection without false positives.

    Usage::

        async with handle_unique_violation("Tenant code already exists.", cid):
            await session.execute(insert_stmt)

    Args:
        detail: Human-readable detail for the 409 response body.
        correlation_id: Optional request correlation ID for the response body.

    Raises:
        HTTPException: 409 on UniqueViolation; re-raises other IntegrityErrors.
    """
    try:
        yield
    except IntegrityError as exc:
        try:
            from psycopg.errors import UniqueViolation  # noqa: PLC0415
            is_unique = isinstance(exc.orig, UniqueViolation)
        except ImportError:
            # Fallback for environments without psycopg (e.g. pure asyncpg).
            is_unique = "23505" in str(exc) or "unique" in str(exc).lower()
        if is_unique:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "about:blank",
                    "title": "Conflict",
                    "status": 409,
                    "detail": detail,
                    "correlation_id": correlation_id,
                },
            ) from exc
        raise


def get_factor_publish_service(
    session: AsyncSession = Depends(get_db),
) -> "FactorPublishService":  # noqa: F821  # type: ignore[name-defined]
    """Dependency: return a FactorPublishService wired to the current session.

    Import is deferred to avoid a circular import between api.__init__ (which
    imports api.main) and application.services.factor_publish_service (which
    imports api.schemas).

    Args:
        session: Authenticated async DB session injected by get_db.

    Returns:
        A ``FactorPublishService`` instance ready to orchestrate the two-eyes
        publish workflow.
    """
    # Deferred import breaks the circular dependency chain:
    # api.__init__ -> api.main -> api.routers -> api.dependencies.__init__
    # -> application.services.factor_publish_service -> api.schemas ->
    # api.__init__ (cycle).
    from ghg_tool.application.services.factor_publish_service import FactorPublishService  # noqa: PLC0415

    return FactorPublishService(session=session)


__all__ = ["get_factor_publish_service", "handle_unique_violation"]
