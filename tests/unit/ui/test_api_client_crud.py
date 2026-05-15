"""Unit tests for the three new CRUD API client functions (FR-29 / UX-CRUD).

Covers:
  - patch_factor_draft: correct endpoint, raises FactorCRUDError on 422.
  - delete_factor_draft: returns None on 204.
  - correct_emission: correct endpoint, returns dict on 201.

No Streamlit runtime is needed because the helpers under test are plain
synchronous httpx wrappers; session_state is mocked at the module level.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Force the agent worktree's src onto sys.path before importing the module
# so the tests exercise the functions added in this branch, not whichever
# editable install pip currently resolves to.
_WORKTREE_SRC = "/home/user/ghg-tool/.claude/worktrees/agent-abb5f05342ad2c88d/src"
if _WORKTREE_SRC not in sys.path:
    sys.path.insert(0, _WORKTREE_SRC)

# Evict any already-cached copy of api_client so the path override above
# takes effect before the first import inside the test bodies.
sys.modules.pop("ghg_tool.ui.streamlit_app.lib.api_client", None)

from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: E402
    EmissionCorrectionError,
    FactorCRUDError,
    correct_emission,
    delete_factor_draft,
    patch_factor_draft,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = "http://testserver"
_PATCH_BASE = "ghg_tool.ui.streamlit_app.lib.api_client._get_base_url"
_PATCH_HTTPX_PATCH = "ghg_tool.ui.streamlit_app.lib.api_client.httpx.patch"
_PATCH_HTTPX_DELETE = "ghg_tool.ui.streamlit_app.lib.api_client.httpx.delete"
_PATCH_HTTPX_POST = "ghg_tool.ui.streamlit_app.lib.api_client.httpx.post"


def _mock_response(
    status_code: int,
    json_body: dict | None = None,
    text: str = "",
) -> MagicMock:
    """Build a mock httpx.Response with the given status code and JSON body."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = Exception("no json")
    return resp


# ---------------------------------------------------------------------------
# patch_factor_draft
# ---------------------------------------------------------------------------


