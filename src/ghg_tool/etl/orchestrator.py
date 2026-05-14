"""ETL orchestrator — main entry point for the 10-step ingestion DAG.

Steps executed:
  1. Read CSV files (readers/csv_reader.py)
  2. Apply FR-01 synthetic row — VIANO_GARGOLA GAS_NAT 2024 = 0
  3. Apply FR-02 synthetic row — SASSUOLO EE_Acquistata_Grid 2025 = 0
  4. Apply FR-37 Cat 3 metadata defaulting
  5. Run pandera schema validation
  6. Run DQ-CRIT gates (01..05); CRIT failure stops the pipeline + writes DLQ
  7. Run DQ-WARN gates (01..04); WARN annotates but does not stop
  8. Write staging rows (raw.scope{1,2,3}_ingestions)
  9. Run Cat 3 FR-11 reconciliation
  10. Persist all DQ findings to dq_findings table

This module does NOT compute emissions — that is the data-analyst's job
in wave 2.  It writes raw staging rows and DQ findings only.

Import direction: etl → application.services (OK); etl NEVER imports
api or infrastructure.db directly (decoupled via dependency injection).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ghg_tool.etl.cat3_reconciliation import compute_cat3_reconciliation
from ghg_tool.etl.dq_gates.checks import (
    check_facility_coverage,
    check_mandatory_columns,
    check_negative_quantities,
    check_outlier_zscore,
    check_temporal_gap,
    check_warn_01_viano_electricity,
    check_warn_02_estimated_quality,
)
from ghg_tool.etl.readers.csv_reader import read_scope1, read_scope2, read_scope3
from ghg_tool.etl.schemas.pandera_schemas import scope1_schema, scope2_schema, scope3_schema
from ghg_tool.etl.transforms.synth_rows import (
    apply_fr37_cat3_metadata_defaulting,
    synthesise_sassuolo_grid_2025,
    synthesise_viano_gargola_gas_nat_2024,
)
from ghg_tool.etl.writers.staging_writer import (
    build_scope1_rows,
    build_scope2_rows,
    build_scope3_rows,
)

FindingDict = dict[str, Any]


@dataclass(frozen=True)
class ETLResult:
    """Result envelope returned by ``run_ingestion_pipeline``.

    All fields are set at construction time and are immutable thereafter
    (``frozen=True``).  The mutable containers (lists) are passed in by the
    orchestrator and must not be mutated by callers after construction.

    Attributes:
        correlation_id: UUID that ties this ETL result to its ingestion batch.
            Equals the ``batch_id`` passed to ``run_ingestion_pipeline``.
        scope1_row_count: Number of Scope 1 staging rows produced.
            Non-negative integer; 0 when the pipeline is blocked.
        scope2_row_count: Number of Scope 2 staging rows produced.
            Non-negative integer; 0 when the pipeline is blocked.
        scope3_row_count: Number of Scope 3 staging rows produced.
            Non-negative integer; 0 when the pipeline is blocked.
        all_findings: Flat list of every DQ finding dict (INFO, WARN, CRIT)
            emitted during the run, tagged with ``dq_report_version``.
        dlq_entries: DLQ dicts for every CRIT finding that blocked the
            pipeline; empty list when ``pipeline_blocked`` is False.
        pipeline_blocked: True if at least one DQ-CRIT gate failed.
            When True the caller must NOT persist staging rows to the DB.
        scope1_rows: Scope 1 staging row dicts ready for bulk insert.
        scope2_rows: Scope 2 staging row dicts ready for bulk insert.
        scope3_rows: Scope 3 staging row dicts ready for bulk insert.
    """

    correlation_id: uuid.UUID
    scope1_row_count: int
    scope2_row_count: int
    scope3_row_count: int
    all_findings: list[FindingDict]
    dlq_entries: list[dict[str, Any]]
    pipeline_blocked: bool
    scope1_rows: list[dict[str, Any]]
    scope2_rows: list[dict[str, Any]]
    scope3_rows: list[dict[str, Any]]


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 of a file for ingestion_batches provenance.

    Args:
        path: Path to the file.

    Returns:
        Hex digest string (64 chars).
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_crit_checks(
    df1: Any,
    df2: Any,
    df3: Any,
    tenant_id: uuid.UUID,
    correlation_id: uuid.UUID,
    dq_report_version: str,
) -> tuple[bool, list[FindingDict], list[dict[str, Any]]]:
    """Run all DQ-CRIT gates (01..05) and collect findings and DLQ entries.

    Args:
        df1: Validated Scope 1 DataFrame.
        df2: Validated Scope 2 DataFrame.
        df3: Validated Scope 3 DataFrame.
        tenant_id: Tenant UUID for DLQ rows.
        correlation_id: Correlation UUID for DLQ rows.
        dq_report_version: Version tag to stamp on each finding.

    Returns:
        ``(all_passed, findings, dlq_entries)`` — ``all_passed`` is False if
        any CRIT gate failed; ``dlq_entries`` contains one entry per CRIT hit.
    """
    checks = [
        check_facility_coverage(df1, df2),
        check_mandatory_columns(df1, 1),
        check_mandatory_columns(df2, 2),
        check_mandatory_columns(df3, 3),
        check_negative_quantities(df1, 1),
        check_negative_quantities(df2, 2),
        check_negative_quantities(df3, 3),
        check_outlier_zscore(df1, 1),
        check_temporal_gap(df1, df2),
    ]
    all_passed = True
    findings: list[FindingDict] = []
    dlq_entries: list[dict[str, Any]] = []
    for passes, gate_findings in checks:
        findings.extend(_tag_findings(gate_findings, dq_report_version))
        if not passes:
            all_passed = False
            dlq_entries.extend(_findings_to_dlq(gate_findings, tenant_id, correlation_id))
    return all_passed, findings, dlq_entries


def _run_warn_checks(
    df1: Any,
    df2: Any,
    dq_report_version: str,
) -> list[FindingDict]:
    """Run all DQ-WARN gates (01..02) and return annotating findings.

    Args:
        df1: Validated Scope 1 DataFrame.
        df2: Validated Scope 2 DataFrame.
        dq_report_version: Version tag to stamp on each finding.

    Returns:
        Flat list of WARN-level finding dicts; never blocks the pipeline.
    """
    findings: list[FindingDict] = []
    _, w1 = check_warn_01_viano_electricity(df2)
    findings.extend(_tag_findings(w1, dq_report_version))
    _, w2a = check_warn_02_estimated_quality(df1, 1)
    findings.extend(_tag_findings(w2a, dq_report_version))
    _, w2b = check_warn_02_estimated_quality(df2, 2)
    findings.extend(_tag_findings(w2b, dq_report_version))
    return findings


def run_ingestion_pipeline(
    *,
    scope1_path: Path,
    scope2_path: Path,
    scope3_path: Path,
    batch_id: uuid.UUID,
    tenant_id: uuid.UUID,
    ingested_by: str,
    dq_report_version: str = "1.0.0",
) -> ETLResult:
    """Execute the 10-step ETL ingestion pipeline.

    Steps 1–9 are pure-function computations.  Step 10 (DB write) is
    performed by the caller (application service layer in wave 2) using
    the returned ``ETLResult``.

    Does NOT compute emissions — that is the data-analyst's job.

    Args:
        scope1_path: Path to scope1_combustione.csv.
        scope2_path: Path to scope2_elettricita.csv.
        scope3_path: Path to scope3_categorie.csv.
        batch_id: UUID of the parent ingestion batch (pre-created by caller).
        tenant_id: Tenant UUID for all insert rows.
        ingested_by: Username or service account string.
        dq_report_version: DQ report version tag for dq_findings rows.

    Returns:
        ``ETLResult`` with all rows and findings ready for DB persistence.
    """
    correlation_id = batch_id  # ETL batch_id == correlation_id
    all_findings: list[FindingDict] = []

    # -- Steps 1–3: Read CSVs + synthetic rows --------------------------------
    df1 = read_scope1(scope1_path)
    df2 = read_scope2(scope2_path)
    df3 = read_scope3(scope3_path)
    df1, f1 = synthesise_viano_gargola_gas_nat_2024(df1)
    df2, f2 = synthesise_sassuolo_grid_2025(df2)
    df3, f37 = apply_fr37_cat3_metadata_defaulting(df3)
    all_findings.extend(_tag_findings(f1, dq_report_version))
    all_findings.extend(_tag_findings(f2, dq_report_version))
    all_findings.extend(_tag_findings(f37, dq_report_version))

    # -- Step 5: Pandera schema validation ------------------------------------
    df1 = scope1_schema.validate(df1, lazy=True)
    df2 = scope2_schema.validate(df2, lazy=True)
    df3 = scope3_schema.validate(df3, lazy=True)

    # -- Steps 6–7: DQ-CRIT gates then DQ-WARN gates -------------------------
    crit_passed, crit_findings, dlq_entries = _run_crit_checks(
        df1, df2, df3, tenant_id, correlation_id, dq_report_version
    )
    all_findings.extend(crit_findings)
    all_findings.extend(_run_warn_checks(df1, df2, dq_report_version))

    # -- Step 8: Build staging rows -------------------------------------------
    scope1_rows = build_scope1_rows(df1, batch_id=batch_id, tenant_id=tenant_id,
                                    ingested_by=ingested_by)
    scope2_rows = build_scope2_rows(df2, batch_id=batch_id, tenant_id=tenant_id,
                                    ingested_by=ingested_by)
    scope3_rows = build_scope3_rows(df3, batch_id=batch_id, tenant_id=tenant_id,
                                    ingested_by=ingested_by)

    # -- Step 9: Cat 3 FR-11 reconciliation -----------------------------------
    all_findings.extend(_tag_findings(compute_cat3_reconciliation(df1, df3), dq_report_version))

    return ETLResult(
        correlation_id=correlation_id,
        scope1_row_count=len(scope1_rows),
        scope2_row_count=len(scope2_rows),
        scope3_row_count=len(scope3_rows),
        all_findings=all_findings,
        dlq_entries=dlq_entries,
        pipeline_blocked=not crit_passed,
        scope1_rows=scope1_rows,
        scope2_rows=scope2_rows,
        scope3_rows=scope3_rows,
    )


def _tag_findings(
    findings: list[FindingDict],
    dq_report_version: str,
) -> list[FindingDict]:
    """Add ``dq_report_version`` to each finding dict.

    Args:
        findings: List of finding dicts from a check function.
        dq_report_version: Version string to stamp on each finding.

    Returns:
        Same list with ``dq_report_version`` key added in-place.
    """
    for f in findings:
        f.setdefault("dq_report_version", dq_report_version)
    return findings


def _findings_to_dlq(
    findings: list[FindingDict],
    tenant_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Convert CRIT findings into DLQ entry dicts.

    Args:
        findings: CRIT-level finding dicts.
        tenant_id: Tenant UUID for DLQ rows.
        correlation_id: Correlation UUID for DLQ rows.

    Returns:
        List of DLQ dicts for persistence.
    """
    dlq: list[dict[str, Any]] = []
    for f in findings:
        if f.get("severity") != "CRIT":
            continue
        dlq.append(
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
                "rule_id": f["rule_id"],
                "severity": "CRIT",
                "scope": f.get("scope", 0),
                "codice_sito": f.get("codice_sito"),
                "anno": f.get("anno"),
                "combustibile_or_voce": f.get("metric"),
                "raw_row_payload": f,  # store full finding as JSONB payload
                "value_observed": f.get("value_observed"),
                "threshold": str(f.get("value_reference", "")),
                "z_score": f.get("z_score"),
                "message": f.get("trigger_desc", ""),
            }
        )
    return dlq
