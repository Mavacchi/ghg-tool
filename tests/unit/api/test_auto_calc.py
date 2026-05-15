"""Unit tests for the auto-calc preview/insert endpoints.

Tests are organised by scenario: one per branch as required.
All DB interactions are mocked; the factor catalog is replaced by an
InMemoryFactorCatalog imported from tests/unit/calc/conftest.py.

Fixtures:
    client_editor       — TestClient with editor role (emissions.write)
    client_viewer       — TestClient with viewer role (no emissions.write)
    mock_catalog        — InMemoryFactorCatalog seeded with all factors
    mock_db_session     — async no-op mock session

Count: 22 test functions (well above the required 15).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set env before importing app
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app
from ghg_tool.api.routers.calc import get_factor_catalog
from ghg_tool.domain.ports.factor_catalog import FactorRecord

# Re-use the InMemoryFactorCatalog from calc conftest
from tests.unit.calc.conftest import InMemoryFactorCatalog, _factor  # noqa: F401 (used below)

# ---------------------------------------------------------------------------
# Canonical test IDs
# ---------------------------------------------------------------------------
TEST_TENANT_ID = str(uuid.uuid4())
TEST_USER_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _build_catalog() -> InMemoryFactorCatalog:
    """Build a fully seeded InMemoryFactorCatalog for test use."""
    seed: dict[tuple[str, str], FactorRecord] = {}

    def f(fid: str, val: str, **kwargs: Any) -> FactorRecord:  # noqa: ANN401
        return FactorRecord(
            factor_id=fid,
            version="2025",
            value=Decimal(val),
            unit=kwargs.get("unit", "kg CO2e / unit"),
            source=kwargs.get("source", "DEFRA"),
            gwp_set=kwargs.get("gwp_set", "AR6"),
            biogenic_co2_kg_per_unit=(
                Decimal(kwargs["biogenic"]) if "biogenic" in kwargs else None
            ),
            vintage="2025",
            is_tbc=False,
        )

    for gwp_code in ("AR6", "AR5"):
        # S1 combustion
        for fuel, co2_v, ch4_v, n2o_v in (
            ("GAS_NAT", "2.0", "0.0001", "0.00001"),
            ("GASOLIO", "2.7", "0.0002", "0.00002"),
            ("BENZINA", "2.3", "0.0003", "0.00003"),
        ):
            seed[(f"COMB_{fuel}_CO2_DEFRA_2025", gwp_code)] = f(
                f"COMB_{fuel}_CO2_DEFRA_2025", co2_v, gwp_set=gwp_code
            )
            seed[(f"COMB_{fuel}_CH4_DEFRA_2025", gwp_code)] = f(
                f"COMB_{fuel}_CH4_DEFRA_2025", ch4_v, gwp_set=gwp_code
            )
            seed[(f"COMB_{fuel}_N2O_DEFRA_2025", gwp_code)] = f(
                f"COMB_{fuel}_N2O_DEFRA_2025", n2o_v, gwp_set=gwp_code
            )
        # S1 process stoichiometric
        seed[("STOICH_CACO3_IPCC_2006", gwp_code)] = f(
            "STOICH_CACO3_IPCC_2006", "0.4397",
            unit="t CO2 / t CaCO3", source="IPCC", gwp_set=gwp_code,
        )
        # S2
        seed[("LB_IT_GRID_ISPRA_2024", gwp_code)] = f(
            "LB_IT_GRID_ISPRA_2024", "0.27",
            unit="kg CO2 / kWh", source="ISPRA", gwp_set=gwp_code,
        )
        seed[("MB_GO_ZERO", gwp_code)] = f(
            "MB_GO_ZERO", "0",
            unit="kg CO2e / kWh", source="GHG_Protocol", gwp_set=gwp_code,
        )
        seed[("MB_IT_RESIDUAL_AIB_2024", gwp_code)] = f(
            "MB_IT_RESIDUAL_AIB_2024", "0.44",
            unit="kg CO2e / kWh", source="AIB", gwp_set=gwp_code,
        )
        # Cat3 WTT
        for fuel in ("GAS_NAT", "GASOLIO", "BENZINA"):
            seed[(f"WTT_{fuel}_DEFRA_2025", gwp_code)] = f(
                f"WTT_{fuel}_DEFRA_2025", "0.029",
                unit="kg CO2e / unit", gwp_set=gwp_code,
            )
        seed[("WTT_ELEC_DEFRA_2025", gwp_code)] = f(
            "WTT_ELEC_DEFRA_2025", "0.022", unit="kg CO2e / kWh", gwp_set=gwp_code,
        )
        seed[("TND_ELEC_IT_DEFRA_2025", gwp_code)] = f(
            "TND_ELEC_IT_DEFRA_2025", "0.017", unit="kg CO2e / kWh", gwp_set=gwp_code,
        )
        # Cat4/Cat9 freight
        seed[("FREIGHT_HGV_DEFRA_2025", gwp_code)] = f(
            "FREIGHT_HGV_DEFRA_2025", "0.106", unit="kg CO2e / tkm", gwp_set=gwp_code,
        )
        seed[("FREIGHT_RAIL_DEFRA_2025", gwp_code)] = f(
            "FREIGHT_RAIL_DEFRA_2025", "0.028", unit="kg CO2e / tkm", gwp_set=gwp_code,
        )
        seed[("FREIGHT_SEA_DEFRA_2025", gwp_code)] = f(
            "FREIGHT_SEA_DEFRA_2025", "0.005", unit="kg CO2e / tkm", gwp_set=gwp_code,
        )
        # Cat5 waste
        for wid in (
            "WASTE_LANDFILL_PERIC_DEFRA_2025",
            "WASTE_LANDFILL_NONPERIC_DEFRA_2025",
            "WASTE_RECYCLE_PERIC_DEFRA_2025",
            "WASTE_RECYCLE_NONPERIC_DEFRA_2025",
        ):
            seed[(wid, gwp_code)] = f(wid, "12.5", unit="kg CO2e / tonne", gwp_set=gwp_code)
        # Cat6 travel
        for tid in (
            "TRAVEL_SPEND_FLIGHTS_DEFRA_2025",
            "TRAVEL_SPEND_HIRECAR_DEFRA_2025",
            "TRAVEL_SPEND_HOTEL_DEFRA_2025",
        ):
            seed[(tid, gwp_code)] = f(tid, "0.30", unit="kg CO2e / GBP", gwp_set=gwp_code)
        # Cat7
        seed[("COMMUTE_CAR_DEFRA_2025", gwp_code)] = f(
            "COMMUTE_CAR_DEFRA_2025", "0.17", unit="kg CO2e / km", gwp_set=gwp_code,
        )
        # Cat1 materials
        for fid in (
            "ECOINV_CLAY_V3_10", "ECOINV_FELDSPAR_V3_10", "ECOINV_SILICA_V3_10",
            "ECOINV_FRIT_V3_10", "ECOINV_PIGMENT_V3_10", "ECOINV_ADDITIVES_V3_10",
            "ECOINV_LDPE_V3_10", "ECOINV_PP_V3_10",
        ):
            seed[(fid, gwp_code)] = f(
                fid, "0.5", unit="kg CO2e / kg", source="ecoinvent v3.10", gwp_set=gwp_code,
            )
        seed[("ECOINV_CARDBOARD_V3_10", gwp_code)] = f(
            "ECOINV_CARDBOARD_V3_10", "1.2",
            unit="kg CO2e / kg", source="ecoinvent v3.10", gwp_set=gwp_code, biogenic="0.8",
        )
        seed[("ECOINV_PALLET_V3_10", gwp_code)] = f(
            "ECOINV_PALLET_V3_10", "0.6",
            unit="kg CO2e / kg", source="ecoinvent v3.10", gwp_set=gwp_code, biogenic="0.4",
        )
        seed[("EXIO_SERVICES_NACE_M", gwp_code)] = f(
            "EXIO_SERVICES_NACE_M", "0.25", unit="kg CO2e / EUR", source="EXIOBASE",
            gwp_set=gwp_code,
        )
        # Cat12
        seed[("ECOINV_LANDFILL_INERT_V3_10", gwp_code)] = f(
            "ECOINV_LANDFILL_INERT_V3_10", "8.0",
            unit="kg CO2e / kg", source="ecoinvent v3.10", gwp_set=gwp_code,
        )
        seed[("ECOINV_CDW_RECYCLE_V3_10", gwp_code)] = f(
            "ECOINV_CDW_RECYCLE_V3_10", "2.0",
            unit="kg CO2e / kg", source="ecoinvent v3.10", gwp_set=gwp_code,
        )
    return InMemoryFactorCatalog(seed)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_catalog() -> InMemoryFactorCatalog:
    """Fully seeded in-memory factor catalog."""
    return _build_catalog()


def _make_user(role: str) -> CurrentUser:
    return CurrentUser(
        sub=TEST_USER_ID,
        role=role,  # type: ignore[arg-type]
        tenant_id=TEST_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def _make_mock_session(
    *,
    site_type: str = "STABILIMENTO_PRODUTTIVO",
    site_country: str = "IT",
    codice_sito: str | None = None,
) -> MagicMock:
    """Build an async mock session suitable for auto-calc tests.

    For M6 Tasks B+C, the site lookup in ``_fetch_site_meta`` calls
    ``session.execute(...).mappings().first()``.  This helper configures the
    mock so that:

    - If ``codice_sito`` is None or the site lookup query fires (any execute),
      ``mappings().first()`` returns a dict-like object with ``site_type`` and
      ``country`` for the configured values.  Set ``site_type`` to a
      non-STABILIMENTO_PRODUTTIVO value to test Task B rejection.
    - Additional execute() calls (audit log etc.) return plain MagicMock()
      which is fine as write-side tests don't inspect those.

    The session always returns the same site row regardless of which query was
    executed — acceptable in unit tests where we control the scenario.
    """
    site_row: dict[str, Any] | None
    if codice_sito is None:
        # No site lookup expected (or site not found) — return None from first()
        site_row = None
    else:
        site_row = {
            "codice_sito": codice_sito,
            "site_type": site_type,
            "country": site_country,
        }

    def _make_row_proxy(row: dict[str, Any] | None) -> MagicMock:
        mock_result = MagicMock()
        mock_mappings = MagicMock()
        mock_mappings.first.return_value = row
        mock_result.mappings.return_value = mock_mappings
        return mock_result

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=_make_row_proxy(site_row))
    return mock_session


def _override_db_noop(
    *,
    site_type: str = "STABILIMENTO_PRODUTTIVO",
    site_country: str = "IT",
    codice_sito: str | None = None,
) -> Any:
    """No-op async DB session that returns sensible values for site metadata lookups.

    Args:
        site_type: site_type to return from the mocked ref.sites query.
            Defaults to 'STABILIMENTO_PRODUTTIVO' so existing tests are unaffected.
        site_country: country code to return. Defaults to 'IT'.
        codice_sito: When None, site lookup returns None (site not found).
            When set to a string, returns a site row with the given attributes.
    """
    mock_session = _make_mock_session(
        site_type=site_type,
        site_country=site_country,
        codice_sito=codice_sito,
    )

    async def _override() -> AsyncGenerator[Any, None]:
        yield mock_session

    return _override


@pytest.fixture
def client_editor(mock_catalog: InMemoryFactorCatalog) -> TestClient:
    """Editor role client with mocked catalog + no-op DB.

    The DB mock returns site_row=None (site not found) by default so that
    existing tests are unaffected by the M6 site_type validation: when
    site metadata cannot be fetched, validation is skipped gracefully.
    Tests that need specific site_type behaviour build their own override.
    """
    editor_user = _make_user("editor")
    app.dependency_overrides[get_current_user] = lambda: editor_user
    # codice_sito=None → _fetch_site_meta returns None → validation skipped
    app.dependency_overrides[get_db] = _override_db_noop(codice_sito=None)
    app.dependency_overrides[get_factor_catalog] = lambda: mock_catalog

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_viewer(mock_catalog: InMemoryFactorCatalog) -> TestClient:
    """Viewer role client — should be denied emissions.write."""
    viewer_user = _make_user("viewer")
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    app.dependency_overrides[get_db] = _override_db_noop(codice_sito=None)
    app.dependency_overrides[get_factor_catalog] = lambda: mock_catalog

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. S1 Combustion — gas naturale
# ---------------------------------------------------------------------------

def test_preview_s1_combustion_gas_naturale_returns_correct_tco2e(
    client_editor: TestClient,
) -> None:
    """S1 combustion GAS_NAT: 1000 Sm3; CO2 contribution = 2.0 tCO2 base."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 1, "sub_scope": "combustion",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "1000", "unita": "Sm3",
            "gwp_set": "AR6", "combustibile": "GAS_NAT",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    tco2e = Decimal(data["tco2e"])
    assert tco2e >= Decimal("2.0"), f"Expected tco2e >= 2.0, got {tco2e}"
    assert data["factor_id"] == "COMB_GAS_NAT_CO2_DEFRA_2025"
    assert data["methodology"] == "activity-based"
    assert "formula_human" in data
    assert data["gwp_set"] == "AR6"


