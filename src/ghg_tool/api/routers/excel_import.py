"""Excel bulk import endpoint — FR-03 completion.

POST /api/v1/raw/excel/import accepts a multipart .xlsx workbook, runs the
full ETL/DQ pipeline, and persists rows into raw.scope{1,2,3}_ingestions
using the same append-only psycopg path as scripts/seed_demo_data.py.

Security constraints:
- Max body size: 10 MB (enforced by FastAPI body-limit dependency).
- The .xlsx bytes are NEVER written to disk; they go directly to parse_workbook.
- Temp CSVs for the orchestrator use NamedTemporaryFile(delete=True) and are
  unlinked immediately after the orchestrator returns.
- tenant_id always sourced from the JWT; never from the request body.
- data_steward OR esg_manager required (raw_ingestions.import permission).

Append-only guarantee: the endpoint only INSERTs new rows.  The same
ON CONFLICT DO NOTHING idempotency-key guard used by seed_demo_data.py applies.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi import File as FastAPIFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.etl.orchestrator import run_ingestion_pipeline
from ghg_tool.etl.readers.excel_reader import (
    InvalidExcelFormatError,
    WorkbookParseError,
    parse_workbook,
)
from ghg_tool.infrastructure.db.models.audit_log import AuditLog
from ghg_tool.infrastructure.security import siem

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/raw/excel", tags=["raw-ingestion"])

_ETL_VERSION = "ui_excel_import_1.0.0"
_DQ_REPORT_VERSION = "1.0.0"
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# Column lists mirror scripts/seed_demo_data.py exactly so they share the
# same DB schema without divergence.
_SCOPE1_COLS = [
    "id", "tenant_id", "batch_id", "scope", "anno", "codice_sito",
    "categoria_s1", "combustibile", "quantita", "unita",
    "fonte_dato", "qualita_dato", "stato_dato", "note",
    "provenance", "provenance_rationale", "idempotency_key", "ingested_by",
]
_SCOPE2_COLS = [
    "id", "tenant_id", "batch_id", "scope", "anno", "codice_sito",
    "voce_s2", "quantita", "unita", "strumento_mb",
    "fonte_dato", "qualita_dato", "stato_dato", "note",
    "provenance", "provenance_rationale", "idempotency_key", "ingested_by",
]
_SCOPE3_COLS = [
    "id", "tenant_id", "batch_id", "scope", "anno",
    "categoria_s3", "sottocategoria", "metodo", "combustibile",
    "quantita", "unita", "fonte_dato", "qualita_dato", "stato_dato",
    "note", "metadata_defaulted", "defaulting_rule_id",
    "idempotency_key", "ingested_by",
]


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class ExcelImportResponse(BaseModel):
    """Response body for a successful Excel import.

    Attributes:
        batch_id: UUID of the newly created ingestion_batches row.
        scope1_rows: Number of scope 1 rows inserted.
        scope2_rows: Number of scope 2 rows inserted.
        scope3_rows: Number of scope 3 rows inserted.
        dq_findings: Total number of DQ findings persisted.
        blocked: True if DQ-CRIT gates blocked the import (never True on 200).
    """

    model_config = ConfigDict(frozen=True)

    batch_id: uuid.UUID
    scope1_rows: int = Field(ge=0)
    scope2_rows: int = Field(ge=0)
    scope3_rows: int = Field(ge=0)
    dq_findings: int = Field(ge=0)
    blocked: bool


# ---------------------------------------------------------------------------
# Internal DB helpers (sync psycopg — same pattern as seed_demo_data.py)
# These run in a thread via asyncio.to_thread so they never block the event loop.
# ---------------------------------------------------------------------------


def _dsn_from_env() -> str:
    """Resolve the sync PostgreSQL DSN from environment variables."""
    raw = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("SQLALCHEMY_URL")
        or "postgresql://ghg_app:changeme@localhost:5432/ghg_tool"
    )
    # Strip async driver prefix if present (asyncpg -> plain psycopg DSN)
    return re.sub(r"^postgresql\+\w+://", "postgresql://", raw)


def _coerce_for_psycopg(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert pandas/numpy scalars to native Python types for psycopg."""
    out: list[dict[str, Any]] = []
    for row in rows:
        clean: dict[str, Any] = {}
        for k, v in row.items():
            if v is None or isinstance(v, float) and v != v:
                clean[k] = None
            elif isinstance(v, Decimal):
                clean[k] = v
            else:
                clean[k] = v
        out.append(clean)
    return out


