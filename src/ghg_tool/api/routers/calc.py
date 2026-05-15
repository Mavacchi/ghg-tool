"""Calc pipeline trigger and status endpoints — FR-34, Task 3B/C/D.

Endpoints:
    POST /api/v1/calc/run        — trigger a single-track run (admin).
    POST /api/v1/calc/run-dual   — trigger CSRD + EU ETS dual-track run (admin).
    GET  /api/v1/calc/runs/{cid} — poll run status from ops.calc_runs (all roles).

Design notes:
- Runs are spawned as FastAPI BackgroundTasks so the endpoint returns
  immediately with HTTP 202.
- ``run_calc_and_persist`` uses ``asyncio.run()`` internally, which means it
  must execute in a thread pool (via ``asyncio.get_event_loop().run_in_executor``
  or ``BackgroundTasks`` which runs in a threadpool for sync functions).
  Since BackgroundTasks calls sync functions in a thread, this works correctly.
- Audit log and structlog SIEM emit on every trigger.
- Correlation IDs for background runs are generated at request time and
  returned to the caller so they can poll the status endpoint.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_role

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/calc", tags=["calc"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

RegulatoryStream = Literal["CSRD_ESRS_E1", "EU_ETS_PHASE_IV"]


class CalcRunRequest(BaseModel):
    """Body for POST /api/v1/calc/run.

    Attributes:
        anno: Reporting year to compute (e.g. 2025).
        regulatory_stream: Target regulatory framework.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    anno: int = Field(ge=2000, le=2100, description="Reporting year")
    regulatory_stream: RegulatoryStream = Field(
        default="CSRD_ESRS_E1",
        description="Regulatory framework: CSRD_ESRS_E1 (AR6) or EU_ETS_PHASE_IV (AR5)",
    )


class CalcRunTriggerResponse(BaseModel):
    """202 Accepted response for a single-track trigger.

    Attributes:
        correlation_id: UUID to pass to GET /api/v1/calc/runs/{correlation_id}.
        message: Human-readable confirmation.
    """

    model_config = ConfigDict(frozen=True)

    correlation_id: uuid.UUID
    message: str


class CalcDualRunTriggerResponse(BaseModel):
    """202 Accepted response for a dual-track trigger.

    Attributes:
        csrd_correlation_id: UUID for the CSRD_ESRS_E1 / AR6 run.
        eu_ets_correlation_id: UUID for the EU_ETS_PHASE_IV / AR5 run.
        message: Human-readable confirmation.
    """

    model_config = ConfigDict(frozen=True)

    csrd_correlation_id: uuid.UUID
    eu_ets_correlation_id: uuid.UUID
    message: str


class CalcRunStatus(BaseModel):
    """Status row from ops.calc_runs.

    Attributes:
        correlation_id: Run UUID.
        anno: Reporting year.
        emissions_written: Total rows inserted in calc.emissions_consolidated.
        duration_ms: Wall-clock duration of the run in milliseconds.
        gwp_set: GWP set used.
        regulatory_stream: Regulatory framework used.
        started_at: UTC start timestamp.
        finished_at: UTC finish timestamp.
        created_by: Service account or user identifier.
    """

    model_config = ConfigDict(frozen=True)

    correlation_id: uuid.UUID
    anno: int
    emissions_written: int
    duration_ms: int
    gwp_set: str
    regulatory_stream: str
    started_at: str
    finished_at: str
    created_by: str


# ---------------------------------------------------------------------------
# GWP set resolution
# ---------------------------------------------------------------------------

_STREAM_TO_GWP: dict[str, str] = {
    "CSRD_ESRS_E1": "AR6",
    "EU_ETS_PHASE_IV": "AR5",
}


# ---------------------------------------------------------------------------
# Background job wrapper
# ---------------------------------------------------------------------------