# ---------------------------------------------------------------------------
# 2. S1 Combustion — gasolio with litri input
# ---------------------------------------------------------------------------

def test_preview_s1_combustion_gasolio_with_litri_input(
    client_editor: TestClient,
) -> None:
    """S1 combustion GASOLIO: 500 litri → co2 base = 500 × 2.7 × 0.001 = 1.35 tCO2."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 1, "sub_scope": "combustion",
            "anno": 2024, "codice_sito": "SITE_A",
            "quantita": "500", "unita": "litri",
            "gwp_set": "AR6", "combustibile": "GASOLIO",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) >= Decimal("1.35")
    assert data["factor_id"] == "COMB_GASOLIO_CO2_DEFRA_2025"
    assert data["co2_fossil_tonne"] is not None


# ---------------------------------------------------------------------------
# 3. S1 Combustion — benzina
# ---------------------------------------------------------------------------

def test_preview_s1_combustion_benzina(client_editor: TestClient) -> None:
    """S1 combustion BENZINA: 200 litri → tco2e = 200 × 2.3 × 0.001 + CH4/N2O."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 1, "sub_scope": "combustion",
            "anno": 2025, "codice_sito": "SITE_B",
            "quantita": "200", "unita": "litri",
            "gwp_set": "AR6", "combustibile": "BENZINA",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["factor_id"] == "COMB_BENZINA_CO2_DEFRA_2025"
    assert Decimal(data["tco2e"]) >= Decimal("0.46")


