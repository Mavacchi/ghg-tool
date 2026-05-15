"""Optional in-process APScheduler integration for automatic calc runs.

Activation:
    Set ``GHG_CALC_SCHEDULE_CRON`` to a cron expression (e.g. ``"0 2 * * *"``).
    When the variable is unset the scheduler is never started, preserving the
    existing manual-only deployment model.

Multi-worker safety:
    When multiple gunicorn workers are running, each worker will attempt to
    start its own scheduler instance and call ``run_calc_and_persist`` on the
    same cron tick.  ``run_calc_and_persist`` is idempotent on the
    ``ops.calc_runs.correlation_id`` PK (the caller must supply a stable UUID
    derived from anno + regulatory_stream), so duplicate runs produce
    harmless conflicts that are caught and logged rather than silently
    double-inserting data.

    Future hardening (tracked in roadmap): set ``GHG_SCHEDULER_LEADER_ONLY=true``
    to restrict scheduling to the lowest-PID worker in the process group.
    For now the safer choice is idempotent runs rather than a fragile
    leader-election mechanism in Python.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

_CRON_ENV_VAR = "GHG_CALC_SCHEDULE_CRON"


def _deterministic_correlation_id(anno: int, regulatory_stream: str) -> uuid.UUID:
    """Return a stable UUID for (anno, regulatory_stream, utc_date).

    Using a date-scoped UUID means that if two workers fire within the same
    calendar day, they generate the same correlation_id and the second INSERT
    into ops.calc_runs hits the PK unique constraint (idempotency).

    Args:
        anno: Reporting year.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.

    Returns:
        A deterministic UUID5 for today's scheduled run.
    """
    today = datetime.now(UTC).date().isoformat()
    name = f"{anno}:{regulatory_stream}:{today}"
    return uuid.uuid5(uuid.NAMESPACE_OID, name)


def _run_scheduled_calc(
    *,
    anno: int,
    regulatory_stream: str,
    gwp_set: str,
) -> None:
    """Scheduled job body — builds engines and calls ``run_calc_and_persist``.

    Designed to be called from APScheduler; all imports are local so the
    scheduler module can be imported without the full app initialisation.

    Args:
        anno: Reporting year to calculate.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.
        gwp_set: 'AR6' or 'AR5'.
    """
    import re  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: PLC0415

    from ghg_tool.application.services.calc_persistence import run_calc_and_persist  # noqa: PLC0415

    _DEFAULT_TENANT_CODE = os.getenv("GHG_SCHEDULER_TENANT_CODE", "GRESMALT")  # noqa: N806
    _RAW_DSN: str = (  # noqa: N806
        os.getenv("DATABASE_URL")
        or os.getenv("SQLALCHEMY_URL")
        or "postgresql+asyncpg://ghg_app:changeme@localhost:5432/ghg_tool"
    )

    def _sync_dsn(raw: str) -> str:
        no_driver = re.sub(r"^postgresql\+\w+://", "postgresql://", raw)
        return no_driver.replace("postgresql://", "postgresql+psycopg://", 1)

    def _async_dsn(raw: str) -> str:
        no_driver = re.sub(r"^postgresql\+\w+://", "postgresql://", raw)
        return no_driver.replace("postgresql://", "postgresql+asyncpg://", 1)

    from sqlalchemy import text as sa_text  # noqa: PLC0415
    sync_engine = create_engine(
        _sync_dsn(_RAW_DSN), pool_pre_ping=True, pool_size=2, max_overflow=0
    )
    async_engine = create_async_engine(
        _async_dsn(_RAW_DSN), pool_pre_ping=True, pool_size=2, max_overflow=0
    )
    session_factory = async_sessionmaker(
        bind=async_engine, expire_on_commit=False, autoflush=False, autocommit=False
    )

    # Resolve tenant_id
    with sync_engine.connect() as conn:
        row = conn.execute(
            sa_text("SELECT id FROM ref.tenants WHERE code = :code"),
            {"code": _DEFAULT_TENANT_CODE},
        ).fetchone()
    if row is None:
        logger.error(
            "scheduler_tenant_not_found",
            tenant_code=_DEFAULT_TENANT_CODE,
        )
        sync_engine.dispose()
        return

    import uuid as _uuid  # noqa: PLC0415
    tenant_id = _uuid.UUID(str(row[0]))
    correlation_id = _deterministic_correlation_id(anno, regulatory_stream)

    log = logger.bind(
        anno=anno,
        regulatory_stream=regulatory_stream,
        gwp_set=gwp_set,
        correlation_id=str(correlation_id),
    )
    log.info("scheduler_job_start")

    try:
        result = run_calc_and_persist(
            tenant_id=tenant_id,
            anno=anno,
            correlation_id=correlation_id,
            sync_engine=sync_engine,
            async_session_factory=session_factory,
            gwp_set=gwp_set,
            regulatory_stream=regulatory_stream,
            created_by="calc_scheduler",
        )
        log.info(
            "scheduler_job_complete",
            emissions_written=result.emissions_written,
            duration_ms=result.duration_ms,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("scheduler_job_failed", error_type=type(exc).__name__)
    finally:
        sync_engine.dispose()


def start_scheduler(*, anno: int) -> object | None:
    """Start an APScheduler BackgroundScheduler if ``GHG_CALC_SCHEDULE_CRON`` is set.

    Called from the FastAPI lifespan startup hook.  Returns the scheduler
    instance (so the caller can shut it down on exit) or ``None`` when the
    env var is unset.

    Args:
        anno: Reporting year to pass to each scheduled run.

    Returns:
        Running ``BackgroundScheduler`` instance, or ``None``.
    """
    cron_expr = os.getenv(_CRON_ENV_VAR, "").strip()
    if not cron_expr:
        logger.info("calc_scheduler_disabled", reason="GHG_CALC_SCHEDULE_CRON_unset")
        return None

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # noqa: PLC0415
        from apscheduler.triggers.cron import CronTrigger  # noqa: PLC0415
    except ImportError:
        logger.error(
            "calc_scheduler_import_error",
            detail="apscheduler not installed; install apscheduler>=3.10 to use scheduling",
        )
        return None

    # Parse the cron expression: "min hour dom mon dow"
    parts = cron_expr.split()
    if len(parts) != 5:  # noqa: PLR2004
        logger.error(
            "calc_scheduler_invalid_cron",
            cron_expr=cron_expr,
            detail="Expected 5-field cron expression (min hour dom mon dow)",
        )
        return None

    minute, hour, day, month, day_of_week = parts

    scheduler = BackgroundScheduler()

    # CSRD track: AR6 / CSRD_ESRS_E1
    scheduler.add_job(
        _run_scheduled_calc,
        CronTrigger(
            minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week
        ),
        kwargs={"anno": anno, "regulatory_stream": "CSRD_ESRS_E1", "gwp_set": "AR6"},
        id="calc_csrd",
        replace_existing=True,
        max_instances=1,
    )

    # EU ETS track: AR5 / EU_ETS_PHASE_IV (FR-34 dual-track)
    scheduler.add_job(
        _run_scheduled_calc,
        CronTrigger(
            minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week
        ),
        kwargs={"anno": anno, "regulatory_stream": "EU_ETS_PHASE_IV", "gwp_set": "AR5"},
        id="calc_eu_ets",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info("calc_scheduler_started", cron_expr=cron_expr, anno=anno)
    return scheduler
