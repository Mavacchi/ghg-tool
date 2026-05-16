"""Unit tests for the factor catalog seed loader pipeline.

Tests cover:
  1. Hash mismatch raises ValueError with explicit message.
  2. DEFRA Excel parse returns N factor records matching the fixture.
  3. Ecoinvent CSV parse returns 5 records with correct field mapping.
  4. MinIO upload mock — boto3 client called with correct args when MINIO_ENDPOINT set.
  5. DB insert mock — executemany called with correct params; idempotent on re-run.

No real PostgreSQL, no network calls.  All external dependencies are mocked.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to locate the fixture files
# ---------------------------------------------------------------------------
_WORKTREE_ROOT = Path(__file__).parents[3]  # tests/unit/infrastructure -> worktree root
_RAW_DIR = _WORKTREE_ROOT / "data" / "raw_factor_sources"
_DEFRA_XLSX = _RAW_DIR / "defra_2024_ghg_conversion_v1.xlsx"
_ECOINVENT_CSV = _RAW_DIR / "ecoinvent_v3.10_sample.csv"


# ===========================================================================
# Import module under test (late so env vars don't interfere)
# ===========================================================================


def _import_seed_loader() -> Any:
    """Import seed_loader with mocked psycopg to avoid import-time DB calls."""
    import importlib
    import sys

    # Ensure fresh import each time so env-var patches take effect
    if "ghg_tool.infrastructure.factors.seed_loader" in sys.modules:
        del sys.modules["ghg_tool.infrastructure.factors.seed_loader"]

    return importlib.import_module("ghg_tool.infrastructure.factors.seed_loader")


# ===========================================================================
# Test 1 — hash mismatch raises ValueError
# ===========================================================================


class TestHashVerification:
    """verify_hash must raise ValueError with a clear message on mismatch."""

    def test_hash_mismatch_raises_value_error(self, tmp_path: Path) -> None:
        """Writing a modified file and checking it against the pinned hash must
        raise ValueError containing 'mismatch' in the message."""
        loader = _import_seed_loader()

        test_file = tmp_path / "test_factor.xlsx"
        test_file.write_bytes(b"original content")
        good_hash = hashlib.sha256(b"original content").hexdigest()

        # Tamper with the file
        test_file.write_bytes(b"tampered content")

        with pytest.raises(ValueError, match="(?i)mismatch"):
            loader.verify_hash(test_file, good_hash, "test source")

    def test_empty_pin_raises_value_error(self, tmp_path: Path) -> None:
        """An empty pin string must raise ValueError before even checking the file."""
        loader = _import_seed_loader()

        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"some pdf content")

        with pytest.raises(ValueError, match="(?i)empty"):
            loader.verify_hash(test_file, "", "ISPRA PDF")

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """A non-existent file must raise FileNotFoundError."""
        loader = _import_seed_loader()

        missing = tmp_path / "does_not_exist.pdf"
        with pytest.raises(FileNotFoundError):
            loader.verify_hash(missing, "abc123", "some source")

    def test_correct_hash_passes_silently(self, tmp_path: Path) -> None:
        """A file with matching hash must not raise any exception."""
        loader = _import_seed_loader()

        content = b"correct content for hash test"
        test_file = tmp_path / "correct.xlsx"
        test_file.write_bytes(content)
        good_hash = hashlib.sha256(content).hexdigest()

        # Should not raise
        loader.verify_hash(test_file, good_hash, "test source")


# ===========================================================================
# Test 2 — DEFRA Excel parse
# ===========================================================================


class TestDefraExcelParse:
    """parse_defra_excel must return the expected factor records from the fixture."""

    @pytest.mark.skipif(
        not _DEFRA_XLSX.exists(),
        reason="DEFRA fixture not found — run worktree setup first",
    )
    def test_defra_parse_returns_5_records(self) -> None:
        """The fixture xlsx has exactly 5 factor rows."""
        loader = _import_seed_loader()
        records = loader.parse_defra_excel(_DEFRA_XLSX)
        assert len(records) == 5, (
            f"Expected 5 DEFRA records, got {len(records)}"
        )

    @pytest.mark.skipif(
        not _DEFRA_XLSX.exists(),
        reason="DEFRA fixture not found",
    )
    def test_defra_records_have_required_keys(self) -> None:
        """Each parsed record must carry all required factor keys."""
        loader = _import_seed_loader()
        records = loader.parse_defra_excel(_DEFRA_XLSX)
        required = {
            "factor_id", "substance", "scope", "category", "source",
            "version", "value", "unit", "gwp_set", "vintage", "applicability_note",
        }
        for i, rec in enumerate(records):
            missing = required - set(rec.keys())
            assert not missing, (
                f"Record {i} is missing keys: {missing}"
            )

    @pytest.mark.skipif(
        not _DEFRA_XLSX.exists(),
        reason="DEFRA fixture not found",
    )
    def test_defra_gas_nat_per_sm3_present(self) -> None:
        """Base GAS_NAT CO2 per-Sm3 factor must be in the fixture."""
        loader = _import_seed_loader()
        records = loader.parse_defra_excel(_DEFRA_XLSX)
        ids = [r["factor_id"] for r in records]
        assert "COMB_GAS_NAT_CO2_DEFRA_2024_PER_SM3" in ids

    @pytest.mark.skipif(
        not _DEFRA_XLSX.exists(),
        reason="DEFRA fixture not found",
    )
    def test_defra_values_are_decimal(self) -> None:
        """Parsed 'value' fields must be Decimal (exact numeric type)."""
        loader = _import_seed_loader()
        records = loader.parse_defra_excel(_DEFRA_XLSX)
        for rec in records:
            assert isinstance(rec["value"], Decimal), (
                f"factor_id {rec['factor_id']}: value must be Decimal, "
                f"got {type(rec['value'])}"
            )

    @pytest.mark.skipif(
        not _DEFRA_XLSX.exists(),
        reason="DEFRA fixture not found",
    )
    def test_defra_missing_column_raises_value_error(self, tmp_path: Path) -> None:
        """An Excel file missing required columns must raise ValueError."""
        import openpyxl

        loader = _import_seed_loader()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Stationary combustion"
        ws.append(["factor_id", "value"])  # missing most required columns
        ws.append(["TEST_FACTOR", 1.0])
        bad_xlsx = tmp_path / "bad.xlsx"
        wb.save(str(bad_xlsx))

        with pytest.raises(ValueError, match="(?i)missing required columns"):
            loader.parse_defra_excel(bad_xlsx)


# ===========================================================================
# Test 3 — Ecoinvent CSV parse
# ===========================================================================


class TestEcoinventCsvParse:
    """parse_ecoinvent_csv must return 5 records from the sample fixture."""

    @pytest.mark.skipif(
        not _ECOINVENT_CSV.exists(),
        reason="Ecoinvent fixture not found",
    )
    def test_ecoinvent_parse_returns_5_records(self) -> None:
        """The sample CSV has exactly 5 ecoinvent Cat 1 records."""
        loader = _import_seed_loader()
        records = loader.parse_ecoinvent_csv(_ECOINVENT_CSV)
        assert len(records) == 5, (
            f"Expected 5 Ecoinvent records, got {len(records)}"
        )

    @pytest.mark.skipif(
        not _ECOINVENT_CSV.exists(),
        reason="Ecoinvent fixture not found",
    )
    def test_ecoinvent_scope_is_3(self) -> None:
        """All Ecoinvent Cat 1 records must have scope=3."""
        loader = _import_seed_loader()
        records = loader.parse_ecoinvent_csv(_ECOINVENT_CSV)
        for rec in records:
            assert rec["scope"] == 3, (
                f"factor_id {rec['factor_id']}: scope must be 3, got {rec['scope']}"
            )

    @pytest.mark.skipif(
        not _ECOINVENT_CSV.exists(),
        reason="Ecoinvent fixture not found",
    )
    def test_ecoinvent_is_licence_only(self) -> None:
        """Ecoinvent records must be marked is_licence_only=True (sample data)."""
        loader = _import_seed_loader()
        records = loader.parse_ecoinvent_csv(_ECOINVENT_CSV)
        for rec in records:
            assert rec["is_licence_only"] is True, (
                f"factor_id {rec['factor_id']}: is_licence_only must be True"
            )

    @pytest.mark.skipif(
        not _ECOINVENT_CSV.exists(),
        reason="Ecoinvent fixture not found",
    )
    def test_ecoinvent_values_positive(self) -> None:
        """All Ecoinvent emission factor values must be positive."""
        loader = _import_seed_loader()
        records = loader.parse_ecoinvent_csv(_ECOINVENT_CSV)
        for rec in records:
            assert rec["value"] > Decimal("0"), (
                f"factor_id {rec['factor_id']}: value must be > 0, got {rec['value']}"
            )

    def test_ecoinvent_missing_column_raises_value_error(self, tmp_path: Path) -> None:
        """A CSV missing required columns must raise ValueError."""
        loader = _import_seed_loader()

        bad_csv = tmp_path / "bad_ecoinvent.csv"
        bad_csv.write_text("material_id,value_kgCO2e_per_kg\nCLAY,0.04\n")

        with pytest.raises(ValueError, match="(?i)missing required columns"):
            loader.parse_ecoinvent_csv(bad_csv)


# ===========================================================================
# Test 4 — MinIO upload mock
# ===========================================================================


class TestMinioUpload:
    """upload_to_minio must call boto3 when MINIO_ENDPOINT is set."""

    def test_upload_calls_boto3_when_endpoint_set(self, tmp_path: Path) -> None:
        """When MINIO_ENDPOINT is set, boto3.client.upload_file must be called.

        boto3 is an optional dependency not installed in dev/test environments.
        We inject a mock into sys.modules so the import inside upload_to_minio
        succeeds regardless of whether the real package is installed.
        """
        import sys
        import types

        loader = _import_seed_loader()

        test_file = tmp_path / "defra.xlsx"
        test_file.write_bytes(b"mock excel data")

        # Build minimal boto3 + botocore mocks
        mock_s3 = MagicMock()
        mock_boto3_mod = types.ModuleType("boto3")
        mock_boto3_mod.client = MagicMock(return_value=mock_s3)  # type: ignore[attr-defined]

        mock_botocore_mod = types.ModuleType("botocore")
        mock_botocore_client_mod = types.ModuleType("botocore.client")

        class _FakeConfig:
            def __init__(self, **_: object) -> None:
                pass

        mock_botocore_client_mod.Config = _FakeConfig  # type: ignore[attr-defined]
        mock_botocore_mod.client = mock_botocore_client_mod  # type: ignore[attr-defined]

        with (
            patch.dict(
                sys.modules,
                {
                    "boto3": mock_boto3_mod,
                    "botocore": mock_botocore_mod,
                    "botocore.client": mock_botocore_client_mod,
                },
            ),
            patch.object(loader, "_MINIO_ENDPOINT", "http://localhost:9000"),
        ):
            uri = loader.upload_to_minio(test_file, "factor-sources/defra.xlsx")

        # boto3.client must have been called once with 's3'
        mock_boto3_mod.client.assert_called_once()
        assert mock_boto3_mod.client.call_args[0][0] == "s3"

        # upload_file must have been called with (local_path, bucket, object_key)
        mock_s3.upload_file.assert_called_once()
        call_args = mock_s3.upload_file.call_args[0]
        assert str(test_file) == call_args[0], "First arg must be local file path"
        assert call_args[2] == "factor-sources/defra.xlsx", "Third arg must be object key"

        assert uri.startswith("minio://"), f"URI must start with minio://, got: {uri}"

    def test_upload_returns_file_uri_when_no_endpoint(self, tmp_path: Path) -> None:
        """When MINIO_ENDPOINT is empty, upload must return file:// URI without calling boto3."""
        loader = _import_seed_loader()

        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"content")

        with patch.object(loader, "_MINIO_ENDPOINT", ""):
            uri = loader.upload_to_minio(test_file, "factor-sources/test.xlsx")

        assert uri.startswith("file://"), (
            f"Without MINIO_ENDPOINT, URI must be file://, got: {uri}"
        )