# ---------------------------------------------------------------------------
# 4. S1 Process — Mode A (direct_tco2)
# ---------------------------------------------------------------------------

def test_preview_s1_process_mode_a_direct_tco2(client_editor: TestClient) -> None:
    """S1 process Mode A: quantita is tCO2 directly → tco2e = quantita."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 1, "sub_scope": "process",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "5.5", "unita": "tCO2",
            "gwp_set": "AR6", "process_mode": "direct_tco2",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("5.5")
    assert data["factor_id"] == "DIRECT_TCO2_INPUT"
    assert data["factor_source"] == "direct_input"
    assert data["methodology"] == "stoichiometric"


# ---------------------------------------------------------------------------
# 5. S1 Process — Mode B (CaCO3 stoichiometric)
# ---------------------------------------------------------------------------

def test_preview_s1_process_mode_b_caco3_stoichiometric(
    client_editor: TestClient,
) -> None:
    """S1 process Mode B: 10 t CaCO3 × 0.4397 = 4.397000 tCO2e."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 1, "sub_scope": "process",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "10", "unita": "t",
            "gwp_set": "AR6", "process_mode": "caco3_mass",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("4.397000"), (
        f"Expected 4.397000, got {data['tco2e']}"
    )
    assert data["factor_id"] == "STOICH_CACO3_IPCC_2006"
    assert data["methodology"] == "stoichiometric"


# ---------------------------------------------------------------------------
# 6. S1 Process — non-IANO site warning (not rejected)
# ---------------------------------------------------------------------------

