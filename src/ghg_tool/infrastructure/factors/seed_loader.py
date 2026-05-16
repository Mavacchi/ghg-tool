"""Factor catalog seed loader — real pipeline for DEFRA/ISPRA/AIB/Ecoinvent sources.

Responsibilities
----------------
1. Hash-check source files (SHA-256) against pinned values for reproducibility.
2. Parse each source: openpyxl for Excel, pdfplumber for PDF stubs, pandas for CSV.
3. Map rows to factor_id business codes per naming convention.
4. Optionally upload raw files to MinIO (if MINIO_ENDPOINT env var is set).
5. INSERT into ref.factor_catalog with evidence_url stored as pdf_source_uri.

CLI entry point
---------------
    python -m ghg_tool.infrastructure.factors.seed_loader --apply
    python -m ghg_tool.infrastructure.factors.seed_loader --check-hash {defra|ispra|aib|ecoinvent}
    python -m ghg_tool.infrastructure.factors.seed_loader --list-tbc

Idempotency
-----------
All INSERTs use ON CONFLICT (tenant_id, factor_id, version, gwp_set) DO NOTHING.
The loader is therefore safe to re-run without creating duplicates.

Design notes
------------
- pdfplumber is an optional dependency (PDF sources are placeholders until the
  data engineer manually downloads ISPRA and AIB PDFs; see data/raw_factor_sources/).
- MinIO upload uses the standard boto3-compatible pattern; falls back to local
  file:// URI when MINIO_ENDPOINT is not set.
- No network calls are made in tests: all external calls are injected as
  dependencies and patched in tests/unit/infrastructure/test_seed_loader.py.

Import direction: infrastructure -> domain (allowed per arch rules).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Raised when required configuration (e.g. SHA-256 pin) is missing or invalid."""


# ---------------------------------------------------------------------------
# Repository root & data directory
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parents[5]  # src/ghg_tool/infrastructure/factors -> repo root
_RAW_DIR = _REPO_ROOT / "data" / "raw_factor_sources"

# ---------------------------------------------------------------------------
# Pinned SHA-256 hashes for source files
# Auditors can reproduce by running: sha256sum <file>
# ---------------------------------------------------------------------------
DEFRA_EXCEL_SHA256: str = (
    "f2fbf9b592e71dae6b73a0217b7811969e015172fe1b2bba91a31e0f69b81803"
)
ECOINVENT_CSV_SHA256: str = (
    "bc48339dafa7d0716b3696d8f09b712a5bbaf98093d5d3847a58e9e6fc8a0039"
)
# PDF files: hashes are set to empty string until the data engineer downloads them.
# The loader raises a clear error when the hash is empty and --apply is used.
ISPRA_PDF_SHA256: str = ""   # TODO: set after downloading ispra_413_2025.pdf
AIB_PDF_SHA256: str = ""     # TODO: set after downloading aib_residual_mix_2024.pdf

# ---------------------------------------------------------------------------
# Source file names
# ---------------------------------------------------------------------------
_DEFRA_FILE = "defra_2024_ghg_conversion_v1.xlsx"
_ECOINVENT_FILE = "ecoinvent_v3.10_sample.csv"
_ISPRA_FILE = "ispra_413_2025.pdf"
_AIB_FILE = "aib_residual_mix_2024.pdf"

# ---------------------------------------------------------------------------
# MinIO configuration (optional)
# ---------------------------------------------------------------------------
_MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "")
_MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "gh-tool-evidence")
_MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
_MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "")

# ---------------------------------------------------------------------------
# Database URL
# ---------------------------------------------------------------------------
_DB_URL = os.environ.get(
    "SQLALCHEMY_URL",
    "postgresql+psycopg://ghg_app:changeme@localhost:5432/ghg_tool",
)

# ---------------------------------------------------------------------------
# Factor record type alias
# ---------------------------------------------------------------------------
FactorRecord = dict[str, Any]


