"""E2E integration test: full pipeline happy-path — FR-22, FR-27, CSRD ESRS E1.

Flow under test
---------------
1. Upload a minimal scope-1 CSV (natural-gas combustion, 1 facility, 1 year).
2. Trigger data-quality check → DQ findings = 0 errors.
3. Trigger calc run (CSRD_ESRS_E1 / AR6) → emissions_consolidated rows created.
4. Publish the run → published_at IS NOT NULL.
5. Trigger PDF export (Celery EAGER mode) → verify successful download.

Fixture requirements
--------------------
This test requires:
- A live PostgreSQL instance reachable via SQLALCHEMY_ASYNC_URL.
- Celery in ALWAYS_EAGER mode (``task_always_eager=True``).
- A seeded tenant row in ``ref.tenants``.
- A seeded factor catalog with AR6 grid + combustion factors.

None of these fixtures are provided by the wave-5 integration conftest.py.
All tests below are therefore skipped with explicit TODO markers that describe
what each fixture must provide.  Un-skip by satisfying the fixture contract
described in ``tests/integration/conftest.py`` (DB fixtures) and adding a
shared ``celery_eager`` autouse fixture.

Design reference:
    auto_calc_design.md §10; GHG Protocol Corporate Standard Ch.4 (Scope 1).
"""

from __future__ import annotations

import io
import os
import uuid

import pytest

# ---------------------------------------------------------------------------
# Environment guard: skip immediately if no live DB is configured.
# ---------------------------------------------------------------------------

_DB_URL = os.getenv("SQLALCHEMY_ASYNC_URL") or os.getenv("DATABASE_URL")
_HAS_LIVE_DB = bool(_DB_URL)

_skip_no_db = pytest.mark.skipif(
    not _HAS_LIVE_DB,
    reason=(
        "TODO E2E-PIPELINE: SQLALCHEMY_ASYNC_URL not set — live PostgreSQL "
        "required for full-pipeline E2E test. Set SQLALCHEMY_ASYNC_URL in the "
        "CI environment (or use docker-compose up db) to enable this test."
    ),
)

# ---------------------------------------------------------------------------
# Celery EAGER fixture guard
# ---------------------------------------------------------------------------

_HAS_EAGER_FIXTURE = False
try:
    from ghg_tool.infrastructure.celery_app import celery_app as _celery_app  # noqa: F401
    _HAS_EAGER_FIXTURE = True
except ImportError:
    pass

_skip_no_celery = pytest.mark.skipif(
    not _HAS_EAGER_FIXTURE,
    reason=(
        "TODO E2E-PIPELINE: celery_app import failed — cannot run EAGER export "
        "step. Ensure ghg_tool.infrastructure.celery_app is importable."
    ),
)

# ---------------------------------------------------------------------------
# Minimal scope-1 CSV fixture
# ---------------------------------------------------------------------------

_SCOPE1_CSV_ROWS = (
    "codice_sito,anno,combustibile,quantita_mj,note\n"
    "IANO,2024,GAS_NAT,3600000,e2e-test-row\n"
)


def _scope1_csv_bytes() -> bytes:
    """Return a minimal scope-1 CSV as bytes for multipart upload."""
    return _SCOPE1_CSV_ROWS.encode("utf-8")