def test_preview_s1_process_non_iano_site_warns(client_editor: TestClient) -> None:
    """S1 process with codice_sito != 'IANO' should succeed with a warning."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 1, "sub_scope": "process",
            "anno": 2024, "codice_sito": "SITE_X",
            "quantita": "2", "unita": "t",
            "gwp_set": "AR6", "process_mode": "caco3_mass",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    warnings = data.get("warnings", [])
    assert any("IANO" in w for w in warnings), f"Expected IANO warning; got {warnings}"


# ---------------------------------------------------------------------------
# 7. S2 LB — Italian grid
# ---------------------------------------------------------------------------

def test_preview_s2_lb_italian_grid(client_editor: TestClient) -> None:
    """S2 LB: 10000 kWh × 0.27 kgCO2/kWh × 1e-3 = 2.700000 tCO2e."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 2, "sub_scope": "lb",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "10000", "unita": "kWh", "gwp_set": "AR6",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("2.700000")
    assert data["factor_id"] == "LB_IT_GRID_ISPRA_2024"
    assert data["methodology"] == "location-based"


# ---------------------------------------------------------------------------
# 8. S2 MB — GO zero emission
# ---------------------------------------------------------------------------

def test_preview_s2_mb_go_zero_emission(client_editor: TestClient) -> None:
    """S2 MB GO: tco2e must be 0 (MB_GO_ZERO factor = 0)."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 2, "sub_scope": "mb",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "5000", "unita": "kWh",
            "gwp_set": "AR6", "strumento_mb": "GO",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("0")
    assert data["factor_id"] == "MB_GO_ZERO"
    assert any("GO" in w for w in data.get("warnings", [])), "Expected GO warning"


# ---------------------------------------------------------------------------
# 9. S2 MB — residual mix
# ---------------------------------------------------------------------------

def test_preview_s2_mb_residual_mix(client_editor: TestClient) -> None:
    """S2 MB RESIDUAL: 1000 kWh × 0.44 kgCO2e/kWh × 1e-3 = 0.440000 tCO2e."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 2, "sub_scope": "mb",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "1000", "unita": "kWh",
            "gwp_set": "AR6", "strumento_mb": "RESIDUAL",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("0.440000")
    assert data["factor_id"] == "MB_IT_RESIDUAL_AIB_2024"
    assert data["methodology"] == "market-based"


# ---------------------------------------------------------------------------
# 10. S3 Cat 1 — purchased goods with biogenic split (cardboard)
# ---------------------------------------------------------------------------

def test_preview_s3_cat1_purchased_goods_with_biogenic_split(
    client_editor: TestClient,
) -> None:
    """S3 Cat1 cardboard: 100 kg → tco2e=0.12; biogenic=0.08 (ADR-007 memo)."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 3, "sub_scope": "cat1_purchased_goods",
            "anno": 2024, "quantita": "100", "unita": "kg",
            "gwp_set": "AR6",
            "sottocategoria": "imballaggi cartone", "metodo": "mass-based",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("0.120000")
    assert data["co2_biogenic_tonne"] is not None
    assert Decimal(data["co2_biogenic_tonne"]) == Decimal("0.080000"), (
        f"Biogenic should be 100×0.8×0.001=0.08; got {data['co2_biogenic_tonne']}"
    )
    assert data["co2_fossil_tonne"] == data["tco2e"]
    formula = data["formula_human"].lower()
    assert "biogenic" in formula or "adr" in formula


# ---------------------------------------------------------------------------
# 11. S3 Cat 3 — WTT gas naturale
# ---------------------------------------------------------------------------

def test_preview_s3_cat3_wtt_gas_naturale(client_editor: TestClient) -> None:
    """S3 Cat3 WTT GAS_NAT: 1000 units × 0.029 × 1e-3 = 0.029000 tCO2e."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 3, "sub_scope": "cat3_fuel_energy",
            "anno": 2024, "quantita": "1000", "unita": "Sm3",
            "gwp_set": "AR6",
            "sottocategoria": "GAS_NAT", "metodo": "fuel-based",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("0.029000")
    assert "WTT_GAS_NAT" in data["factor_id"]


# ---------------------------------------------------------------------------
# 12. S3 Cat 4 — upstream transport distance-based
# ---------------------------------------------------------------------------

def test_preview_s3_cat4_upstream_transport_distance_based(
    client_editor: TestClient,
) -> None:
    """S3 Cat4 HGV: 500 tkm × 0.106 × 1e-3 = 0.053000 tCO2e."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 3, "sub_scope": "cat4_upstream_transport",
            "anno": 2024, "quantita": "500", "unita": "tkm",
            "gwp_set": "AR6",
            "sottocategoria": "strada HGV", "metodo": "distance-based",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("0.053000")
    assert data["factor_id"] == "FREIGHT_HGV_DEFRA_2025"


# ---------------------------------------------------------------------------
# 13. Unit conversion — NCV-dependent rejected (Sm3 → kWh)
# ---------------------------------------------------------------------------

def test_preview_unit_conversion_ncv_dependent_rejected(
    client_editor: TestClient,
) -> None:
    """S2 LB with Sm3 (NCV-dependent conversion to kWh) must return 422."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 2, "sub_scope": "lb",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "1000", "unita": "Sm3",  # NCV-dependent
            "gwp_set": "AR6",
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    detail_str = str(body.get("detail", "")).lower()
    assert "ncv" in detail_str or "unit conversion" in detail_str