def _background_run(
    *,
    anno: int,
    correlation_id: uuid.UUID,
    regulatory_stream: str,
    tenant_id: str,
    triggered_by: str,
) -> None:
    """Run ``run_calc_and_persist`` in the background thread.

    Builds its own engine pair (sync + async) per call so the background
    task is fully independent of the request-scoped session.

    Args:
        anno: Reporting year.
        correlation_id: Pre-generated UUID for this run.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.
        tenant_id: UUID string of the triggering tenant.
        triggered_by: Username / sub claim of the triggering user.
    """
    import os  # noqa: PLC0415
    import re  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: PLC0415

    from ghg_tool.application.services.calc_persistence import run_calc_and_persist  # noqa: PLC0415

    raw_dsn: str = os.getenv("DATABASE_URL") or os.getenv(
        "SQLALCHEMY_URL",
        "postgresql+asyncpg://ghg_app:changeme@localhost:5432/ghg_tool",
    ) or "postgresql+asyncpg://ghg_app:changeme@localhost:5432/ghg_tool"

    def _sync_dsn(raw: str) -> str:
        no_driver = re.sub(r"^postgresql\\+\\w+://", "postgresql://", raw)
        return no_driver.replace("postgresql://", "postgresql+psycopg://", 1)

    def _async_dsn(raw: str) -> str:
        no_driver = re.sub(r"^postgresql\\+\\w+://", "postgresql://", raw)
        return no_driver.replace("postgresql://", "postgresql+asyncpg://", 1)

    sync_engine = create_engine(
        _sync_dsn(raw_dsn), pool_pre_ping=True, pool_size=2, max_overflow=0
    )
    async_engine = create_async_engine(
        _async_dsn(raw_dsn), pool_pre_ping=True, pool_size=2, max_overflow=0
    )
    session_factory = async_sessionmaker(
        bind=async_engine, expire_on_commit=False, autoflush=False, autocommit=False
    )

    gwp_set = _STREAM_TO_GWP.get(regulatory_stream, "AR6")
    log = logger.bind(
        correlation_id=str(correlation_id),
        anno=anno,
        regulatory_stream=regulatory_stream,
        gwp_set=gwp_set,
        triggered_by=triggered_by,
    )
    log.info("background_calc_run_start")

    try:
        result = run_calc_and_persist(
            tenant_id=uuid.UUID(tenant_id),
            anno=anno,
            correlation_id=correlation_id,
            sync_engine=sync_engine,
            async_session_factory=session_factory,
            gwp_set=gwp_set,
            regulatory_stream=regulatory_stream,
            created_by=f"api:{triggered_by}",
        )
        # SIEM / audit emit
        log.info(
            "background_calc_run_complete",
            emissions_written=result.emissions_written,
            duration_ms=result.duration_ms,
            siem_event="CALC_RUN_COMPLETE",
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "background_calc_run_failed",
            error_type=type(exc).__name__,
            siem_event="CALC_RUN_FAILED",
        )
    finally:
        sync_engine.dispose()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_SELECT_CALC_RUN = text(
    """
    SELECT
        correlation_id, anno, emissions_written, duration_ms,
        gwp_set, regulatory_stream,
        started_at::text AS started_at,
        finished_at::text AS finished_at,
        created_by
    FROM ops.calc_runs
    WHERE correlation_id = :cid
    LIMIT 1
    """
)


@router.post(
    "/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CalcRunTriggerResponse,
    summary="Trigger a single-track calc run",
    description=(
        "Spawns a background calc run for the given anno and regulatory stream. "
        "Returns 202 with a correlation_id; poll GET /api/v1/calc/runs/{correlation_id} "
        "for completion status. Requires admin role."
    ),
    responses={
        202: {"description": "Run accepted and queued"},
        403: {"description": "Insufficient role"},
        422: {"description": "Validation error"},
    },
)
async def trigger_calc_run(
    body: CalcRunRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[CurrentUser, Depends(require_role("admin"))],
) -> CalcRunTriggerResponse:
    """Trigger a single-track calc run in the background.

    Args:
        body: Request with anno and regulatory_stream.
        background_tasks: FastAPI background task runner.
        user: Authenticated admin.

    Returns:
        202 response with the new correlation_id.
    """
    req_cid = get_correlation_id()
    run_cid = uuid.uuid4()
    log = logger.bind(
        request_correlation_id=req_cid,
        run_correlation_id=str(run_cid),
        anno=body.anno,
        regulatory_stream=body.regulatory_stream,
        user=user.sub,
    )
    log.info("calc_run_trigger_accepted", siem_event="CALC_TRIGGER")

    background_tasks.add_task(
        _background_run,
        anno=body.anno,
        correlation_id=run_cid,
        regulatory_stream=body.regulatory_stream,
        tenant_id=user.tenant_id,
        triggered_by=user.sub,
    )

    return CalcRunTriggerResponse(
        correlation_id=run_cid,
        message=f"Calc run queued for anno={body.anno} stream={body.regulatory_stream}",
    )