class TestPatchFactorDraft:
    """Tests for api_client.patch_factor_draft."""

    def test_patch_factor_draft_calls_correct_endpoint(self) -> None:
        """PATCH is sent to /api/v1/factor-catalog/{uuid} with the updates payload."""
        _uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        _updates = {"value": 0.256, "unit": "kg CO2e/kWh"}
        _resp_body = {"id": _uuid, "value": 0.256, "is_published": False}
        mock_resp = _mock_response(200, _resp_body)

        with (
            patch(_PATCH_HTTPX_PATCH, return_value=mock_resp) as mock_p,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            result = patch_factor_draft(_uuid, _updates, token="bearer-tok")

        mock_p.assert_called_once()
        call_kwargs = mock_p.call_args
        assert f"/api/v1/factor-catalog/{_uuid}" in call_kwargs.args[0]
        assert call_kwargs.kwargs["json"] == _updates
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer bearer-tok"
        assert result == _resp_body

    def test_patch_factor_draft_raises_on_422_published(self) -> None:
        """FactorCRUDError(422) is raised when the API returns 422 (published row)."""
        _uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        _resp_422 = _mock_response(422, {"detail": "Factor is published and immutable."})

        with patch(_PATCH_HTTPX_PATCH, return_value=_resp_422), patch(
            _PATCH_BASE, return_value=_BASE
        ), pytest.raises(FactorCRUDError) as exc_info:
            patch_factor_draft(_uuid, {"value": 9.9}, token="bearer-tok")

        assert exc_info.value.status_code == 422
        assert "immutable" in exc_info.value.detail

    def test_patch_factor_draft_raises_on_403_forbidden(self) -> None:
        """FactorCRUDError(403) is raised when the caller lacks data_steward role."""
        _uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        _resp_403 = _mock_response(403, {"detail": "Forbidden."})

        with patch(_PATCH_HTTPX_PATCH, return_value=_resp_403), patch(
            _PATCH_BASE, return_value=_BASE
        ), pytest.raises(FactorCRUDError) as exc_info:
            patch_factor_draft(_uuid, {"value": 9.9}, token="wrong-role-tok")

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# delete_factor_draft
# ---------------------------------------------------------------------------


class TestDeleteFactorDraft:
    """Tests for api_client.delete_factor_draft."""

    def test_delete_factor_draft_returns_none_on_204(self) -> None:
        """delete_factor_draft returns None on HTTP 204 (no content)."""
        _uuid = "11111111-2222-3333-4444-555555555555"
        _resp_204 = _mock_response(204)

        with (
            patch(_PATCH_HTTPX_DELETE, return_value=_resp_204) as mock_d,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            result = delete_factor_draft(_uuid, token="bearer-tok")

        assert result is None
        mock_d.assert_called_once()
        call_kwargs = mock_d.call_args
        assert f"/api/v1/factor-catalog/{_uuid}" in call_kwargs.args[0]
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer bearer-tok"

    def test_delete_factor_draft_raises_on_422_published(self) -> None:
        """FactorCRUDError(422) is raised when trying to delete a published factor."""
        _uuid = "11111111-2222-3333-4444-555555555555"
        _resp_422 = _mock_response(422, {"detail": "Cannot delete published factor."})

        with patch(_PATCH_HTTPX_DELETE, return_value=_resp_422), patch(
            _PATCH_BASE, return_value=_BASE
        ), pytest.raises(FactorCRUDError) as exc_info:
            delete_factor_draft(_uuid, token="bearer-tok")

        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# correct_emission
# ---------------------------------------------------------------------------


class TestCorrectEmission:
    """Tests for api_client.correct_emission."""

    def test_correct_emission_calls_correct_endpoint(self) -> None:
        """POST is sent to /api/v1/emissions/{id}/correct with the payload."""
        _eid = "cccccccc-dddd-eeee-ffff-000000000000"
        _payload = {
            "reason_code": "FACTOR_UPDATE",
            "tco2e_corrected": 12.5,
            "notes": "Updated to DEFRA 2024 factors.",
        }
        _resp_body = {"id": "new-row-uuid", "superseded_by": _eid, "tco2e": 12.5}
        mock_resp = _mock_response(201, _resp_body)

        with (
            patch(_PATCH_HTTPX_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            result = correct_emission(_eid, _payload, token="bearer-tok")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert f"/api/v1/emissions/{_eid}/correct" in call_kwargs.args[0]
        assert call_kwargs.kwargs["json"] == _payload
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer bearer-tok"
        assert result == _resp_body

    def test_correct_emission_raises_on_422_validation(self) -> None:
        """EmissionCorrectionError(422) is raised on validation failure."""
        _eid = "cccccccc-dddd-eeee-ffff-000000000000"
        _resp_422 = _mock_response(422, {"detail": "tco2e_corrected must be >= 0."})
        _bad_payload = {
            "reason_code": "MANUAL_FIX",
            "tco2e_corrected": -1.0,
            "notes": "bad",
        }

        with patch(_PATCH_HTTPX_POST, return_value=_resp_422), patch(
            _PATCH_BASE, return_value=_BASE
        ), pytest.raises(EmissionCorrectionError) as exc_info:
            correct_emission(_eid, _bad_payload, token="tok")

        assert exc_info.value.status_code == 422

    def test_correct_emission_raises_on_404_not_found(self) -> None:
        """EmissionCorrectionError(404) is raised when the emission row does not exist."""
        _eid = "nonexistent-uuid"
        _resp_404 = _mock_response(404, {"detail": "Emission not found."})
        _payload = {
            "reason_code": "MANUAL_FIX",
            "tco2e_corrected": 1.0,
            "notes": "test",
        }

        with patch(_PATCH_HTTPX_POST, return_value=_resp_404), patch(
            _PATCH_BASE, return_value=_BASE
        ), pytest.raises(EmissionCorrectionError) as exc_info:
            correct_emission(_eid, _payload, token="tok")

        assert exc_info.value.status_code == 404