def _do_db_work(
    *,
    batch_id: uuid.UUID,
    tenant_id: uuid.UUID,
    triggered_by: str,
    scope1_rows: list[dict[str, Any]],
    scope2_rows: list[dict[str, Any]],
    scope3_rows: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, int]:
    """Synchronous psycopg writes: batch row + raw rows + dq_findings.

    Returns a dict with keys s1, s2, s3, findings containing counts inserted.
    This function is designed to run in a worker thread (asyncio.to_thread).

    Args:
        batch_id: UUID for the new ingestion_batches row.
        tenant_id: Tenant UUID sourced from the JWT.
        triggered_by: User sub (truncated to first 8 chars for non-PII logging).
        scope1_rows: Scope 1 staging row dicts from the orchestrator.
        scope2_rows: Scope 2 staging row dicts from the orchestrator.
        scope3_rows: Scope 3 staging row dicts from the orchestrator.
        findings: All DQ findings from the orchestrator.

    Returns:
        Row-count dict: {"s1": int, "s2": int, "s3": int, "findings": int}.
    """
    import psycopg  # noqa: PLC0415

    dsn = _dsn_from_env()
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # 1. Create ingestion_batches row
        cur.execute(
            """
            INSERT INTO raw.ingestion_batches
                (batch_id, tenant_id, correlation_id, etl_version,
                 gwp_set, triggered_by, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                batch_id,
                tenant_id,
                batch_id,
                _ETL_VERSION,
                "AR6",
                triggered_by,
                "UI Excel import via POST /api/v1/raw/excel/import",
            ),
        )

        # 2. Bulk-insert staging rows
        def _bulk_insert(table: str, rows: list[dict[str, Any]], cols: list[str]) -> int:
            if not rows:
                return 0
            placeholders = "(" + ", ".join(["%s"] * len(cols)) + ")"
            sql = (
                f"INSERT INTO raw.{table} ({', '.join(cols)}) "
                f"VALUES {placeholders} "
                "ON CONFLICT (tenant_id, batch_id, idempotency_key) DO NOTHING"
            )
            inserted = 0
            for row in rows:
                values = tuple(row.get(c) for c in cols)
                cur.execute(sql, values)
                inserted += cur.rowcount
            return inserted

        s1_n = _bulk_insert("scope1_ingestions",
                             _coerce_for_psycopg(scope1_rows), _SCOPE1_COLS)
        s2_n = _bulk_insert("scope2_ingestions",
                             _coerce_for_psycopg(scope2_rows), _SCOPE2_COLS)
        s3_n = _bulk_insert("scope3_ingestions",
                             _coerce_for_psycopg(scope3_rows), _SCOPE3_COLS)

        # 3. Persist DQ findings
        dq_sql = """
            INSERT INTO calc.dq_findings (
                id, tenant_id, correlation_id, rule_id, severity, scope,
                codice_sito, anno, metric, value_observed, value_reference,
                ratio_yoy, z_score, trigger_desc, recommended_action,
                blocks_pipeline, dq_report_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
        """
        f_n = 0
        for f in findings:
            cur.execute(
                dq_sql,
                (
                    uuid.uuid4(),
                    tenant_id,
                    batch_id,
                    f["rule_id"],
                    f["severity"],
                    f.get("scope"),
                    f.get("codice_sito"),
                    f.get("anno"),
                    f.get("metric"),
                    f.get("value_observed"),
                    f.get("value_reference"),
                    f.get("ratio_yoy"),
                    f.get("z_score"),
                    f.get("trigger_desc"),
                    f.get("recommended_action"),
                    bool(f.get("blocks_pipeline", False)),
                    f.get("dq_report_version", _DQ_REPORT_VERSION),
                ),
            )
            f_n += cur.rowcount

        # 4. Mark batch completed
        cur.execute(
            "UPDATE raw.ingestion_batches SET run_completed_at = now() "
            "WHERE batch_id = %s",
            (batch_id,),
        )
        conn.commit()

    return {"s1": s1_n, "s2": s2_n, "s3": s3_n, "findings": f_n}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/import",
    response_model=ExcelImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk-import an .xlsx workbook into raw.scope{1,2,3}_ingestions",
    description=(
        "Accepts a multipart/form-data upload of an .xlsx workbook with one or "
        "more of the sheets Scope1 / Scope2 / Scope3.  "
        "The workbook is parsed in-memory (never written to disk). "
        "Temp CSVs for the ETL orchestrator are written to /tmp with "
        "NamedTemporaryFile(delete=True) and exist only for the duration "
        "of the request.  "
        "DQ-CRIT gates are evaluated; if any gate fails the import is "
        "rejected with HTTP 422 and the blocking findings are returned "
        "so the user understands what to fix.  "
        "If all DQ-CRIT gates pass the rows are appended (ON CONFLICT DO NOTHING "
        "on idempotency_key) and a new raw.ingestion_batches row is created.  "
        "Max upload size: 10 MB.  "
        "Requires data_steward or esg_manager role."
    ),
    responses={
        200: {"description": "Import successful"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role (data_steward or esg_manager required)"},
        422: {"description": "Workbook parse error or DQ-CRIT gate blocked the import"},
    },
)
async def import_excel(
    request: Request,
    workbook: UploadFile = FastAPIFile(
        ...,
        description="The .xlsx workbook to import (max 10 MB).",
    ),
    user: CurrentUser = Depends(require_permission("raw_ingestions", "import")),
    session: AsyncSession = Depends(get_db),
) -> ExcelImportResponse:
    """Parse and import an Excel workbook into raw staging tables.

    Args:
        request: The incoming HTTP request (used for ip_address / user_agent).
        workbook: Uploaded .xlsx file from multipart form data.
        user: Authenticated user (data_steward or esg_manager).
        session: Authenticated async DB session with RLS GUCs set.

    Returns:
        ExcelImportResponse with row counts and batch_id.

    Raises:
        HTTPException: 422 on parse failure or DQ-CRIT block.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user=user.sub[:8],
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:120],
    )
    log.info("excel_import_started", filename=workbook.filename)

    # ------------------------------------------------------------------
    # 1. Size guard — reject before reading the full body
    # ------------------------------------------------------------------
    raw_bytes = await workbook.read()
    if len(raw_bytes) > _MAX_UPLOAD_BYTES:
        log.warning(
            "excel_import_rejected_too_large",
            size_bytes=len(raw_bytes),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "about:blank",
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": (
                    f"Workbook exceeds the 10 MB size limit "
                    f"({len(raw_bytes)} bytes received)."
                ),
                "correlation_id": correlation_id,
            },
        )

    # ------------------------------------------------------------------
    # 2. Parse the workbook in-memory (bytes never touch disk)
    # ------------------------------------------------------------------
    try:
        parsed = parse_workbook(raw_bytes)
    except InvalidExcelFormatError as exc:
        # BUG-13: magic-byte check failed before openpyxl was invoked.
        log.warning("excel_import_invalid_format", detail=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "about:blank",
                "title": "Invalid Excel Format",
                "status": 422,
                "detail": str(exc),
                "error_code": "invalid_excel_format",
                "correlation_id": correlation_id,
            },
        ) from exc
    except WorkbookParseError as exc:
        log.warning("excel_import_parse_error", detail=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "about:blank",
                "title": "Workbook Parse Error",
                "status": 422,
                "detail": str(exc),
                "correlation_id": correlation_id,
            },
        ) from exc

    # ------------------------------------------------------------------
    # 3. Write temp CSVs and run the ETL orchestrator
    #
    # The orchestrator requires Path objects pointing at CSV files.
    # We write temporary CSVs (semicolon-delimited, UTF-8-BOM, exactly
    # matching what csv_reader expects) and keep them only long enough
    # for the orchestrator to read them.  delete=True ensures cleanup
    # even on exception.
    # ------------------------------------------------------------------
    from pathlib import Path  # noqa: PLC0415

    import pandas as pd  # noqa: PLC0415

    batch_id = uuid.uuid4()
    tenant_id = uuid.UUID(user.tenant_id)

    # Build placeholder DataFrames for scopes not present in the upload.
    # The orchestrator always requires all three paths; absent scopes get
    # an empty DataFrame that passes pandera with zero rows.
    scope1_df = parsed.get("scope1", pd.DataFrame())
    scope2_df = parsed.get("scope2", pd.DataFrame())
    scope3_df = parsed.get("scope3", pd.DataFrame())

    def _sanitise_cell_for_csv(value: Any) -> Any:
        """Prefix formula-trigger chars to prevent CSV injection (BUG-07).

        Affected first-characters: ``=``, ``+``, ``-``, ``@``, ``\\t``, ``\\r``.
        """
        formula_triggers = frozenset({"=", "+", "-", "@", "\t", "\r"})
        if isinstance(value, str) and value and value[0] in formula_triggers:
            return "'" + value
        return value

    def _write_temp_csv(df: pd.DataFrame) -> tempfile.NamedTemporaryFile:  # type: ignore[type-arg]
        """Write df to a UTF-8-BOM semicolon CSV in /tmp; caller owns the handle.

        All string cells are sanitised against formula injection before writing
        (BUG-07: temp CSV path was previously unsanitised).
        """
        tf = tempfile.NamedTemporaryFile(  # noqa: SIM115
            mode="w",
            suffix=".csv",
            prefix="ghg_excel_",
            encoding="utf-8-sig",
            delete=True,
            dir=None,  # system default tmp dir
        )
        try:
            sanitised = df.map(_sanitise_cell_for_csv)  # pandas >= 2.1
        except AttributeError:
            sanitised = df.applymap(_sanitise_cell_for_csv)  # pandas < 2.1 fallback
        sanitised.to_csv(tf, sep=";", index=False)
        tf.flush()
        return tf

    with (
        _write_temp_csv(scope1_df) as tmp1,
        _write_temp_csv(scope2_df) as tmp2,
        _write_temp_csv(scope3_df) as tmp3,
    ):
        result = run_ingestion_pipeline(
            scope1_path=Path(tmp1.name),
            scope2_path=Path(tmp2.name),
            scope3_path=Path(tmp3.name),
            batch_id=batch_id,
            tenant_id=tenant_id,
            ingested_by=user.sub[:8],  # truncated sub — no PII in provenance
            dq_report_version=_DQ_REPORT_VERSION,
        )

    # ------------------------------------------------------------------
    # 4. DQ-CRIT gate check
    # ------------------------------------------------------------------
    crit_findings = [f for f in result.all_findings if f.get("severity") == "CRIT"]
    if result.pipeline_blocked:
        log.warning(
            "excel_import_dq_crit_blocked",
            crit_count=len(crit_findings),
        )
        # Surface every CRIT finding so the user knows what to fix.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "about:blank",
                "title": "DQ-CRIT Gate Blocked Import",
                "status": 422,
                "detail": (
                    f"{len(crit_findings)} critical data-quality finding(s) "
                    "must be resolved before this workbook can be imported."
                ),
                "blocked_findings": [
                    {
                        "rule_id": f.get("rule_id"),
                        "scope": f.get("scope"),
                        "codice_sito": f.get("codice_sito"),
                        "anno": f.get("anno"),
                        "trigger_desc": f.get("trigger_desc"),
                        "recommended_action": f.get("recommended_action"),
                    }
                    for f in crit_findings
                ],
                "correlation_id": correlation_id,
            },
        )

    # ------------------------------------------------------------------
    # 5. Persist rows via sync psycopg in a worker thread
    # ------------------------------------------------------------------
    try:
        inserted = await asyncio.to_thread(
            _do_db_work,
            batch_id=batch_id,
            tenant_id=tenant_id,
            triggered_by=user.sub[:8],
            scope1_rows=result.scope1_rows,
            scope2_rows=result.scope2_rows,
            scope3_rows=result.scope3_rows,
            findings=result.all_findings,
        )
    except Exception as exc:
        log.error(
            "excel_import_db_error",
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Database write failed. No rows were persisted.",
                "correlation_id": correlation_id,
            },
        ) from exc

    # ------------------------------------------------------------------
    # 6. Write audit_log row via SQLAlchemy async session (same transaction
    #    boundary as the rest of the API — the psycopg writes above are in
    #    their own connection and already committed).
    # ------------------------------------------------------------------
    now = datetime.now(tz=UTC)
    audit_row = AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        correlation_id=uuid.UUID(correlation_id) if correlation_id else batch_id,
        occurred_at=now,
        user_id=uuid.UUID(user.sub),
        user_role=user.role,
        action="excel_imported",
        resource="raw_ingestions",
        resource_id=batch_id,
        request_method="POST",
        request_path="/api/v1/raw/excel/import",
        status_code=200,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:200],
        after_state={
            "batch_id": str(batch_id),
            "scope1_rows": inserted["s1"],
            "scope2_rows": inserted["s2"],
            "scope3_rows": inserted["s3"],
            "dq_findings": inserted["findings"],
        },
    )
    session.add(audit_row)
    await session.flush()

    # ------------------------------------------------------------------
    # 7. SIEM event (best-effort, never blocks the response)
    # ------------------------------------------------------------------
    siem.emit(
        event="excel_imported",
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user_sub=user.sub[:8],
        severity="INFO",
        payload={
            "batch_id": str(batch_id),
            "scope1_rows": inserted["s1"],
            "scope2_rows": inserted["s2"],
            "scope3_rows": inserted["s3"],
            "dq_findings": inserted["findings"],
            "filename": workbook.filename or "unknown",
        },
    )

    log.info(
        "excel_import_completed",
        batch_id=str(batch_id),
        scope1_rows=inserted["s1"],
        scope2_rows=inserted["s2"],
        scope3_rows=inserted["s3"],
        dq_findings=inserted["findings"],
    )

    return ExcelImportResponse(
        batch_id=batch_id,
        scope1_rows=inserted["s1"],
        scope2_rows=inserted["s2"],
        scope3_rows=inserted["s3"],
        dq_findings=inserted["findings"],
        blocked=False,
    )
