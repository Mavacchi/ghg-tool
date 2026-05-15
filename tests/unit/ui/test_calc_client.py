"""Unit tests for api_client.calc_preview and api_client.calc_insert.

Covers the new AutoCalcError exception class and both endpoint wrappers:
  - calc_preview: POST /api/v1/calc/preview (no DB write)
  - calc_insert:  POST /api/v1/calc/insert   (writes ledger row)

Error-handling matrix tested:
  - 200 / 201  → return parsed JSON
  - 422        → raise AutoCalcError(detail)
  - 403        → raise AutoCalcError("Ruolo insufficiente: solo editor/admin")
  - 5xx / other → raise AutoCalcError(detail)
  - Network error → raise AutoCalcError("Errore di rete: ...")

No Streamlit runtime is needed because both helpers are plain synchronous
httpx wrappers; session_state is not touched by these functions.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Evict any previously-cached module so that stale editable-install copies
# don't silently shadow the local source tree.
sys.modules.pop("ghg_tool.ui.streamlit_app.lib.api_client", None)

from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: E402
    AutoCalcError,
    calc_insert,
    calc_preview,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_BASE = "http://testserver"
_PATCH_BASE = "ghg_tool.ui.streamlit_app.lib.api_client._get_base_url"
_PATCH_POST = "ghg_tool.ui.streamlit_app.lib.api_client.httpx.post"

_MINIMAL_PAYLOAD = {
    "scope": 1,
    "sub_scope": "combustion",
    "combustibile": "GAS_NAT",
    "codice_sito": "IANO",
    "anno": 2024,
    "quantita": "22916841",
    "unita": "Sm3",
    "gwp_set": "AR6",
    "regulatory_stream": "CSRD_ESRS_E1",
}

_PREVIEW_RESPONSE = {
    "preview_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "tco2e": "44530.123456",
    "breakdown": {
        "co2_tonne": "44321.0",
        "co2_fossil_tonne": "44321.0",
        "co2_biogenic_tonne": None,
        "ch4_tco2e": "5.123",
        "n2o_tco2e": "204.0",
        "gas_components": [
            {
                "gas": "CO2",
                "factor_id": "COMB_GAS_NAT_CO2_DEFRA_2025",
                "factor_value": "1.95",
                "contribution_tco2e": "44321.0",
            }
        ],
    },
    "factor_metadata": {
        "primary_factor_id": "COMB_GAS_NAT_CO2_DEFRA_2025",
        "factor_db_id": "uuid-1234",
        "factor_version": "2025",
        "factor_source": "DEFRA",
        "vintage": "2025",
        "vintage_offset_applied": False,
        "unit": "kg CO2 / Sm3",
    },
    "gwp_set": "AR6",
    "methodology": "activity-based",
    "regulatory_stream": "CSRD_ESRS_E1",
    "disclosure_notes": "Combustion GAS_NAT: CO2 factor applied.",
    "dq_findings": [{"rule": "anno_within_window", "severity": "PASS"}],
}

_INSERT_RESPONSE = {
    **_PREVIEW_RESPONSE,
    "emission_id": "new-row-uuid-1234",
    "audit_log_id": "audit-uuid-5678",
}


def _mock_response(
    status_code: int,
    json_body: dict | None = None,
    text: str = "",
) -> MagicMock:
    """Build a mock httpx.Response with the given status code and optional JSON body."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = Exception("no json")
    return resp


# ---------------------------------------------------------------------------
# AutoCalcError
# ---------------------------------------------------------------------------


class TestAutoCalcError:
    """Basic AutoCalcError construction and attribute access."""

    def test_stores_detail(self) -> None:
        exc = AutoCalcError("Nessun fattore trovato.")
        assert exc.detail == "Nessun fattore trovato."

    def test_is_exception(self) -> None:
        assert isinstance(AutoCalcError("x"), Exception)

    def test_str_is_detail(self) -> None:
        exc = AutoCalcError("hello")
        assert str(exc) == "hello"


# ---------------------------------------------------------------------------
# calc_preview — success paths
# ---------------------------------------------------------------------------


