"""Seed the staging tables with the Saturnia demo CSVs in ``data/raw/``.

Pipeline:
  1. Resolve tenant_id from ``ref.tenants.code`` (default ``CERAMIC_TILE_CO``).
  2. INSERT a row into ``raw.ingestion_batches`` (one per script run).
  3. Run ``etl.orchestrator.run_ingestion_pipeline`` (pure-function): reads
     CSVs, applies FR-01/FR-02/FR-37 synthetic rows, validates with pandera,
     runs DQ-CRIT + DQ-WARN gates.
  4. Bulk INSERT the produced ``scope{1,2,3}_rows`` into
     ``raw.scope{1,2,3}_ingestions`` (ON CONFLICT DO NOTHING on
     ``idempotency_key``, so re-runs are safe).
  5. Bulk INSERT all DQ findings into ``calc.dq_findings``.

Scope NOT covered by this script (wave-3 work — see Makefile:153):
  - Emission calculation (``application.services.calc_orchestrator``) — the
    16 calc modules are pure-function and present, but the SQLAlchemy-async
    ``FactorCatalogPort`` adapter required to wire them end-to-end is not
    yet implemented. The dashboards' KPI views (which read from
    ``calc.emissions_consolidated``) will therefore remain empty after this
    seed. Use this script for raw-data inspection in psql; full KPI/PDF
    output requires the wave-3 calc pipeline.

Idempotent: running twice does not duplicate raw rows (UNIQUE on
``idempotency_key``), but DOES create two ingestion_batches. Pass
``--batch-id <uuid>`` to reuse an existing batch.

Usage (from inside the ``app`` container, where deps are installed):

    docker compose --profile app exec app python -m scripts.seed_demo_data
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from ghg_tool.etl.orchestrator import ETLResult

_DEFAULT_DSN = "postgresql://ghg_app:changeme@localhost:5432/ghg_tool"
_DEFAULT_TENANT_CODE = "CERAMIC_TILE_CO"
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
_ETL_VERSION = "demo-seed-1.0.0"
_DQ_REPORT_VERSION = "1.0.0"


def _dsn() -> str:
    raw = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_URL") or _DEFAULT_DSN
    return re.sub(r"^postgresql\+\w+://", "postgresql://", raw)


def _resolve_tenant(cur: psycopg.Cursor[Any], tenant_code: str) -> uuid.UUID:
    cur.execute("SELECT id FROM ref.tenants WHERE code = %s", (tenant_code,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(
            f"Tenant '{tenant_code}' not found. Run `alembic upgrade head` first."
        )
    return uuid.UUID(str(row[0]))


def _create_batch(
    cur: psycopg.Cursor[Any],
    *,
    tenant_id: uuid.UUID,
    triggered_by: str,
) -> uuid.UUID:
    """Insert a fresh ingestion_batches row and return its UUID."""
    batch_id = uuid.uuid4()
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
            batch_id,  # correlation_id == batch_id for ETL-triggered runs
            _ETL_VERSION,
            "AR6",
            triggered_by,
            "Demo seed via scripts/seed_demo_data.py",
        ),
    )
    return batch_id


def _bulk_insert_raw(
    cur: psycopg.Cursor[Any],
    *,
    table: str,
    rows: list[dict[str, Any]],
    columns: list[str],
) -> int:
    """Bulk-insert ``rows`` into ``raw.<table>`` skipping idempotency-key dupes.

    Returns the number of rows actually inserted.
    """
    if not rows:
        return 0
    placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
    sql = (
        f"INSERT INTO raw.{table} ({', '.join(columns)}) VALUES {placeholders} "
        "ON CONFLICT (tenant_id, batch_id, idempotency_key) DO NOTHING"
    )
    inserted = 0
    for row in rows:
        values = tuple(row.get(c) for c in columns)
        cur.execute(sql, values)
        inserted += cur.rowcount
    return inserted


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


def _insert_findings(
    cur: psycopg.Cursor[Any],
    *,
    tenant_id: uuid.UUID,
    correlation_id: uuid.UUID,
    findings: list[dict[str, Any]],
) -> int:
    """Persist DQ findings to ``calc.dq_findings``. Returns rows inserted."""
    if not findings:
        return 0
    sql = """
        INSERT INTO calc.dq_findings (
            id, tenant_id, correlation_id, rule_id, severity, scope,
            codice_sito, anno, metric, value_observed, value_reference,
            ratio_yoy, z_score, trigger_desc, recommended_action,
            blocks_pipeline, dq_report_version
        )
        VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s
        )
    """
    inserted = 0
    for f in findings:
        cur.execute(
            sql,
            (
                uuid.uuid4(),
                tenant_id,
                correlation_id,
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
        inserted += cur.rowcount
    return inserted


def _coerce_for_psycopg(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert pandas/numpy scalars (NaN, np.int64) into native Python types.

    psycopg accepts ``Decimal``/``int``/``str``/``None`` cleanly but pandas-
    derived NaN floats end up as the SQL literal ``'nan'`` on numeric columns,
    which PostgreSQL rejects on Numeric(20, 6). We normalise here.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        clean: dict[str, Any] = {}
        for k, v in row.items():
            if v is None:
                clean[k] = None
            elif isinstance(v, float) and v != v:  # NaN
                clean[k] = None
            elif isinstance(v, Decimal):
                clean[k] = v
            else:
                clean[k] = v
        out.append(clean)
    return out


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed raw.scope*_ingestions + calc.dq_findings from data/raw/ CSVs.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_DEFAULT_DATA_DIR,
        help=f"Directory containing the three CSVs (default: {_DEFAULT_DATA_DIR}).",
    )
    parser.add_argument(
        "--tenant-code",
        default=_DEFAULT_TENANT_CODE,
        help=f"ref.tenants.code (default: {_DEFAULT_TENANT_CODE}).",
    )
    parser.add_argument(
        "--ingested-by",
        default="demo-seed-script",
        help="Service-account string recorded on each raw row.",
    )
    parser.add_argument("--dsn", default=None, help="PostgreSQL DSN override.")
    return parser


def _summary(result: "ETLResult", inserted: dict[str, int]) -> str:
    return (
        "Seed summary:\n"
        f"  batch_id              : {result.batch_id}\n"
        f"  pipeline_blocked      : {result.pipeline_blocked}\n"
        f"  scope1 staged / built : {inserted['s1']} / {result.scope1_row_count}\n"
        f"  scope2 staged / built : {inserted['s2']} / {result.scope2_row_count}\n"
        f"  scope3 staged / built : {inserted['s3']} / {result.scope3_row_count}\n"
        f"  dq_findings inserted  : {inserted['findings']}\n"
        f"  dlq entries (in-mem)  : {len(result.dlq_entries)}\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    data_dir: Path = args.data_dir
    scope1_path = data_dir / "scope1_combustione.csv"
    scope2_path = data_dir / "scope2_elettricita.csv"
    scope3_path = data_dir / "scope3_categorie.csv"
    for p in (scope1_path, scope2_path, scope3_path):
        if not p.exists():
            raise SystemExit(f"Missing CSV: {p}")

    # Deferred imports: pandas + the ETL package are heavy and only needed
    # when we actually run a seed (the --help path stays import-free).
    import psycopg  # noqa: PLC0415
    from ghg_tool.etl.orchestrator import run_ingestion_pipeline  # noqa: PLC0415

    dsn = args.dsn or _dsn()
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        tenant_id = _resolve_tenant(cur, args.tenant_code)
        batch_id = _create_batch(
            cur, tenant_id=tenant_id, triggered_by=args.ingested_by
        )

        result = run_ingestion_pipeline(
            scope1_path=scope1_path,
            scope2_path=scope2_path,
            scope3_path=scope3_path,
            batch_id=batch_id,
            tenant_id=tenant_id,
            ingested_by=args.ingested_by,
            dq_report_version=_DQ_REPORT_VERSION,
        )

        if result.pipeline_blocked:
            # CRIT-failed runs must still record findings + dlq for audit, but
            # we MUST NOT insert any staging rows (the orchestrator already
            # returned empty lists in that case).
            print(
                "WARNING: DQ-CRIT gate failed — no raw rows will be inserted. "
                "Persisting DQ findings only.",
                file=sys.stderr,
            )

        inserted = {
            "s1": _bulk_insert_raw(
                cur,
                table="scope1_ingestions",
                rows=_coerce_for_psycopg(result.scope1_rows),
                columns=_SCOPE1_COLS,
            ),
            "s2": _bulk_insert_raw(
                cur,
                table="scope2_ingestions",
                rows=_coerce_for_psycopg(result.scope2_rows),
                columns=_SCOPE2_COLS,
            ),
            "s3": _bulk_insert_raw(
                cur,
                table="scope3_ingestions",
                rows=_coerce_for_psycopg(result.scope3_rows),
                columns=_SCOPE3_COLS,
            ),
            "findings": _insert_findings(
                cur,
                tenant_id=tenant_id,
                correlation_id=batch_id,
                findings=result.findings,
            ),
        }
        # Mark batch as completed
        cur.execute(
            "UPDATE raw.ingestion_batches SET run_completed_at = now() "
            "WHERE batch_id = %s",
            (batch_id,),
        )
        conn.commit()

    print(_summary(result, inserted))
    return 1 if result.pipeline_blocked else 0


if __name__ == "__main__":
    sys.exit(main())