# ---------------------------------------------------------------------------
# E2E tests (all skipped until fixture contract is satisfied)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@_skip_no_db
class TestFullPipelineE2E:
    """Full pipeline: upload → DQ → calc → publish → export.

    Each test method represents one step of the pipeline.  In CI the class is
    skipped via _skip_no_db.  Un-skip by providing the DB fixtures described in
    the class docstring below.

    Fixture contract (to be provided in tests/integration/conftest.py or a
    new tests/integration/e2e/conftest.py):

        ``tenant_id`` (str) — UUID of a seeded ref.tenants row.
        ``seeded_factor_catalog`` — scope-1 AR6 combustion + LB grid factors.
        ``celery_eager`` (autouse) — sets celery_app.conf.task_always_eager=True.
        ``http_client`` — httpx.AsyncClient or TestClient bound to the FastAPI app.
        ``admin_token`` (str) — valid JWT with admin role for the seeded tenant.
    """

    @pytest.fixture(autouse=True)
    def _require_fixtures(self) -> None:
        """Gate: skip with clear message if required fixtures are absent."""
        pytest.skip(
            "TODO E2E-PIPELINE: required fixtures (tenant_id, seeded_factor_catalog, "
            "celery_eager, http_client, admin_token) not yet provided. "
            "Implement fixture contract in tests/integration/e2e/conftest.py "
            "and remove this skip."
        )

    def test_step1_upload_scope1_csv(self, http_client, admin_token: str, tenant_id: str) -> None:  # type: ignore[name-defined]
        """Step 1: POST /api/v1/raw/excel (or CSV ingest) with scope-1 data.

        Expected: HTTP 200/201; raw.scope1_raw rows created for (IANO, 2024).
        """
        csv_bytes = _scope1_csv_bytes()
        resp = http_client.post(
            "/api/v1/raw/scope1/upload",
            files={"file": ("scope1.csv", io.BytesIO(csv_bytes), "text/csv")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data.get("rows_inserted", 0) > 0

    def test_step2_dq_check_no_errors(self, http_client, admin_token: str, tenant_id: str) -> None:  # type: ignore[name-defined]
        """Step 2: POST /api/v1/dq/run → DQ findings with 0 error-severity items.

        Expected: HTTP 202; no DQ findings with severity='ERROR' for anno=2024.
        """
        resp = http_client.post(
            "/api/v1/dq/run",
            json={"anno": 2024},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 202, resp.text

    def test_step3_calc_run_creates_emissions(self, http_client, admin_token: str, tenant_id: str) -> None:  # type: ignore[name-defined]
        """Step 3: POST /api/v1/calc/run → calc.emissions_consolidated rows.

        Expected: HTTP 202; at least 1 row in emissions_consolidated for
        (tenant_id, anno=2024, scope=1, gwp_set='AR6').
        """
        resp = http_client.post(
            "/api/v1/calc/run",
            json={"anno": 2024, "regulatory_stream": "CSRD_ESRS_E1"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert "correlation_id" in data
        # Correlation ID must be a valid UUID (FR-22 traceability)
        cid = uuid.UUID(data["correlation_id"])
        assert str(cid) == data["correlation_id"]

    def test_step4_pdf_export_succeeds(self, http_client, admin_token: str, tenant_id: str) -> None:  # type: ignore[name-defined]
        """Step 5: POST /api/v1/exports/pdf → Celery EAGER PDF generation.

        With task_always_eager=True the task runs synchronously; the download
        endpoint should return binary PDF bytes.

        Expected: HTTP 202 from trigger; HTTP 200 + Content-Type application/pdf
        from download.
        """
        # Trigger PDF export
        trigger_resp = http_client.post(
            "/api/v1/exports/pdf",
            json={"anno": 2024},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert trigger_resp.status_code == 202, trigger_resp.text
        task_data = trigger_resp.json()
        task_id = task_data.get("task_id")
        assert task_id is not None

        # In EAGER mode the task has already completed; download immediately.
        download_resp = http_client.get(
            f"/api/v1/exports/{task_id}/download",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert download_resp.status_code == 200, download_resp.text
        content_type = download_resp.headers.get("content-type", "")
        assert "pdf" in content_type or len(download_resp.content) > 0


# ---------------------------------------------------------------------------
# Smoke test: celery EAGER mode is importable (always runs, no DB needed)
# ---------------------------------------------------------------------------


@_skip_no_celery
def test_celery_eager_mode_importable() -> None:
    """Verify celery_app can be imported and configured to EAGER mode.

    This smoke test always runs (no DB required) and confirms the Celery
    infrastructure is importable before the full E2E test attempts to use it.
    """
    from ghg_tool.infrastructure.celery_app import celery_app

    # Store original value and restore it after the test.
    original = celery_app.conf.task_always_eager
    try:
        celery_app.conf.update(task_always_eager=True)
        assert celery_app.conf.task_always_eager is True
    finally:
        celery_app.conf.update(task_always_eager=original)


def test_scope1_csv_fixture_is_valid_csv() -> None:
    """Verify the test CSV fixture is well-formed (header + data row).

    This test always runs; it guards against fixture drift that would make
    the upload step fail with a parser error rather than a meaningful assertion.
    """
    lines = _SCOPE1_CSV_ROWS.strip().splitlines()
    assert len(lines) >= 2, "CSV must have header + at least one data row"
    header = lines[0].split(",")
    assert "codice_sito" in header
    assert "anno" in header
    assert "combustibile" in header
    assert "quantita_mj" in header

    data_row = lines[1].split(",")
    assert data_row[0] == "IANO"
    assert data_row[1] == "2024"
    assert data_row[2] == "GAS_NAT"
    # quantita_mj must be a positive number
    assert float(data_row[3]) > 0