class TestCalcPreview200:
    """calc_preview returns parsed JSON on HTTP 200."""

    def test_returns_dict_on_200(self) -> None:
        mock_resp = _mock_response(200, _PREVIEW_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            result = calc_preview(_MINIMAL_PAYLOAD, token="bearer-tok")

        assert result["tco2e"] == "44530.123456"
        assert result["gwp_set"] == "AR6"
        mock_post.assert_called_once()

    def test_sends_correct_endpoint(self) -> None:
        mock_resp = _mock_response(200, _PREVIEW_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            calc_preview(_MINIMAL_PAYLOAD, token="tok")

        url = mock_post.call_args.args[0]
        assert "/api/v1/calc/preview" in url

    def test_attaches_bearer_token(self) -> None:
        mock_resp = _mock_response(200, _PREVIEW_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            calc_preview(_MINIMAL_PAYLOAD, token="my-jwt-token")

        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer my-jwt-token"

    def test_sends_payload_as_json(self) -> None:
        mock_resp = _mock_response(200, _PREVIEW_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            calc_preview(_MINIMAL_PAYLOAD, token="tok")

        sent_json = mock_post.call_args.kwargs["json"]
        assert sent_json == _MINIMAL_PAYLOAD

    def test_also_accepts_201(self) -> None:
        """The spec says 200; accept 201 for forward-compat."""
        mock_resp = _mock_response(201, _PREVIEW_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            result = calc_preview(_MINIMAL_PAYLOAD, token="tok")

        assert "tco2e" in result


# ---------------------------------------------------------------------------
# calc_preview — error paths
# ---------------------------------------------------------------------------


class TestCalcPreviewErrors:
    """calc_preview raises AutoCalcError on all non-200 responses and network errors."""

    def test_raises_on_422_missing_factor(self) -> None:
        """422 with a detail field → AutoCalcError(detail)."""
        body = {"detail": "MissingFactorError: no factor for (GAS_NAT, 2024, AR6)."}
        mock_resp = _mock_response(422, body)
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_preview(_MINIMAL_PAYLOAD, token="tok")

        assert "MissingFactorError" in exc_info.value.detail

    def test_raises_on_422_unit_mismatch(self) -> None:
        body = {"detail": "UnitMismatchError: user unit 'MWh' not convertible to 'Sm3'."}
        mock_resp = _mock_response(422, body)
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_preview({**_MINIMAL_PAYLOAD, "unita": "MWh"}, token="tok")

        assert "UnitMismatchError" in exc_info.value.detail

    def test_raises_on_422_fastapi_list_detail(self) -> None:
        """FastAPI validation errors return detail as a list of dicts."""
        body = {
            "detail": [
                {
                    "loc": ["body", "anno"],
                    "msg": "value is not a valid integer",
                    "type": "type_error.integer",
                },
            ]
        }
        mock_resp = _mock_response(422, body)
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_preview({**_MINIMAL_PAYLOAD, "anno": "bad"}, token="tok")

        assert "value is not a valid integer" in exc_info.value.detail

    def test_raises_on_403_forbidden(self) -> None:
        """403 → AutoCalcError with a role-insufficient message (not the raw body)."""
        mock_resp = _mock_response(403, {"detail": "Forbidden."})
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_preview(_MINIMAL_PAYLOAD, token="viewer-tok")

        assert "Ruolo insufficiente" in exc_info.value.detail
        assert "editor" in exc_info.value.detail

    def test_raises_on_500_server_error(self) -> None:
        body = {"detail": "AmbiguousFactorError: more than one factor matched."}
        mock_resp = _mock_response(500, body)
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_preview(_MINIMAL_PAYLOAD, token="tok")

        assert "AmbiguousFactorError" in exc_info.value.detail

    def test_raises_on_network_error(self) -> None:
        """Network-level RequestError → AutoCalcError with 'Errore di rete'."""
        with (
            patch(
                _PATCH_POST,
                side_effect=httpx.RequestError("connection refused"),
            ),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_preview(_MINIMAL_PAYLOAD, token="tok")

        assert "Errore di rete" in exc_info.value.detail
        assert "backend non raggiungibile" in exc_info.value.detail

    def test_raises_on_no_json_body(self) -> None:
        """Non-JSON response body → AutoCalcError with raw text fallback."""
        mock_resp = _mock_response(422, text="Bad Gateway")
        mock_resp.json.side_effect = Exception("not json")
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_preview(_MINIMAL_PAYLOAD, token="tok")

        # Detail should be the raw text rather than an empty string
        assert exc_info.value.detail  # non-empty


# ---------------------------------------------------------------------------
# calc_insert — success paths
# ---------------------------------------------------------------------------


class TestCalcInsert201:
    """calc_insert returns parsed JSON (with emission_id) on HTTP 201."""

    def test_returns_dict_on_201(self) -> None:
        mock_resp = _mock_response(201, _INSERT_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            result = calc_insert(_MINIMAL_PAYLOAD, token="bearer-tok")

        assert result["emission_id"] == "new-row-uuid-1234"
        assert result["tco2e"] == "44530.123456"
        mock_post.assert_called_once()

    def test_sends_correct_endpoint(self) -> None:
        mock_resp = _mock_response(201, _INSERT_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            calc_insert(_MINIMAL_PAYLOAD, token="tok")

        url = mock_post.call_args.args[0]
        assert "/api/v1/calc/insert" in url

    def test_attaches_bearer_token(self) -> None:
        mock_resp = _mock_response(201, _INSERT_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            calc_insert(_MINIMAL_PAYLOAD, token="my-jwt-token")

        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer my-jwt-token"

    def test_also_accepts_200(self) -> None:
        """Accept 200 for forward-compat in case the backend returns it."""
        mock_resp = _mock_response(200, _INSERT_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            result = calc_insert(_MINIMAL_PAYLOAD, token="tok")

        assert "emission_id" in result

    def test_idempotency_key_forwarded(self) -> None:
        """idempotency_key in payload is forwarded to the API unchanged."""
        payload_with_key = {
            **_MINIMAL_PAYLOAD,
            "idempotency_key": "idem-uuid-xyz",
        }
        mock_resp = _mock_response(201, _INSERT_RESPONSE)
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            calc_insert(payload_with_key, token="tok")

        sent_json = mock_post.call_args.kwargs["json"]
        assert sent_json.get("idempotency_key") == "idem-uuid-xyz"


# ---------------------------------------------------------------------------
# calc_insert — error paths
# ---------------------------------------------------------------------------


class TestCalcInsertErrors:
    """calc_insert raises AutoCalcError on all non-201 responses and network errors."""

    def test_raises_on_422_dq_failure(self) -> None:
        """422 from DQ pre-insert validation → AutoCalcError."""
        body = {"detail": "DQ-CRIT: tco2e < 0 is not allowed."}
        mock_resp = _mock_response(422, body)
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_insert(_MINIMAL_PAYLOAD, token="tok")

        assert "DQ-CRIT" in exc_info.value.detail

    def test_raises_on_422_missing_factor_on_insert(self) -> None:
        body = {"detail": "MissingFactorError: factor expired for vintage=2023, anno=2024."}
        mock_resp = _mock_response(422, body)
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_insert(_MINIMAL_PAYLOAD, token="tok")

        assert "MissingFactorError" in exc_info.value.detail

    def test_raises_on_403_insufficient_role(self) -> None:
        mock_resp = _mock_response(403, {"detail": "Forbidden."})
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_insert(_MINIMAL_PAYLOAD, token="viewer-tok")

        assert "Ruolo insufficiente" in exc_info.value.detail

    def test_raises_on_409_conflict(self) -> None:
        """409 Conflict (duplicate active row) → AutoCalcError."""
        body = {
            "detail": (
                "Conflict: active row already exists for (IANO, combustion, 2024, AR6). "
                "Use the FR-21 correction endpoint."
            )
        }
        mock_resp = _mock_response(409, body)
        with (
            patch(_PATCH_POST, return_value=mock_resp),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_insert(_MINIMAL_PAYLOAD, token="tok")

        assert "Conflict" in exc_info.value.detail

    def test_raises_on_network_error(self) -> None:
        with (
            patch(
                _PATCH_POST,
                side_effect=httpx.RequestError("timed out"),
            ),
            patch(_PATCH_BASE, return_value=_BASE),
            pytest.raises(AutoCalcError) as exc_info,
        ):
            calc_insert(_MINIMAL_PAYLOAD, token="tok")

        assert "Errore di rete" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Scope 3 payload path (regression: Cat key normalization)
# ---------------------------------------------------------------------------


class TestCalcPreviewScope3Payload:
    """calc_preview forwards Scope 3 payloads without modification."""

    def test_scope3_cat1_payload_forwarded(self) -> None:
        s3_payload = {
            "scope": 3,
            "sub_scope": "Cat1",
            "categoria_s3": 1,
            "sottocategoria": "Argille",
            "metodo": "mass-based",
            "codice_sito": None,
            "anno": 2024,
            "quantita": "1500.000000",
            "unita": "t",
            "gwp_set": "AR6",
            "regulatory_stream": "CSRD_ESRS_E1",
        }
        mock_resp = _mock_response(200, {**_PREVIEW_RESPONSE, "tco2e": "120.000000"})
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            result = calc_preview(s3_payload, token="tok")

        sent = mock_post.call_args.kwargs["json"]
        assert sent["scope"] == 3
        assert sent["sub_scope"] == "Cat1"
        assert sent["categoria_s3"] == 1
        assert sent["metodo"] == "mass-based"
        assert result["tco2e"] == "120.000000"

    def test_scope2_mb_payload_with_strumento(self) -> None:
        mb_payload = {
            "scope": 2,
            "sub_scope": "MB",
            "strumento_mb": "GO",
            "codice_sito": "VIANO",
            "anno": 2024,
            "quantita": "500000.000000",
            "unita": "kWh",
            "gwp_set": "AR6",
            "regulatory_stream": "CSRD_ESRS_E1",
        }
        mock_resp = _mock_response(200, {**_PREVIEW_RESPONSE, "tco2e": "0.000000"})
        with (
            patch(_PATCH_POST, return_value=mock_resp) as mock_post,
            patch(_PATCH_BASE, return_value=_BASE),
        ):
            calc_preview(mb_payload, token="tok")

        sent = mock_post.call_args.kwargs["json"]
        assert sent["strumento_mb"] == "GO"
        assert sent["sub_scope"] == "MB"