# ===========================================================================
# 1. Hash verification
# ===========================================================================


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file.

    Args:
        path: Absolute path to the file.

    Returns:
        Lowercase hex SHA-256 string.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_hash(path: Path, expected_sha256: str, source_name: str) -> None:
    """Assert that a file matches its pinned SHA-256 hash.

    Args:
        path: Path to the file on disk.
        expected_sha256: Pinned SHA-256 hex string (from code).
        source_name: Human-readable source label for error messages.

    Raises:
        FileNotFoundError: If the file is absent (placeholder only present).
        ValueError: If hash mismatches the pin OR pin is empty.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Source file not found: {path}. "
            f"See data/raw_factor_sources/{path.name}.placeholder for instructions."
        )
    if not expected_sha256:
        raise ValueError(
            f"SHA-256 pin for {source_name} is empty — "
            f"download the file and set the pin constant in seed_loader.py first."
        )
    actual = compute_sha256(path)
    if actual != expected_sha256.lower():
        raise ValueError(
            f"Hash mismatch for {source_name}: "
            f"expected {expected_sha256}, got {actual}. "
            f"The file may have been tampered with or is a different edition. "
            f"Auditor reproducibility requires an exact hash match."
        )
    logger.info("Hash verified OK: %s (%s...)", source_name, actual[:16])


# ===========================================================================
# 2. MinIO upload (optional)
# ===========================================================================


def upload_to_minio(local_path: Path, object_name: str) -> str:
    """Upload a file to MinIO and return the minio:// URI.

    Falls back to a local file:// URI when MINIO_ENDPOINT is not configured.

    Args:
        local_path: Local file path.
        object_name: Object key in the MinIO bucket.

    Returns:
        Evidence URI string (minio:// or file://).
    """
    if not _MINIO_ENDPOINT:
        uri = f"file://{local_path.resolve()}"
        logger.debug("MinIO not configured; evidence_url = %s", uri)
        return uri

    try:
        import boto3  # type: ignore[import-not-found]
        from botocore.client import Config  # type: ignore[import-not-found]

        s3 = boto3.client(
            "s3",
            endpoint_url=_MINIO_ENDPOINT,
            aws_access_key_id=_MINIO_ACCESS_KEY,
            aws_secret_access_key=_MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
        s3.upload_file(str(local_path), _MINIO_BUCKET, object_name)
        uri = f"minio://{_MINIO_BUCKET}/{object_name}"
        logger.info("Uploaded to MinIO: %s", uri)
        return uri
    except ImportError:
        uri = f"file://{local_path.resolve()}"
        logger.warning(
            "boto3 not installed; skipping MinIO upload, evidence_url = %s", uri
        )
        return uri


# ===========================================================================
# 3a. Parse DEFRA 2024 Excel
# ===========================================================================


def parse_defra_excel(path: Path) -> list[FactorRecord]:
    """Parse the DEFRA 2024 GHG Conversion Factors Excel fixture.

    Expected sheet: 'Stationary combustion'
    Required columns: factor_id, substance, scope, category, source,
                      version, value, unit, gwp_set, vintage, applicability_note

    Args:
        path: Path to defra_2024_ghg_conversion_v1.xlsx.

    Returns:
        List of FactorRecord dicts ready for DB insertion.

    Raises:
        ValueError: If required columns are missing.
    """
    df = pd.read_excel(path, sheet_name="Stationary combustion", engine="openpyxl")

    required_cols = {
        "factor_id", "substance", "scope", "category", "source",
        "version", "value", "unit", "gwp_set", "vintage", "applicability_note",
    }
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(
            f"DEFRA Excel is missing required columns: {sorted(missing)}"
        )

    records: list[FactorRecord] = []
    for _, row in df.iterrows():
        records.append(
            {
                "factor_id": str(row["factor_id"]).strip(),
                "substance": str(row["substance"]).strip(),
                "scope": int(row["scope"]),
                "category": str(row["category"]).strip(),
                "source": str(row["source"]).strip(),
                "version": str(row["version"]).strip(),
                "value": Decimal(str(row["value"])),
                "unit": str(row["unit"]).strip(),
                "gwp_set": str(row["gwp_set"]).strip(),
                "vintage": str(row["vintage"]).strip(),
                "applicability_note": str(row["applicability_note"]).strip(),
                "is_tbc": False,
                "is_licence_only": False,
            }
        )
    logger.info("DEFRA Excel parsed: %d factor records", len(records))
    return records


# ===========================================================================
# 3b. Parse Ecoinvent CSV
# ===========================================================================


def parse_ecoinvent_csv(path: Path) -> list[FactorRecord]:
    """Parse the Ecoinvent v3.10 sample CSV.

    Expected columns: material_id, source, value_kgCO2e_per_kg, gwp_set,
                      vintage, methodology, applicability_note

    The CSV contains anonymised/sample data. Replace with licensed Ecoinvent
    export before production use (see docs/methodology/factor_sources.md).

    Args:
        path: Path to ecoinvent_v3.10_sample.csv.

    Returns:
        List of FactorRecord dicts.

    Raises:
        ValueError: If required columns are missing.
    """
    df = pd.read_csv(path)

    required_cols = {
        "material_id", "source", "value_kgCO2e_per_kg", "gwp_set",
        "vintage", "methodology", "applicability_note",
    }
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(
            f"Ecoinvent CSV is missing required columns: {sorted(missing)}"
        )

    records: list[FactorRecord] = []
    for _, row in df.iterrows():
        records.append(
            {
                "factor_id": str(row["material_id"]).strip(),
                "substance": str(row["applicability_note"]).split(";")[0].strip(),
                "scope": 3,
                "category": "Cat 1",
                "source": "ecoinvent",
                "version": "3.10",
                "value": Decimal(str(row["value_kgCO2e_per_kg"])),
                "unit": "kg CO2e / kg",
                "gwp_set": str(row["gwp_set"]).strip(),
                "vintage": str(row["vintage"]).strip(),
                "applicability_note": str(row["applicability_note"]).strip(),
                "is_tbc": False,
                # Sample CSV values are NOT production-licensed data.
                # When loading a real licensed export set is_licence_only=True.
                "is_licence_only": True,
            }
        )
    logger.info("Ecoinvent CSV parsed: %d factor records", len(records))
    return records


# ===========================================================================
# 3c. Parse ISPRA PDF (stub — requires manual download)
# ===========================================================================


def parse_ispra_pdf(path: Path) -> list[FactorRecord]:
    """Parse ISPRA Rapporto 413/2025 PDF for Italian grid LB emission factor.

    Requires pdfplumber (optional dependency).  The ISPRA PDF is not committed
    to the repository — see .placeholder file for download instructions.

    The Italian grid LB factor appears in Table 3 of the ISPRA report as
    'Fattore medio di emissione (consumo)' in gCO2eq/kWh.  This function
    extracts that value and converts to kgCO2eq/kWh.

    Args:
        path: Path to ispra_413_2025.pdf (must be manually downloaded).

    Returns:
        List with one FactorRecord for LB_IT_GRID_ISPRA_2024.

    Raises:
        ConfigurationError: If ISPRA_PDF_SHA256 is empty and bypass env var is unset.
        ImportError: If pdfplumber is not installed.
        ValueError: If the factor value cannot be extracted from the PDF.
        FileNotFoundError: If the PDF file does not exist.
    """
    if not ISPRA_PDF_SHA256 and not os.environ.get("GHG_SEED_SKIP_HASH_CHECK"):
        raise ConfigurationError(
            "ISPRA_PDF_SHA256 is empty; set the SHA-256 or export "
            "GHG_SEED_SKIP_HASH_CHECK=1 to bypass (NOT for production)."
        )

    try:
        import pdfplumber  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "pdfplumber is required to parse ISPRA PDFs. "
            "Install with: pip install pdfplumber"
        ) from exc

    if not path.exists():
        raise FileNotFoundError(
            f"ISPRA PDF not found: {path}. "
            "See data/raw_factor_sources/ispra_413_2025.placeholder for download instructions."
        )

    import re

    extracted_value: Decimal | None = None

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # ISPRA 413/2025 Table 3 format example:
            # "Fattore medio di emissione (consumo)   350,4 gCO2eq/kWh"
            match = re.search(
                r"Fattore medio.*?consumo[^0-9]*([0-9]+[,\.][0-9]+)\s*gCO2",
                text,
                re.IGNORECASE,
            )
            if match:
                raw = match.group(1).replace(",", ".")
                # gCO2eq/kWh -> kgCO2eq/kWh
                extracted_value = Decimal(raw) / Decimal("1000")
                logger.info(
                    "ISPRA: extracted grid factor %s gCO2eq/kWh = %s kgCO2eq/kWh",
                    raw,
                    extracted_value,
                )
                break

    if extracted_value is None:
        raise ValueError(
            "Could not extract Italian grid LB factor from ISPRA 413/2025 PDF. "
            "The PDF layout may have changed — manual extraction required. "
            "See methodology_validation.md §13 ref 19."
        )

    return [
        {
            "factor_id": "LB_IT_GRID_ISPRA_2024",
            "substance": "Electricity grid Italy LB",
            "scope": 2,
            "category": "LB",
            "source": "ISPRA",
            "version": "Rapporto_413_2025",
            "value": extracted_value,
            "unit": "kg CO2 / kWh",
            "gwp_set": "AR6",
            "vintage": "2024",
            "applicability_note": (
                "Italian grid LB consumption-side; ISPRA Rapporto 413/2025 "
                "(2023 data); 2024 vintage pending mid-2026 publication — "
                "use 2023 value with offset disclosed."
            ),
            "is_tbc": False,
            "is_licence_only": False,
        }
    ]


# ===========================================================================
# 3d. Parse AIB PDF (stub — requires manual download)
# ===========================================================================


def parse_aib_pdf(path: Path) -> list[FactorRecord]:
    """Parse AIB European Residual Mix 2024 PDF for Italian residual mix factor.

    Requires pdfplumber.  The AIB PDF is not committed — see .placeholder file.

    Args:
        path: Path to aib_residual_mix_2024.pdf (must be manually downloaded).

    Returns:
        List with one FactorRecord for MB_IT_RESIDUAL_AIB_2024.

    Raises:
        ConfigurationError: If AIB_PDF_SHA256 is empty and bypass env var is unset.
        ImportError: If pdfplumber is not installed.
        ValueError: If the Italian factor cannot be extracted from the PDF.
        FileNotFoundError: If the PDF file does not exist.
    """
    if not AIB_PDF_SHA256 and not os.environ.get("GHG_SEED_SKIP_HASH_CHECK"):
        raise ConfigurationError(
            "AIB_PDF_SHA256 is empty; set the SHA-256 or export "
            "GHG_SEED_SKIP_HASH_CHECK=1 to bypass (NOT for production)."
        )

    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError(
            "pdfplumber is required to parse AIB PDFs. "
            "Install with: pip install pdfplumber"
        ) from exc

    if not path.exists():
        raise FileNotFoundError(
            f"AIB PDF not found: {path}. "
            "See data/raw_factor_sources/aib_residual_mix_2024.placeholder "
            "for download instructions. "
            "Note: AIB returned HTTP 403 during Phase 2 (MG-15 gate)."
        )

    import re

    extracted_value: Decimal | None = None

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # AIB ERM report table — look for Italy row.
            # Typical format: "Italy  ...  0.xxx  kg CO2e/kWh"
            match = re.search(
                r"Italy\s+.*?([0-9]+\.[0-9]+)\s+(?:kg|kgCO2e)",
                text,
                re.IGNORECASE,
            )
            if match:
                extracted_value = Decimal(match.group(1))
                logger.info(
                    "AIB: extracted Italian residual mix factor %s kgCO2e/kWh",
                    extracted_value,
                )
                break

    if extracted_value is None:
        raise ValueError(
            "Could not extract Italian residual mix factor from AIB ERM 2024 PDF. "
            "Check the PDF layout or extract manually. "
            "See methodology_validation.md §4.5 (MG-15 gate)."
        )

    return [
        {
            "factor_id": "MB_IT_RESIDUAL_AIB_2024",
            "substance": "Electricity Italian residual mix MB",
            "scope": 2,
            "category": "MB-residual",
            "source": "AIB",
            "version": "2024",
            "value": extracted_value,
            "unit": "kg CO2e / kWh",
            "gwp_set": "AR6",
            "vintage": "2024",
            "applicability_note": (
                "AIB European Residual Mix 2024 (published 2025-05-30); "
                "Italian residual mix factor; MG-15 gate."
            ),
            "is_tbc": False,
            "is_licence_only": False,
        }
    ]


# ===========================================================================
# 4. DB insert (synchronous via psycopg)
# ===========================================================================

_UPSERT_SQL = """
INSERT INTO ref.factor_catalog
    (tenant_id, factor_id, version, substance, scope, category, source,
     value, is_licence_only, is_tbc, biogenic_co2_kg_per_unit,
     unit, gwp_set, vintage, valid_from, applicability_note,
     pdf_source_uri, published_by, published_at, is_published)
SELECT t.id,
    %(factor_id)s, %(version)s, %(substance)s, %(scope)s, %(category)s, %(source)s,
    %(value)s, %(is_licence_only)s, %(is_tbc)s, NULL,
    %(unit)s, %(gwp_set)s, %(vintage)s, CURRENT_DATE, %(applicability_note)s,
    %(evidence_url)s, 'system_seed', now(), TRUE
FROM ref.tenants t WHERE t.code = 'CERAMIC_TILE_CO'
ON CONFLICT (tenant_id, factor_id, version, gwp_set) DO NOTHING;
"""


def insert_factors(
    conn: Any,
    records: list[FactorRecord],
    evidence_url: str,
) -> int:
    """Bulk-insert factor records using psycopg executemany.

    Idempotent: ON CONFLICT DO NOTHING prevents duplicates on re-run.
    The consolidated ref.factor_catalog trigger blocks UPDATE/DELETE on
    published rows (ops.deny_factor_mutation), so we never mutate existing data.

    Args:
        conn: psycopg3 Connection (synchronous).
        records: List of FactorRecord dicts from a parse_* function.
        evidence_url: minio:// or file:// URI to store as pdf_source_uri.

    Returns:
        Number of rows submitted (not guaranteed inserted — use rowcount for
        actual inserts; ON CONFLICT DO NOTHING returns rowcount=0 on dup).
    """
    params = [
        {
            "factor_id": r["factor_id"],
            "version": r["version"],
            "substance": r["substance"],
            "scope": r["scope"],
            "category": r["category"],
            "source": r["source"],
            "value": float(r["value"]) if r.get("value") is not None else None,
            "is_licence_only": r.get("is_licence_only", False),
            "is_tbc": r.get("is_tbc", False),
            "unit": r["unit"],
            "gwp_set": r["gwp_set"],
            "vintage": r["vintage"],
            "applicability_note": r.get("applicability_note", ""),
            "evidence_url": evidence_url,
        }
        for r in records
    ]
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, params)
    conn.commit()
    logger.info("Submitted %d factor records via executemany (ON CONFLICT DO NOTHING)", len(params))
    return len(params)


# ===========================================================================
# 5. Main orchestrator
# ===========================================================================


def load_all_seeds(
    *,
    db_url: str | None = None,
    raw_dir: Path | None = None,
    skip_pdf: bool = False,
) -> dict[str, Any]:
    """Load all factor seeds from verified source files into ref.factor_catalog.

    Pipeline per source:
    1. Hash-check file against pinned SHA-256.
    2. Parse into FactorRecord list.
    3. Upload to MinIO (if configured).
    4. INSERT into ref.factor_catalog via idempotent upsert.

    Args:
        db_url: PostgreSQL connection URL; defaults to SQLALCHEMY_URL env var.
        raw_dir: Directory containing source files; defaults to data/raw_factor_sources/.
        skip_pdf: If True, skip ISPRA and AIB PDF parsing (useful when PDFs are
                  not yet downloaded; their TBC rows remain in the DB).

    Returns:
        Dict with counts per source and overall status.
    """
    import psycopg

    effective_url = db_url or _DB_URL
    effective_dir = raw_dir or _RAW_DIR

    # Convert SQLAlchemy URL to psycopg3 DSN (strip +psycopg suffix if present)
    dsn = effective_url.replace("postgresql+psycopg://", "postgresql://")

    result: dict[str, Any] = {"sources": {}, "total_inserted": 0, "status": "OK"}

    with psycopg.connect(dsn) as conn:

        # --- DEFRA 2024 Excel ---
        defra_path = effective_dir / _DEFRA_FILE
        try:
            verify_hash(defra_path, DEFRA_EXCEL_SHA256, "DEFRA 2024 Excel")
            defra_records = parse_defra_excel(defra_path)
            evidence_url = upload_to_minio(defra_path, f"factor-sources/{_DEFRA_FILE}")
            n = insert_factors(conn, defra_records, evidence_url)
            result["sources"]["defra"] = {"inserted": n, "status": "OK"}
            result["total_inserted"] += n
        except FileNotFoundError as exc:
            logger.error("DEFRA seed failed — file missing: %s", exc)
            result["sources"]["defra"] = {"error": str(exc), "status": "FAILED"}
            result["status"] = "PARTIAL"
        except ValueError as exc:
            logger.error("DEFRA seed failed — hash mismatch or parse error: %s", exc)
            result["sources"]["defra"] = {"error": str(exc), "status": "FAILED"}
            result["status"] = "PARTIAL"
        except psycopg.DatabaseError as exc:
            logger.error("DEFRA seed failed — database error: %s", exc)
            result["sources"]["defra"] = {"error": str(exc), "status": "FAILED"}
            result["status"] = "PARTIAL"

        # --- Ecoinvent CSV ---
        ecoinvent_path = effective_dir / _ECOINVENT_FILE
        try:
            verify_hash(ecoinvent_path, ECOINVENT_CSV_SHA256, "Ecoinvent v3.10 CSV")
            ecoinvent_records = parse_ecoinvent_csv(ecoinvent_path)
            evidence_url = upload_to_minio(ecoinvent_path, f"factor-sources/{_ECOINVENT_FILE}")
            n = insert_factors(conn, ecoinvent_records, evidence_url)
            result["sources"]["ecoinvent"] = {"inserted": n, "status": "OK"}
            result["total_inserted"] += n
        except FileNotFoundError as exc:
            logger.error("Ecoinvent seed failed — file missing: %s", exc)
            result["sources"]["ecoinvent"] = {"error": str(exc), "status": "FAILED"}
            result["status"] = "PARTIAL"
        except ValueError as exc:
            logger.error("Ecoinvent seed failed — hash mismatch or parse error: %s", exc)
            result["sources"]["ecoinvent"] = {"error": str(exc), "status": "FAILED"}
            result["status"] = "PARTIAL"
        except psycopg.DatabaseError as exc:
            logger.error("Ecoinvent seed failed — database error: %s", exc)
            result["sources"]["ecoinvent"] = {"error": str(exc), "status": "FAILED"}
            result["status"] = "PARTIAL"

        # --- ISPRA PDF (optional — requires manual download) ---
        if not skip_pdf:
            ispra_path = effective_dir / _ISPRA_FILE
            try:
                verify_hash(ispra_path, ISPRA_PDF_SHA256, "ISPRA Rapporto 413/2025")
                ispra_records = parse_ispra_pdf(ispra_path)
                evidence_url = upload_to_minio(ispra_path, f"factor-sources/{_ISPRA_FILE}")
                n = insert_factors(conn, ispra_records, evidence_url)
                result["sources"]["ispra"] = {"inserted": n, "status": "OK"}
                result["total_inserted"] += n
            except (FileNotFoundError, ValueError) as exc:
                logger.warning("ISPRA seed skipped (file not yet downloaded): %s", exc)
                result["sources"]["ispra"] = {
                    "error": str(exc),
                    "status": "SKIPPED_PENDING_DOWNLOAD",
                }

        # --- AIB PDF (optional — requires manual download) ---
        if not skip_pdf:
            aib_path = effective_dir / _AIB_FILE
            try:
                verify_hash(aib_path, AIB_PDF_SHA256, "AIB ERM 2024")
                aib_records = parse_aib_pdf(aib_path)
                evidence_url = upload_to_minio(aib_path, f"factor-sources/{_AIB_FILE}")
                n = insert_factors(conn, aib_records, evidence_url)
                result["sources"]["aib"] = {"inserted": n, "status": "OK"}
                result["total_inserted"] += n
            except (FileNotFoundError, ValueError) as exc:
                logger.warning("AIB seed skipped (file not yet downloaded): %s", exc)
                result["sources"]["aib"] = {
                    "error": str(exc),
                    "status": "SKIPPED_PENDING_DOWNLOAD",
                }

    return result


# ===========================================================================
# Legacy helper API (kept for backward-compat with code that imported
# list_tbc_factor_ids / get_tbc_source_url / hash_pin_pdf_evidence)
# ===========================================================================

_TBC_FACTOR_URLS: dict[str, str] = {
    "LB_IT_GRID_ISPRA_2024": (
        "https://emissioni.sina.isprambiente.it/wp-content/uploads/2025/05/"
        "Le-emissioni-di-CO2-nel-settore-elettrico_r413-2025_def.pdf"
    ),
    "MB_IT_RESIDUAL_AIB_2024": "https://www.aib-net.org/facts/european-residual-mix/2024",
    "WTT_GAS_NAT_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WTT_GASOLIO_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WTT_BENZINA_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WTT_ELEC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "TND_ELEC_IT_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "FREIGHT_HGV_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "FREIGHT_RAIL_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "FREIGHT_SEA_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "TRAVEL_SPEND_FLIGHTS_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "TRAVEL_SPEND_HIRECAR_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "TRAVEL_SPEND_HOTEL_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMMUTE_CAR_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WASTE_LANDFILL_PERIC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WASTE_LANDFILL_NONPERIC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WASTE_RECYCLE_PERIC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WASTE_RECYCLE_NONPERIC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GAS_NAT_CO2_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GAS_NAT_CH4_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GAS_NAT_N2O_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GASOLIO_CO2_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GASOLIO_CH4_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GASOLIO_N2O_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_BENZINA_CO2_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_BENZINA_CH4_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_BENZINA_N2O_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "ECOINV_CARDBOARD_V3_10": "https://ecoinvent.org/ecoinvent-v3-10/",
    "ECOINV_PALLET_V3_10": "https://ecoinvent.org/ecoinvent-v3-10/",
}

_DETERMINISTIC_FACTORS: dict[str, Decimal] = {
    "STOICH_CACO3_IPCC_2006": Decimal("0.4397"),
    "MB_GO_ZERO": Decimal("0.0"),
}


def list_tbc_factor_ids() -> list[str]:
    """Return all factor IDs that are still pending numeric pinning.

    Returns:
        Sorted list of factor_id strings with TBC status.
    """
    return sorted(_TBC_FACTOR_URLS.keys())


def get_tbc_source_url(factor_id: str) -> str | None:
    """Return the authoritative source URL for a TBC factor.

    Args:
        factor_id: Factor identifier to look up.

    Returns:
        URL string, or None if factor_id is not in the TBC registry.
    """
    return _TBC_FACTOR_URLS.get(factor_id)


def get_deterministic_value(factor_id: str) -> Decimal | None:
    """Return the deterministic (non-TBC) value for a factor.

    Args:
        factor_id: Factor identifier.

    Returns:
        Decimal value, or None if not a deterministic factor.
    """
    return _DETERMINISTIC_FACTORS.get(factor_id)


def hash_pin_pdf_evidence(factor_id: str, pdf_path: str) -> str:
    """Compute SHA-256 hash of a factor source PDF for MinIO provenance.

    Prints the hash for manual pinning in the SHA256 constants above.

    Args:
        factor_id: Factor identifier (for logging / MinIO naming).
        pdf_path: Local path to the retrieved PDF.

    Returns:
        SHA-256 hex digest of the PDF file.
    """
    p = Path(pdf_path)
    digest = compute_sha256(p)
    logger.info(
        "Hash for %s (%s): %s  -- set this as the SHA256 pin constant in seed_loader.py",
        factor_id,
        p.name,
        digest,
    )
    return digest


# ---------------------------------------------------------------------------
# Deprecated stub aliases (raised NotImplementedError before — now removed)
# ---------------------------------------------------------------------------


def pin_defra_2025_value(factor_id: str, value: Decimal) -> None:
    """Deprecated: use load_all_seeds() with the DEFRA Excel fixture instead.

    Previously raised NotImplementedError.  This stub is preserved so that
    any code path that called it gets a clear deprecation message rather
    than an unexpected error.

    Args:
        factor_id: DEFRA factor identifier.
        value: Confirmed numeric value.
    """
    logger.warning(
        "pin_defra_2025_value is deprecated. "
        "Use load_all_seeds() with defra_2024_ghg_conversion_v1.xlsx instead. "
        "factor_id=%s value=%s",
        factor_id,
        value,
    )


def pin_ispra_lb_factor(value: Decimal) -> None:
    """Deprecated: use load_all_seeds() with the downloaded ISPRA PDF instead.

    Args:
        value: Confirmed numeric value (kg CO2/kWh).
    """
    logger.warning(
        "pin_ispra_lb_factor is deprecated. "
        "Use load_all_seeds() after downloading ispra_413_2025.pdf. value=%s",
        value,
    )


def pin_aib_residual_mix_2024(value: Decimal) -> None:
    """Deprecated: use load_all_seeds() with the downloaded AIB PDF instead.

    Args:
        value: Confirmed numeric value (kg CO2e/kWh).
    """
    logger.warning(
        "pin_aib_residual_mix_2024 is deprecated. "
        "Use load_all_seeds() after downloading aib_residual_mix_2024.pdf. value=%s",
        value,
    )


# ===========================================================================
# CLI entry point
# ===========================================================================


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ghg_tool.infrastructure.factors.seed_loader",
        description="Load factor catalog seeds from verified source files.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run the full seed pipeline (hash check + parse + upload + DB insert).",
    )
    parser.add_argument(
        "--check-hash",
        metavar="SOURCE",
        choices=["defra", "ispra", "aib", "ecoinvent"],
        help="Print the SHA-256 of a single source file (for pinning).",
    )
    parser.add_argument(
        "--list-tbc",
        action="store_true",
        help="Print all factor_ids still pending numeric pinning.",
    )
    parser.add_argument(
        "--skip-pdf",
        action="store_true",
        default=False,
        help="Skip ISPRA and AIB PDF parsing (use when PDFs not yet downloaded).",
    )
    parser.add_argument(
        "--raw-dir",
        metavar="PATH",
        default=None,
        help="Override path to raw_factor_sources directory.",
    )
    return parser


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = _build_arg_parser()
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir) if args.raw_dir else _RAW_DIR

    if args.list_tbc:
        ids = list_tbc_factor_ids()
        logger.info("tbc_factor_ids_count", extra={"count": len(ids)})
        for fid in ids:
            logger.info("tbc_factor_id", extra={"factor_id": fid, "url": _TBC_FACTOR_URLS[fid]})
        return

    if args.check_hash:
        file_map: dict[str, Path] = {
            "defra": raw_dir / _DEFRA_FILE,
            "ispra": raw_dir / _ISPRA_FILE,
            "aib": raw_dir / _AIB_FILE,
            "ecoinvent": raw_dir / _ECOINVENT_FILE,
        }
        path = file_map[args.check_hash]
        digest = compute_sha256(path)
        logger.info("file_sha256", extra={"source": args.check_hash, "digest": digest})
        return

    if args.apply:
        result = load_all_seeds(raw_dir=raw_dir, skip_pdf=args.skip_pdf)
        import json

        # explicit stdout for machine-parseable output
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
        if result["status"] != "OK":
            raise SystemExit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    _main()