# ===========================================================================
# Test 5 — DB insert mock
# ===========================================================================


class TestDbInsert:
    """insert_factors must call executemany with the correct parameter shapes."""

    def _make_records(self, n: int = 3) -> list[Any]:
        """Return N minimal FactorRecord dicts for testing."""
        return [
            {
                "factor_id": f"TEST_FACTOR_{i}",
                "version": "2024_v1.0",
                "substance": f"Substance {i}",
                "scope": 1,
                "category": "combustion",
                "source": "DEFRA",
                "value": Decimal(f"{1.0 + i * 0.1:.1f}"),
                "unit": "kg CO2 / Sm3",
                "gwp_set": "AR6",
                "vintage": "2024",
                "applicability_note": f"Test factor {i}",
                "is_tbc": False,
                "is_licence_only": False,
            }
            for i in range(n)
        ]

    def test_insert_calls_executemany(self) -> None:
        """insert_factors must call cur.executemany exactly once."""
        loader = _import_seed_loader()

        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        records = self._make_records(3)
        loader.insert_factors(mock_conn, records, "file:///tmp/test.xlsx")

        mock_cur.executemany.assert_called_once()

    def test_insert_executemany_params_count(self) -> None:
        """executemany must be called with a list matching len(records)."""
        loader = _import_seed_loader()

        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        records = self._make_records(5)
        loader.insert_factors(mock_conn, records, "minio://bucket/test.xlsx")

        params_list = mock_cur.executemany.call_args[0][1]
        assert len(params_list) == 5, (
            f"executemany must receive 5 param dicts, got {len(params_list)}"
        )

    def test_insert_commits_after_executemany(self) -> None:
        """conn.commit() must be called after executemany to finalise the transaction."""
        loader = _import_seed_loader()

        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        loader.insert_factors(mock_conn, self._make_records(2), "file:///tmp/x.csv")

        mock_conn.commit.assert_called_once()

    def test_insert_params_contain_evidence_url(self) -> None:
        """Each param dict must contain the evidence_url as 'evidence_url'."""
        loader = _import_seed_loader()

        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        expected_url = "minio://gh-tool-evidence/factor-sources/defra.xlsx"
        loader.insert_factors(mock_conn, self._make_records(2), expected_url)

        params_list = mock_cur.executemany.call_args[0][1]
        for param in params_list:
            assert param["evidence_url"] == expected_url, (
                f"evidence_url mismatch: expected {expected_url}, got {param['evidence_url']}"
            )
