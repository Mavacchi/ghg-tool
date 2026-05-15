"""Unit tests for POST /api/v1/emissions/{emission_id}/correct.

Covers all 10 specified test cases:
  - 201 happy path
  - Append-only: new row inserted, old row NOT updated by the application layer
  - superseded_by link (old → new direction via fn_emit_correction)
  - 404 for unknown emission_id
  - 404 for cross-tenant access
  - 422 for negative tco2e
  - 422 for unknown reason_code
  - 403 for viewer role
  - 403 for admin role
  - audit_log row written
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT_ID = str(uuid.uuid4())
_FACTOR_ID = str(uuid.uuid4())
_EMISSION_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str) -> CurrentUser:
    return CurrentUser(
        sub=str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def _user_override(role: str) -> Any:
    u = _make_user(role)

    async def _dep() -> CurrentUser:
        return u

    return _dep


def _empty_session() -> Any:
    async def _gen() -> Any:
        session = AsyncMock()
        yield session

    return _gen


def _emission_orm_row(**kwargs: Any) -> MagicMock:
    """Build a MagicMock that looks like an active Emission ORM row."""
    defaults = {
        "id": _EMISSION_ID,
        "tenant_id": uuid.UUID(_TENANT_ID),
        "correlation_id": uuid.uuid4(),
        "raw_row_id": uuid.uuid4(),
        "raw_scope": 1,
        "scope": 1,
        "sub_scope": "combustion",
        "codice_sito": "IANO",
        "anno": 2024,
        "tco2e": 100.0,
        "co2_tonne": 95.0,
        "ch4_tco2e": None,
        "n2o_tco2e": None,
        "co2_biogenic_tonne": None,
        "co2_fossil_tonne": None,
        "factor_id": uuid.UUID(_FACTOR_ID),
        "factor_version": "v1.0",
        "factor_source": "DEFRA",
        "gwp_set": "AR6",
        "methodology": "activity-based",
        "regulatory_stream": "CSRD_ESRS_E1",
        "calc_timestamp": datetime.now(tz=UTC),
        "created_by": "test-user",
        "valid_from": datetime.now(tz=UTC),
        "valid_to": None,          # active row
        "superseded_by": None,
        "reason_code": None,
        "disclosure_notes": None,
    }
    defaults.update(kwargs)
    row = MagicMock(spec_set=list(defaults.keys()))
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


_VALID_CORRECTION_BODY: dict[str, Any] = {
    "reason_code": "FACTOR_UPDATE",
    "tco2e": 90.0,
    "factor_id": str(uuid.uuid4()),
    "factor_source": "DEFRA",
    "factor_version": "v2.0",
    "gwp_set": "AR6",
    "methodology": "activity-based",
}

_CORRECTION_URL = f"/api/v1/emissions/{_EMISSION_ID}/correct"


# ---------------------------------------------------------------------------
# Fixture: mock repo that finds the predecessor
# ---------------------------------------------------------------------------


def _repo_mock_found(predecessor: MagicMock | None = None) -> Any:
    """Patch EmissionsRepository so get_by_id returns the predecessor row."""
    if predecessor is None:
        predecessor = _emission_orm_row()

    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id = AsyncMock(return_value=predecessor)
    mock_repo_instance.insert = AsyncMock(return_value=predecessor)
    mock_repo_instance.apply_correction = AsyncMock(return_value=None)
    return mock_repo_instance


def _repo_mock_not_found() -> Any:
    """Patch EmissionsRepository so get_by_id returns None (not found)."""
    mock_repo_instance = MagicMock()
    mock_repo_instance.get_by_id = AsyncMock(return_value=None)
    return mock_repo_instance


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestCorrectEmissionById:
    """Tests for POST /api/v1/emissions/{emission_id}/correct."""

    def test_correct_emission_returns_201_with_new_row_id(self) -> None:
        """Happy path: editor gets 201 with new_id in response."""
        mock_repo = _repo_mock_found()
        with patch("ghg_tool.api.routers.emissions.EmissionsRepository", return_value=mock_repo):
            app.dependency_overrides[get_current_user] = _user_override("editor")
            app.dependency_overrides[get_db] = _empty_session()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(_CORRECTION_URL, json=_VALID_CORRECTION_BODY)
            app.dependency_overrides.clear()

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "new_id" in body
        assert "superseded_id" in body
        assert "reason_code" in body
        assert "correlation_id" in body
        assert body["superseded_id"] == str(_EMISSION_ID)
        assert body["reason_code"] == "FACTOR_UPDATE"
        # new_id must be a valid UUID distinct from the predecessor
        new_id = uuid.UUID(body["new_id"])
        assert new_id != _EMISSION_ID

    def test_correct_emission_inserts_new_row_not_updates_old(self) -> None:
        """Append-only: repo.insert is called once; no direct UPDATE on old row.

        The only mutation to the old row is routed through apply_correction
        (which calls calc.fn_emit_correction SECURITY DEFINER).  The
        application layer must never call session.execute with a raw UPDATE
        outside that path.
        """
        mock_repo = _repo_mock_found()
        with patch("ghg_tool.api.routers.emissions.EmissionsRepository", return_value=mock_repo):
            app.dependency_overrides[get_current_user] = _user_override("editor")
            app.dependency_overrides[get_db] = _empty_session()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(_CORRECTION_URL, json=_VALID_CORRECTION_BODY)
            app.dependency_overrides.clear()

        assert resp.status_code == 201, resp.text
        # insert must have been called exactly once (the new row)
        mock_repo.insert.assert_called_once()
        inserted_arg = mock_repo.insert.call_args[0][0]
        # The inserted row must NOT carry the old predecessor id
        assert inserted_arg.id != _EMISSION_ID
        # apply_correction is the ONLY permitted quasi-update path
        mock_repo.apply_correction.assert_called_once()

    def test_correct_emission_sets_superseded_by_link(self) -> None:
        """apply_correction is invoked with predecessor_id=old and new_id=new.

        Direction confirmed: OLD row points to NEW row via superseded_by = new_id.
        (Methodology §5, fn_emit_correction source in M1 migration.)
        """
        mock_repo = _repo_mock_found()
        with patch("ghg_tool.api.routers.emissions.EmissionsRepository", return_value=mock_repo):
            app.dependency_overrides[get_current_user] = _user_override("editor")
            app.dependency_overrides[get_db] = _empty_session()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(_CORRECTION_URL, json=_VALID_CORRECTION_BODY)
            app.dependency_overrides.clear()

        assert resp.status_code == 201, resp.text
        body = resp.json()

        # apply_correction must be called with predecessor_id = the path param
        # and new_id = the newly generated UUID returned in the response
        call_kwargs = mock_repo.apply_correction.call_args.kwargs
        assert call_kwargs["predecessor_id"] == _EMISSION_ID
        assert call_kwargs["new_id"] == uuid.UUID(body["new_id"])
        assert call_kwargs["reason_code"] == "FACTOR_UPDATE"

    def test_correct_emission_404_unknown_id(self) -> None:
        """Unknown emission_id returns 404."""
        mock_repo = _repo_mock_not_found()
        with patch("ghg_tool.api.routers.emissions.EmissionsRepository", return_value=mock_repo):
            app.dependency_overrides[get_current_user] = _user_override("editor")
            app.dependency_overrides[get_db] = _empty_session()
            unknown_id = uuid.uuid4()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    f"/api/v1/emissions/{unknown_id}/correct",
                    json=_VALID_CORRECTION_BODY,
                )
            app.dependency_overrides.clear()

        assert resp.status_code == 404, resp.text

    def test_correct_emission_404_cross_tenant(self) -> None:
        """Cross-tenant lookup returns None → 404 (no tenant data leak)."""
        # Simulate RLS / tenant check by returning None even for a real UUID
        mock_repo = _repo_mock_not_found()
        with patch("ghg_tool.api.routers.emissions.EmissionsRepository", return_value=mock_repo):
            app.dependency_overrides[get_current_user] = _user_override("editor")
            app.dependency_overrides[get_db] = _empty_session()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    f"/api/v1/emissions/{_EMISSION_ID}/correct",
                    json=_VALID_CORRECTION_BODY,
                )
            app.dependency_overrides.clear()

        assert resp.status_code == 404, resp.text

    def test_correct_emission_422_negative_tco2e(self) -> None:
        """tco2e < 0 is rejected by Pydantic with 422 before the handler runs."""
        bad_body = {**_VALID_CORRECTION_BODY, "tco2e": -5.0}
        app.dependency_overrides[get_current_user] = _user_override("editor")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_CORRECTION_URL, json=bad_body)
        app.dependency_overrides.clear()

        assert resp.status_code == 422, resp.text

    def test_correct_emission_422_unknown_reason_code(self) -> None:
        """reason_code not in the canonical enum is rejected with 422."""
        bad_body = {**_VALID_CORRECTION_BODY, "reason_code": "MANUAL_FIX"}
        app.dependency_overrides[get_current_user] = _user_override("editor")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_CORRECTION_URL, json=bad_body)
        app.dependency_overrides.clear()

        assert resp.status_code == 422, resp.text

    def test_correct_emission_403_auditor(self) -> None:
        """viewer role does not have emissions:write permission → 403."""
        app.dependency_overrides[get_current_user] = _user_override("viewer")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_CORRECTION_URL, json=_VALID_CORRECTION_BODY)
        app.dependency_overrides.clear()

        assert resp.status_code == 403, resp.text

    def test_correct_emission_403_esg_manager(self) -> None:
        """admin does not have emissions:write permission → 403.

        The resource-scoped correction endpoint uses ``emissions:write``
        (editor only), which is stricter than the bulk ``/correction``
        endpoint that allows ``emissions:correct``.
        """
        app.dependency_overrides[get_current_user] = _user_override("admin")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_CORRECTION_URL, json=_VALID_CORRECTION_BODY)
        app.dependency_overrides.clear()

        assert resp.status_code == 403, resp.text

    def test_correct_emission_audit_log_row_written(self) -> None:
        """An AuditLog row is added to the session with action='EMISSION_CORRECTION'."""
        mock_repo = _repo_mock_found()
        captured_audit: list[Any] = []

        async def _fake_session_gen() -> Any:
            session = AsyncMock()
            session.flush = AsyncMock()

            # Capture all objects passed to session.add
            def _capture_add(obj: Any) -> None:
                captured_audit.append(obj)

            session.add = MagicMock(side_effect=_capture_add)
            yield session

        with patch("ghg_tool.api.routers.emissions.EmissionsRepository", return_value=mock_repo):
            app.dependency_overrides[get_current_user] = _user_override("editor")
            app.dependency_overrides[get_db] = _fake_session_gen
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(_CORRECTION_URL, json=_VALID_CORRECTION_BODY)
            app.dependency_overrides.clear()

        assert resp.status_code == 201, resp.text

        from ghg_tool.infrastructure.db.models.audit_log import AuditLog

        audit_rows = [obj for obj in captured_audit if isinstance(obj, AuditLog)]
        assert len(audit_rows) == 1, (
            f"Expected exactly 1 AuditLog row added to session; got {len(audit_rows)}"
        )
        audit = audit_rows[0]
        assert audit.action == "EMISSION_CORRECTION"
        assert audit.resource == "calc.emissions_consolidated"
        assert audit.resource_id == _EMISSION_ID
        assert audit.status_code == 201
        assert audit.before_state is not None
        assert audit.after_state is not None
        assert audit.after_state.get("reason_code") == "FACTOR_UPDATE"
