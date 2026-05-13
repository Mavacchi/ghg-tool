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


class ETLResult:
    """Result envelope returned by ``run_ingestion_pipeline``."""

    def __init__(
        self,
        correlation_id: uuid.UUID,
        scope1_row_count: int,
        scope2_row_count: int,
        scope3_row_count: int,
        all_findings: list[FindingDict],
        dlq_entries: list[dict[str, Any]],
        pipeline_blocked: bool,
        scope1_rows: list[dict[str, Any]],
        scope2_rows: list[dict[str, Any]],
        scope3_rows: list[dict[str, Any]],
    ) -> None:
        self.correlation_id = correlation_id
        self.scope1_row_count = scope1_row_count
        self.scope2_row_count = scope2_row_count
        self.scope3_row_count = scope3_row_count
        self.all_findings = all_findings
        self.dlq_entries = dlq_entries
        self.pipeline_blocked = pipeline_blocked
        self.scope1_rows = scope1_rows
        self.scope2_rows = scope2_rows
        self.scope3_rows = scope3_rows


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
    dlq_entries: list[dict[str, Any]] = []

    # -- Step 1: Read CSVs ---------------------------------------------------
    df1 = read_scope1(scope1_path)
    df2 = read_scope2(scope2_path)
    df3 = read_scope3(scope3_path)

    # -- Step 2: FR-01 synthetic row -----------------------------------------
    df1, f1 = synthesise_viano_gargola_gas_nat_2024(df1)
    all_findings.extend(_tag_findings(f1, dq_report_version))

    # -- Step 3: FR-02 synthetic row -----------------------------------------
    df2, f2 = synthesise_sassuolo_grid_2025(df2)
    all_findings.extend(_tag_findings(f2, dq_report_version))

    # -- Step 4: FR-37 defaulting --------------------------------------------
    df3, f37 = apply_fr37_cat3_metadata_defaulting(df3)
    all_findings.extend(_tag_findings(f37, dq_report_version))

    # -- Step 5: Pandera schema validation ------------------------------------
    df1 = scope1_schema.validate(df1, lazy=True)
    df2 = scope2_schema.validate(df2, lazy=True)
    df3 = scope3_schema.validate(df3, lazy=True)

    # -- Step 6: DQ-CRIT gates -----------------------------------------------
    pipeline_blocked = False
    _crit_checks = [
        (check_facility_coverage(df1, df2)),
        (check_mandatory_columns(df1, 1)),
        (check_mandatory_columns(df2, 2)),
        (check_mandatory_columns(df3, 3)),
        (check_negative_quantities(df1, 1)),
        (check_negative_quantities(df2, 2)),
        (check_negative_quantities(df3, 3)),
        (check_outlier_zscore(df1, 1)),
        (check_temporal_gap(df1, df2)),
    ]
    for passes, findings in _crit_checks:
        all_findings.extend(_tag_findings(findings, dq_report_version))
        if not passes:
            pipeline_blocked = True
            dlq_entries.extend(
                _findings_to_dlq(findings, tenant_id, correlation_id)
            )

    # -- Step 7: DQ-WARN gates -----------------------------------------------
    _, w1 = check_warn_01_viano_electricity(df2)
    all_findings.extend(_tag_findings(w1, dq_report_version))
    _, w2a = check_warn_02_estimated_quality(df1, 1)
    all_findings.extend(_tag_findings(w2a, dq_report_version))
    _, w2b = check_warn_02_estimated_quality(df2, 2)
    all_findings.extend(_tag_findings(w2b, dq_report_version))

    # -- Step 8: Build staging rows (not yet written to DB here) -------------
    scope1_rows = build_scope1_rows(df1, batch_id=batch_id, tenant_id=tenant_id,
                                    ingested_by=ingested_by)
    scope2_rows = build_scope2_rows(df2, batch_id=batch_id, tenant_id=tenant_id,
                                    ingested_by=ingested_by)
    scope3_rows = build_scope3_rows(df3, batch_id=batch_id, tenant_id=tenant_id,
                                    ingested_by=ingested_by)

    # -- Step 9: Cat 3 FR-11 reconciliation ----------------------------------
    rec_findings = compute_cat3_reconciliation(df1, df3)
    all_findings.extend(_tag_findings(rec_findings, dq_report_version))

    return ETLResult(
        correlation_id=correlation_id,
        scope1_row_count=len(scope1_rows),
        scope2_row_count=len(scope2_rows),
        scope3_row_count=len(scope3_rows),
        all_findings=all_findings,
        dlq_entries=dlq_entries,
        pipeline_blocked=pipeline_blocked,
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