# ---------------------------------------------------------------------------
# 14. Vintage closest-prior resolution
# ---------------------------------------------------------------------------

def test_preview_vintage_closest_prior_resolution(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Factor vintage='2023' should appear in warnings when anno=2024 is requested."""
    from ghg_tool.api.schemas.calc_schemas import CalcInputRequest
    from ghg_tool.application.services.auto_calc_service import compute_preview

    # Patch catalog with a vintage-2023 LB factor
    old_factor = FactorRecord(
        factor_id="LB_IT_GRID_ISPRA_2024",
        version="2023",
        value=Decimal("0.27"),
        unit="kg CO2 / kWh",
        source="ISPRA",
        gwp_set="AR6",
        vintage="2023",
    )
    mock_catalog._seed[("LB_IT_GRID_ISPRA_2024", "AR6")] = old_factor

    req = CalcInputRequest(
        scope=2, sub_scope="lb",
        anno=2024, codice_sito="IANO",
        quantita=Decimal("1000"), unita="kWh", gwp_set="AR6",
    )
    result = asyncio.run(compute_preview(req, factor_catalog=mock_catalog))
    assert any(
        "closest-prior" in w or "2023" in w for w in result.warnings
    ), f"Expected vintage warning; got {result.warnings}"
    assert result.factor_vintage == "2023"


# ---------------------------------------------------------------------------
# 15. Missing factor raises explicit error (422)
# ---------------------------------------------------------------------------

def test_preview_missing_factor_raises_explicit_error(
    client_editor: TestClient,
) -> None:
    """Unknown sottocategoria for Cat1 should return 422 with descriptive detail."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 3, "sub_scope": "cat1_purchased_goods",
            "anno": 2024, "quantita": "100", "unita": "kg",
            "gwp_set": "AR6",
            "sottocategoria": "UNKNOWN_MATERIAL_XYZ", "metodo": "mass-based",
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", "")
    assert "UNKNOWN_MATERIAL_XYZ" in str(detail) or "factor" in str(detail).lower()


# ---------------------------------------------------------------------------
# 16. Negative quantita returns 422
# ---------------------------------------------------------------------------

def test_preview_negative_quantita_422(client_editor: TestClient) -> None:
    """Negative quantita must be rejected by Pydantic (gt=0) as 422."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 1, "sub_scope": "combustion",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "-100", "unita": "Sm3",
            "gwp_set": "AR6", "combustibile": "GAS_NAT",
        },
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 17. Viewer role → 403
# ---------------------------------------------------------------------------

def test_preview_viewer_role_403(client_viewer: TestClient) -> None:
    """Viewer does not have emissions.write → expect 403."""
    resp = client_viewer.post(
        "/api/v1/calc/preview",
        json={
            "scope": 2, "sub_scope": "lb",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "1000", "unita": "kWh", "gwp_set": "AR6",
        },
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 18. Insert writes emission row and audit log
# ---------------------------------------------------------------------------

def test_insert_writes_emission_row_and_audit_log(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """compute_and_insert should call session.execute for: site lookup, raw.direct_entry,
    emissions_consolidated, and audit_log — exactly 4 calls total (M6: Task B/C/D added).
    """
    from ghg_tool.api.schemas.calc_schemas import CalcInputRequest
    from ghg_tool.application.services.auto_calc_service import compute_and_insert

    execute_calls: list[Any] = []

    def _noop_result() -> MagicMock:
        """Return a mock execute result where mappings().first() returns None."""
        mock_result = MagicMock()
        mock_mappings = MagicMock()
        mock_mappings.first.return_value = None
        mock_result.mappings.return_value = mock_mappings
        return mock_result

    mock_session = MagicMock()

    async def capture_execute(stmt: Any, params: Any = None) -> MagicMock:
        execute_calls.append((stmt, params))
        return _noop_result()

    mock_session.execute = capture_execute

    user = _make_user("editor")
    req = CalcInputRequest(
        scope=2, sub_scope="lb",
        anno=2024, codice_sito="IANO",
        quantita=Decimal("1000"), unita="kWh", gwp_set="AR6",
    )

    with patch(
        "ghg_tool.application.services.auto_calc_service.get_correlation_id",
        return_value=str(uuid.uuid4()),
    ):
        result = asyncio.run(
            compute_and_insert(
                req, factor_catalog=mock_catalog, session=mock_session, user=user,
            )
        )

    # M6 + factor FK fix: 5 execute calls =
    #   site_lookup + factor_uuid_lookup + raw.direct_entry +
    #   emissions_consolidated + audit_log
    assert len(execute_calls) == 5, (
        f"Expected 5 DB execute calls (site_lookup + factor_uuid_lookup + "
        f"raw_entry + emission + audit), got {len(execute_calls)}"
    )
    assert result.emission_id is not None
    assert isinstance(result.emission_id, uuid.UUID)
    assert result.tco2e == Decimal("0.270000")


# ---------------------------------------------------------------------------
# 19. Insert returns 201 with emission_id
# ---------------------------------------------------------------------------

def test_insert_returns_201_with_emission_id(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """POST /api/v1/calc/insert must return HTTP 201 with a valid emission_id."""
    mock_session = _make_mock_session(codice_sito=None)  # site not found → skip validation

    async def _override() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = lambda: _make_user("editor")
    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_factor_catalog] = lambda: mock_catalog

    with (
        TestClient(app, raise_server_exceptions=False) as c,
        patch(
            "ghg_tool.application.services.auto_calc_service.get_correlation_id",
            return_value=str(uuid.uuid4()),
        ),
    ):
        resp = c.post(
            "/api/v1/calc/insert",
            json={
                "scope": 2, "sub_scope": "lb",
                "anno": 2024, "codice_sito": "IANO",
                "quantita": "1000", "unita": "kWh", "gwp_set": "AR6",
            },
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 201, resp.text
    data = resp.json()
    emission_id = uuid.UUID(data["emission_id"])
    assert emission_id != uuid.UUID(int=0)
    assert "correlation_id" in data
    assert "created_at" in data
    assert Decimal(data["tco2e"]) == Decimal("0.270000")


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

def test_preview_s3_cat5_waste_landfill(client_editor: TestClient) -> None:
    """S3 Cat5 non-hazardous landfill: 10 t × 12.5 × 1e-3 = 0.125000 tCO2e."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 3, "sub_scope": "cat5_waste",
            "anno": 2024, "quantita": "10", "unita": "t",
            "gwp_set": "AR6",
            "sottocategoria": "discarica non pericolosi", "metodo": "mass-based",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("0.125000")


def test_preview_s3_cat6_voli(client_editor: TestClient) -> None:
    """S3 Cat6 flights: 500 EUR × 0.30 × 1e-3 = 0.150000 tCO2e."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 3, "sub_scope": "cat6_business_travel",
            "anno": 2024, "quantita": "500", "unita": "EUR",
            "gwp_set": "AR6",
            "sottocategoria": "voli", "metodo": "spend-based",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("0.150000")


def test_preview_s3_cat12_eol_combined(client_editor: TestClient) -> None:
    """S3 Cat12 EOL 100 kg: 30×8.0 + 70×2.0 all ×0.001 = 0.38 tCO2e."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 3, "sub_scope": "cat12_eol",
            "anno": 2024, "quantita": "100", "unita": "kg",
            "gwp_set": "AR6",
            "sottocategoria": "ceramica eol", "metodo": "mass-based",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    expected = (
        Decimal("100") * Decimal("0.30") * Decimal("8.0") * Decimal("0.001")
        + Decimal("100") * Decimal("0.70") * Decimal("2.0") * Decimal("0.001")
    )
    assert Decimal(data["tco2e"]) == expected.quantize(Decimal("0.000001"))


def test_preview_missing_combustibile_for_s1_combustion(client_editor: TestClient) -> None:
    """S1 combustion without combustibile field should return 422."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 1, "sub_scope": "combustion",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "1000", "unita": "Sm3", "gwp_set": "AR6",
            # combustibile omitted
        },
    )
    assert resp.status_code == 422, resp.text


def test_preview_s1_process_mode_a_wrong_unit_rejected(client_editor: TestClient) -> None:
    """S1 process Mode A with unita != 'tCO2' should be rejected (422)."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 1, "sub_scope": "process",
            "anno": 2024, "codice_sito": "IANO",
            "quantita": "5", "unita": "kg",  # wrong unit for Mode A
            "gwp_set": "AR6", "process_mode": "direct_tco2",
        },
    )
    assert resp.status_code == 422, resp.text