@router.post(
    "/run-dual",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CalcDualRunTriggerResponse,
    summary="Trigger FR-34 dual-track calc run (CSRD + EU ETS)",
    description=(
        "Spawns two background calc runs for the same anno: "
        "CSRD_ESRS_E1/AR6 and EU_ETS_PHASE_IV/AR5. "
        "Per Reg. UE 2018/2066 (MRR) + 2018/2067 (Verification), both runs "
        "MUST complete before any EU ETS filing. "
        "Returns two correlation_ids. Requires admin role."
    ),
    responses={
        202: {"description": "Both runs accepted and queued"},
        403: {"description": "Insufficient role"},
        422: {"description": "Validation error"},
    },
)
async def trigger_dual_calc_run(
    body: CalcRunRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[CurrentUser, Depends(require_role("admin"))],
) -> CalcDualRunTriggerResponse:
    """Trigger both CSRD and EU ETS calc runs for the same anno.

    FR-34: dual-track runs MUST happen before any EU ETS filing
    (Regolamento UE 2018/2066 Art. 12 MRR + 2018/2067 Verification).

    Args:
        body: Request with anno (regulatory_stream is ignored; both are run).
        background_tasks: FastAPI background task runner.
        user: Authenticated admin.

    Returns:
        202 response with two correlation_ids.
    """
    req_cid = get_correlation_id()
    csrd_cid = uuid.uuid4()
    eu_ets_cid = uuid.uuid4()
    log = logger.bind(
        request_correlation_id=req_cid,
        csrd_correlation_id=str(csrd_cid),
        eu_ets_correlation_id=str(eu_ets_cid),
        anno=body.anno,
        user=user.sub,
    )
    log.info("dual_calc_run_trigger_accepted", siem_event="DUAL_CALC_TRIGGER")

    background_tasks.add_task(
        _background_run,
        anno=body.anno,
        correlation_id=csrd_cid,
        regulatory_stream="CSRD_ESRS_E1",
        tenant_id=user.tenant_id,
        triggered_by=user.sub,
    )
    background_tasks.add_task(
        _background_run,
        anno=body.anno,
        correlation_id=eu_ets_cid,
        regulatory_stream="EU_ETS_PHASE_IV",
        tenant_id=user.tenant_id,
        triggered_by=user.sub,
    )

    return CalcDualRunTriggerResponse(
        csrd_correlation_id=csrd_cid,
        eu_ets_correlation_id=eu_ets_cid,
        message=(
            f"Dual-track calc queued for anno={body.anno}: "
            "CSRD_ESRS_E1/AR6 and EU_ETS_PHASE_IV/AR5"
        ),
    )


@router.get(
    "/runs/{correlation_id}",
    status_code=status.HTTP_200_OK,
    response_model=CalcRunStatus,
    summary="Poll calc run status",
    description=(
        "Returns the ops.calc_runs row for the given correlation_id. "
        "Returns 404 if the run has not started or does not exist. "
        "Accessible by all authenticated roles."
    ),
    responses={
        200: {"description": "Run status row"},
        404: {"description": "Correlation ID not found in ops.calc_runs"},
    },
)
async def get_calc_run_status(
    correlation_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_role("editor", "admin", "viewer"))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CalcRunStatus:
    """Return the ops.calc_runs status row for a correlation_id.

    Args:
        correlation_id: UUID of the calc run to look up.
        user: Authenticated user (any role).
        session: Async DB session with RLS GUCs pre-set.

    Returns:
        CalcRunStatus with run details.

    Raises:
        HTTPException 404: If the correlation_id is not found.
    """
    result = await session.execute(
        _SELECT_CALC_RUN, {"cid": str(correlation_id)}
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"No calc run found for correlation_id={correlation_id}",
            },
        )

    return CalcRunStatus(
        correlation_id=uuid.UUID(str(row["correlation_id"])),
        anno=int(row["anno"]),
        emissions_written=int(row["emissions_written"]),
        duration_ms=int(row["duration_ms"]),
        gwp_set=str(row["gwp_set"]),
        regulatory_stream=str(row["regulatory_stream"]),
        started_at=str(row["started_at"]),
        finished_at=str(row["finished_at"]),
        created_by=str(row["created_by"]),
    )
