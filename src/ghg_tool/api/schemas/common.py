"""Shared Pydantic v2 schemas: pagination, problem detail, token models."""

from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

# ---------------------------------------------------------------------------
# RFC 7807 Problem Detail
# ---------------------------------------------------------------------------


class ProblemDetail(BaseModel):
    """RFC 7807 Problem Detail response (application/problem+json).

    Every error response from the API uses this schema so that clients have a
    uniform, machine-readable error format.  Stack traces are never included.

    Attributes:
        type: A URI reference identifying the problem type.
        title: Short, human-readable summary.
        status: HTTP status code.
        detail: Human-readable explanation specific to this occurrence.
        correlation_id: Request correlation UUID for log tracing (FR-22).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str = Field(default="about:blank", description="URI identifying the problem type")
    title: str = Field(description="Short problem summary")
    status: int = Field(ge=100, le=599, description="HTTP status code")
    detail: str = Field(description="Human-readable error explanation")
    correlation_id: UUID | None = Field(default=None, description="Request correlation ID")


# ---------------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------------


class CursorPage(BaseModel, Generic[T]):
    """Cursor-based pagination envelope for list endpoints.

    Attributes:
        items: The page of results.
        next_cursor: Opaque cursor for fetching the next page (None if last page).
        total: Total matching record count (optional; may be omitted for perf).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[T]
    next_cursor: str | None = Field(default=None)
    total: int | None = Field(default=None)


# ---------------------------------------------------------------------------
# Common request / response fragments
# ---------------------------------------------------------------------------


class CorrelationIdMixin(BaseModel):
    """Mixin that adds ``correlation_id`` to a response model."""

    correlation_id: UUID = Field(description="Request-scoped correlation UUID (FR-22)")


class JobAccepted(BaseModel):
    """Async job accepted response (202 Accepted).

    Attributes:
        job_id: Opaque identifier for polling ``GET /reports/status/{job_id}``.
        correlation_id: Correlation UUID for log tracing.
    """

    model_config = ConfigDict(frozen=True)

    job_id: UUID = Field(description="Async job identifier")
    correlation_id: UUID = Field(description="Request correlation UUID")


# ---------------------------------------------------------------------------
# Annotated type aliases
# ---------------------------------------------------------------------------

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=512)]
ReasonCode = Annotated[str, Field(min_length=3, max_length=40)]

# Re-export for convenience
__all__ = [
    "CursorPage",
    "JobAccepted",
    "NonEmptyStr",
    "ProblemDetail",
    "ReasonCode",
]

# Satisfy Generic[T] at runtime for mypy; must be after class definition.
CursorPage.model_rebuild()

def _build_problem(
    status: int,
    title: str,
    detail: str,
    correlation_id: UUID | None = None,
    type_uri: str = "about:blank",
) -> dict[str, Any]:
    """Build a RFC 7807 problem dict for HTTPException detail.

    Args:
        status: HTTP status code.
        title: Short summary of the error.
        detail: Human-readable detail for this occurrence.
        correlation_id: Optional correlation UUID.
        type_uri: URI identifying the problem type.

    Returns:
        A dict suitable for use as the ``detail`` of ``HTTPException``.
    """
    payload: dict[str, Any] = {
        "type": type_uri,
        "title": title,
        "status": status,
        "detail": detail,
    }
    if correlation_id is not None:
        payload["correlation_id"] = str(correlation_id)
    return payload