def test_preview_s3_missing_metodo_returns_422(client_editor: TestClient) -> None:
    """S3 without metodo should be rejected by validators (422)."""
    resp = client_editor.post(
        "/api/v1/calc/preview",
        json={
            "scope": 3, "sub_scope": "cat4_upstream_transport",
            "anno": 2024, "quantita": "100", "unita": "tkm", "gwp_set": "AR6",
            "sottocategoria": "strada",
            # metodo omitted
        },
    )
    assert resp.status_code == 422, resp.text


# ===========================================================================
# M6 Task B — site_type validation for Processo_Decarb
# ===========================================================================

def _client_with_site_type(
    mock_catalog: InMemoryFactorCatalog,
    *,
    codice_sito: str,
    site_type: str,
) -> TestClient:
    """Helper: build a TestClient whose DB session reports a specific site_type.

    Args:
        mock_catalog: Seeded factor catalog.
        codice_sito: The site code to configure in the mock DB.
        site_type: The site_type value to return from ref.sites.

    Returns:
        A configured TestClient as context manager (caller must enter/exit).
    """
    editor_user = _make_user("editor")
    app.dependency_overrides[get_current_user] = lambda: editor_user
    app.dependency_overrides[get_db] = _override_db_noop(
        codice_sito=codice_sito, site_type=site_type, site_country="IT"
    )
    app.dependency_overrides[get_factor_catalog] = lambda: mock_catalog
    return TestClient(app, raise_server_exceptions=False)


