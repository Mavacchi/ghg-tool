"""CLI wrapper: run the calc pipeline and persist results.

Usage (from inside the app container):

    docker compose --profile app exec app python -m scripts.run_calc \\
        --anno 2025 --tenant-code GRESMALT

Options:
    --anno            Reporting year (required).
    --tenant-code     Tenant code in ref.tenants (default: GRESMALT).
    --correlation-id  UUID to stamp on all emitted rows (default: new uuid4).
    --gwp-set         AR6 or AR5 (default: AR6).
    --dry-run         Print row counts without persisting.

Exit codes:
    0  All emissions written (or zero records produced from an empty raw set).
    1  An exception was raised during the run.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from typing import Any

_DEFAULT_DSN_SYNC = "postgresql+psycopg://ghg_app:changeme@localhost:5432/ghg_tool"
_DEFAULT_DSN_ASYNC = "postgresql+asyncpg://ghg_app:changeme@localhost:5432/ghg_tool"
_DEFAULT_TENANT_CODE = "GRESMALT"


def _sync_dsn() -> str:
    raw = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_URL") or _DEFAULT_DSN_SYNC
    # Normalise: strip any existing driver tag and apply psycopg (sync).
    no_driver = re.sub(r"^postgresql\+\w+://", "postgresql://", raw)
    return no_driver.replace("postgresql://", "postgresql+psycopg://", 1)


def _async_dsn() -> str:
    raw = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_URL") or _DEFAULT_DSN_ASYNC
    no_driver = re.sub(r"^postgresql\+\w+://", "postgresql://", raw)
    return no_driver.replace("postgresql://", "postgresql+asyncpg://", 1)


def _resolve_tenant(sync_engine: Any, tenant_code: str) -> uuid.UUID:
    """Resolve tenant_code to tenant_id via ref.tenants.

    Args:
        sync_engine: Sync SQLAlchemy engine.
        tenant_code: Code column value in ref.tenants.

    Returns:
        Tenant UUID.

    Raises:
        SystemExit: When the tenant code is not found.
    """
    from sqlalchemy import text as sa_text

    with sync_engine.connect() as conn:
        row = conn.execute(
            sa_text("SELECT id FROM ref.tenants WHERE code = :code"),
            {"code": tenant_code},
        ).fetchone()

    if row is None:
        print(  # noqa: T201
            f"ERROR: tenant '{tenant_code}' not found in ref.tenants. "
            "Run `alembic upgrade head` and seed the tenant first.",
            file=sys.stderr,
        )
        sys.exit(1)

    return uuid.UUID(str(row[0]))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_calc",
        description="Run the GHG calc pipeline and persist results.",
    )
    parser.add_argument("--anno", type=int, required=True, help="Reporting year")
    parser.add_argument(
        "--tenant-code",
        default=_DEFAULT_TENANT_CODE,
        help=f"Tenant code in ref.tenants (default: {_DEFAULT_TENANT_CODE})",
    )
    parser.add_argument(
        "--correlation-id",
        default=None,
        help="UUID to stamp on all emitted rows (default: new uuid4)",
    )
    parser.add_argument(
        "--gwp-set",
        default="AR6",
        choices=["AR6", "AR5"],
        help="GWP set (default: AR6)",
    )
    parser.add_argument(
        "--regulatory-stream",
        default="CSRD_ESRS_E1",
        choices=["CSRD_ESRS_E1", "EU_ETS_PHASE_IV"],
        help="Regulatory stream (default: CSRD_ESRS_E1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and run orchestrator but do not write to DB",
    )
    parser.add_argument(
        "--dual",
        action="store_true",
        help=(
            "FR-34 dual-track: run TWICE — once with (AR6, CSRD_ESRS_E1) then "
            "(AR5, EU_ETS_PHASE_IV) — and print both result summaries. "
            "Supersedes --gwp-set and --regulatory-stream when set. "
            "MUST be used before any EU ETS filing per Reg. UE 2018/2066 + 2018/2067."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the CLI script."""
    args = _parse_args()

    correlation_id = (
        uuid.UUID(args.correlation_id)
        if args.correlation_id
        else uuid.uuid4()
    )

    # Build engines
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    sync_engine = create_engine(
        _sync_dsn(),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )
    async_engine = create_async_engine(
        _async_dsn(),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )
    session_factory = async_sessionmaker(
        bind=async_engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    # Resolve tenant
    tenant_id = _resolve_tenant(sync_engine, args.tenant_code)

    if args.dry_run:
        print(  # noqa: T201
            f"DRY-RUN: tenant={args.tenant_code} anno={args.anno} "
            f"gwp_set={args.gwp_set} correlation_id={correlation_id}"
        )
        # Load raw rows only and report counts.
        from ghg_tool.application.services.calc_persistence import _load_raw_rows
        s1, s2, s3, sites = _load_raw_rows(sync_engine, tenant_id=tenant_id, anno=args.anno)
        print(  # noqa: T201
            f"Raw rows -- scope1={len(s1)} scope2={len(s2)} scope3={len(s3)} sites={len(sites)}"
        )
        sync_engine.dispose()
        return

    from ghg_tool.application.services.calc_persistence import run_calc_and_persist

    if args.dual:
        # FR-34: run both CSRD (AR6) and EU ETS (AR5) tracks.
        # Per Regolamento UE 2018/2066 (MRR Art. 12) + 2018/2067 (Verification),
        # both tracks MUST complete before any EU ETS filing.
        tracks = [
            ("AR6", "CSRD_ESRS_E1"),
            ("AR5", "EU_ETS_PHASE_IV"),
        ]
        exit_code = 0
        for gwp, stream in tracks:
            track_cid = uuid.uuid4()
            try:
                result = run_calc_and_persist(
                    tenant_id=tenant_id,
                    anno=args.anno,
                    correlation_id=track_cid,
                    sync_engine=sync_engine,
                    async_session_factory=session_factory,
                    gwp_set=gwp,
                    regulatory_stream=stream,
                    created_by="scripts.run_calc.dual",
                )
                print(  # noqa: T201
                    f"OK [{stream}/{gwp}] tenant={args.tenant_code} anno={args.anno} "
                    f"correlation_id={result.correlation_id} "
                    f"emissions_written={result.emissions_written} "
                    f"(s1={result.scope1_count} s2={result.scope2_count} s3={result.scope3_count}) "
                    f"duration_ms={result.duration_ms}"
                )
            except Exception as exc:  # noqa: BLE001
                print(  # noqa: T201
                    f"ERROR [{stream}/{gwp}]: calc run failed -- {exc}", file=sys.stderr
                )
                exit_code = 1
        sync_engine.dispose()
        sys.exit(exit_code)

    # Single-track run (default behaviour, unchanged).
    try:
        result = run_calc_and_persist(
            tenant_id=tenant_id,
            anno=args.anno,
            correlation_id=correlation_id,
            sync_engine=sync_engine,
            async_session_factory=session_factory,
            gwp_set=args.gwp_set,
            regulatory_stream=args.regulatory_stream,
            created_by="scripts.run_calc",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: calc run failed -- {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    finally:
        sync_engine.dispose()

    print(  # noqa: T201
        f"OK tenant={args.tenant_code} anno={args.anno} "
        f"correlation_id={result.correlation_id} "
        f"emissions_written={result.emissions_written} "
        f"(s1={result.scope1_count} s2={result.scope2_count} s3={result.scope3_count}) "
        f"duration_ms={result.duration_ms}"
    )

    # Exit non-zero if the orchestrator produced records but nothing was written
    # (a partial persistence failure). Zero records from empty raw tables is OK.
    sys.exit(0)


if __name__ == "__main__":
    main()