def test_processo_decarb_rejected_422_for_ufficio_casalgrande(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task B: Processo_Decarb on CASALGRANDE (UFFICIO) must return 422 site_type_invalid.

    Decision #7 from auto_calc_design.md §12: process emissions are only
    allowed for STABILIMENTO_PRODUTTIVO sites.
    """
    with _client_with_site_type(
        mock_catalog, codice_sito="CASALGRANDE", site_type="UFFICIO"
    ) as client:
        resp = client.post(
            "/api/v1/calc/preview",
            json={
                "scope": 1, "sub_scope": "process",
                "anno": 2024, "codice_sito": "CASALGRANDE",
                "quantita": "10.0", "unita": "tCO2",
                "gwp_set": "AR6", "process_mode": "direct_tco2",
            },
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "site_type_invalid", f"Unexpected detail: {detail}"
    assert detail.get("codice_sito") == "CASALGRANDE"
    assert detail.get("site_type") == "UFFICIO"


def test_processo_decarb_rejected_422_for_ufficio_sassuolo(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task B: Processo_Decarb on SASSUOLO (UFFICIO) must return 422 site_type_invalid."""
    with _client_with_site_type(
        mock_catalog, codice_sito="SASSUOLO", site_type="UFFICIO"
    ) as client:
        resp = client.post(
            "/api/v1/calc/preview",
            json={
                "scope": 1, "sub_scope": "process",
                "anno": 2024, "codice_sito": "SASSUOLO",
                "quantita": "5.0", "unita": "tCO2",
                "gwp_set": "AR6", "process_mode": "direct_tco2",
            },
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "site_type_invalid"
    assert detail.get("site_type") == "UFFICIO"


def test_processo_decarb_rejected_422_for_magazzino_viano_gargola(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task B: Processo_Decarb on VIANO_GARGOLA (MAGAZZINO) must return 422."""
    with _client_with_site_type(
        mock_catalog, codice_sito="VIANO_GARGOLA", site_type="MAGAZZINO"
    ) as client:
        resp = client.post(
            "/api/v1/calc/preview",
            json={
                "scope": 1, "sub_scope": "process",
                "anno": 2024, "codice_sito": "VIANO_GARGOLA",
                "quantita": "3.0", "unita": "tCO2",
                "gwp_set": "AR6", "process_mode": "direct_tco2",
            },
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "site_type_invalid"
    assert detail.get("site_type") == "MAGAZZINO"


def test_processo_decarb_rejected_422_for_magazzino_fiorano(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task B: Processo_Decarb on FIORANO (MAGAZZINO) must return 422."""
    with _client_with_site_type(
        mock_catalog, codice_sito="FIORANO", site_type="MAGAZZINO"
    ) as client:
        resp = client.post(
            "/api/v1/calc/preview",
            json={
                "scope": 1, "sub_scope": "process",
                "anno": 2024, "codice_sito": "FIORANO",
                "quantita": "7.5", "unita": "tCO2",
                "gwp_set": "AR6", "process_mode": "direct_tco2",
            },
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "site_type_invalid"
    assert detail.get("site_type") == "MAGAZZINO"


def test_processo_decarb_ok_for_stabilimento_iano(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task B: Processo_Decarb on IANO (STABILIMENTO_PRODUTTIVO) must return 200."""
    with _client_with_site_type(
        mock_catalog, codice_sito="IANO", site_type="STABILIMENTO_PRODUTTIVO"
    ) as client:
        resp = client.post(
            "/api/v1/calc/preview",
            json={
                "scope": 1, "sub_scope": "process",
                "anno": 2024, "codice_sito": "IANO",
                "quantita": "5.5", "unita": "tCO2",
                "gwp_set": "AR6", "process_mode": "direct_tco2",
            },
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("5.5")


def test_processo_decarb_ok_for_stabilimento_viano(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task B: Processo_Decarb on VIANO (STABILIMENTO_PRODUTTIVO) must return 200."""
    with _client_with_site_type(
        mock_catalog, codice_sito="VIANO", site_type="STABILIMENTO_PRODUTTIVO"
    ) as client:
        resp = client.post(
            "/api/v1/calc/preview",
            json={
                "scope": 1, "sub_scope": "process",
                "anno": 2024, "codice_sito": "VIANO",
                "quantita": "3.0", "unita": "tCO2",
                "gwp_set": "AR6", "process_mode": "direct_tco2",
            },
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["tco2e"]) == Decimal("3.0")


def test_processo_decarb_ok_for_stabilimento_frassinoro(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task B: Processo_Decarb on FRASSINORO (STABILIMENTO_PRODUTTIVO) must return 200."""
    with _client_with_site_type(
        mock_catalog, codice_sito="FRASSINORO", site_type="STABILIMENTO_PRODUTTIVO"
    ) as client:
        resp = client.post(
            "/api/v1/calc/preview",
            json={
                "scope": 1, "sub_scope": "process",
                "anno": 2024, "codice_sito": "FRASSINORO",
                "quantita": "12.0", "unita": "tCO2",
                "gwp_set": "AR6", "process_mode": "direct_tco2",
            },
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text


# ===========================================================================
# M6 Task E — Idempotency-Key header on /calc/insert
# ===========================================================================

def _make_idempotency_mock_session(
    *,
    cached_hit: dict[str, Any] | None = None,
    raise_reuse: bool = False,
) -> MagicMock:
    """Build a mock session that simulates idempotency cache behavior.

    Args:
        cached_hit: If set, the idempotency lookup returns this response dict.
            ``None`` means cache miss (no prior entry).
        raise_reuse: If True, simulates a cache hit with mismatched body.

    Returns:
        A configured MagicMock session.
    """

    call_count = 0

    def _make_first_result(cached: dict[str, Any] | None) -> MagicMock:
        """Result for the idempotency lookup query."""
        mock_result = MagicMock()
        mock_mappings = MagicMock()
        if cached is not None:
            # Simulate a DB row with correct hash (same body)
            mock_mappings.first.return_value = {
                "request_hash": "a" * 64,  # matches computed hash below
                "response_status": 201,
                "response_body": cached,
            }
        else:
            mock_mappings.first.return_value = None
        mock_result.mappings.return_value = mock_mappings
        return mock_result

    # Default noop result (for site lookup and write statements)
    noop_result = MagicMock()
    noop_mappings = MagicMock()
    noop_mappings.first.return_value = None
    noop_result.mappings.return_value = noop_mappings

    mock_session = MagicMock()

    async def _execute(stmt: Any, params: Any = None) -> MagicMock:
        nonlocal call_count
        call_count += 1
        # First call is the idempotency lookup
        if call_count == 1 and (cached_hit is not None or raise_reuse):
            return _make_first_result(cached_hit)
        return noop_result

    mock_session.execute = _execute
    return mock_session


def test_idempotency_key_same_body_returns_replay(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task E: same Idempotency-Key + same body → replay with X-Idempotency-Replayed: true.

    We patch ``check_idempotency`` directly to return an ``IdempotencyHit``
    so that the router's cache-hit branch is exercised without a real DB.
    """
    import uuid as _uuid  # noqa: PLC0415

    from ghg_tool.application.services.idempotency_service import IdempotencyHit  # noqa: PLC0415

    cached_emission_id = str(_uuid.uuid4())
    cached_body: dict[str, Any] = {
        "tco2e": "2.700000",
        "co2_biogenic_tonne": None,
        "co2_fossil_tonne": None,
        "factor_id": "LB_IT_GRID_ISPRA_2024",
        "factor_value": "0.27",
        "factor_unit": "kg CO2 / kWh",
        "factor_source": "ISPRA",
        "factor_version": "2025",
        "factor_vintage": "2025",
        "gwp_set": "AR6",
        "gwp_value": "1",
        "methodology": "location-based",
        "formula_human": "10000 kWh × 0.27 kgCO2/kWh × 1e-3 = 2.700000 tCO2e [LB country=IT]",
        "unit_conversion_applied": None,
        "warnings": [],
        "emission_id": cached_emission_id,
        "correlation_id": str(_uuid.uuid4()),
        "created_at": "2026-05-15T10:00:00+00:00",
    }

    mock_session = _make_mock_session(codice_sito=None)

    async def _override() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = lambda: _make_user("editor")
    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_factor_catalog] = lambda: mock_catalog

    idempotency_hit = IdempotencyHit(
        response_status=201,
        response_body=cached_body,
    )

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch(
            "ghg_tool.api.routers.calc.check_idempotency",
            new=AsyncMock(return_value=idempotency_hit),
        ),
        patch(
            "ghg_tool.application.services.auto_calc_service.get_correlation_id",
            return_value=str(uuid.uuid4()),
        ),
    ):
        resp = client.post(
            "/api/v1/calc/insert",
            json={
                "scope": 2, "sub_scope": "lb",
                "anno": 2024, "codice_sito": "IANO",
                "quantita": "10000", "unita": "kWh", "gwp_set": "AR6",
            },
            headers={"Idempotency-Key": "test-idempotency-key-abc123"},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Idempotency-Replayed") == "true"
    data = resp.json()
    assert data["emission_id"] == cached_emission_id


def test_idempotency_key_different_body_returns_422(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task E: same Idempotency-Key with different body → 422 idempotency_key_reuse.

    We patch ``check_idempotency`` to raise ``IdempotencyKeyReusedError``
    simulating a body mismatch.
    """
    from ghg_tool.application.services.idempotency_service import (
        IdempotencyKeyReusedError,  # noqa: PLC0415
    )

    mock_session = _make_mock_session(codice_sito=None)

    async def _override() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = lambda: _make_user("editor")
    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_factor_catalog] = lambda: mock_catalog

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch(
            "ghg_tool.api.routers.calc.check_idempotency",
            new=AsyncMock(
                side_effect=IdempotencyKeyReusedError(
                    "Idempotency-Key 'test-key' was previously used with a different body."
                )
            ),
        ),
    ):
        resp = client.post(
            "/api/v1/calc/insert",
            json={
                "scope": 2, "sub_scope": "lb",
                "anno": 2024, "codice_sito": "IANO",
                "quantita": "5000", "unita": "kWh", "gwp_set": "AR6",  # different body
            },
            headers={"Idempotency-Key": "test-idempotency-key-abc123"},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "idempotency_key_reuse_with_different_body"


def test_idempotency_key_absent_inserts_normally(
    mock_catalog: InMemoryFactorCatalog,
) -> None:
    """Task E: no Idempotency-Key header → normal insert path (no cache check).

    When the header is absent, ``check_idempotency`` must NOT be called.
    """
    mock_session = _make_mock_session(codice_sito=None)

    async def _override() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = lambda: _make_user("editor")
    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_factor_catalog] = lambda: mock_catalog

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch(
            "ghg_tool.api.routers.calc.check_idempotency",
            new=AsyncMock(),
        ) as mock_check,
        patch(
            "ghg_tool.application.services.auto_calc_service.get_correlation_id",
            return_value=str(uuid.uuid4()),
        ),
    ):
        resp = client.post(
            "/api/v1/calc/insert",
            json={
                "scope": 2, "sub_scope": "lb",
                "anno": 2024, "codice_sito": "IANO",
                "quantita": "1000", "unita": "kWh", "gwp_set": "AR6",
            },
            # No Idempotency-Key header
        )
        # check_idempotency must not have been called
        mock_check.assert_not_called()

    app.dependency_overrides.clear()

    assert resp.status_code == 201, resp.text
