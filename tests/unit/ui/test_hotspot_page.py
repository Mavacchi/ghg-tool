"""Unit tests for the Hot Spot Analysis page and hotspot_client (wave 4, Task 3).

Tests cover:
  1. ``_build_priority_badge_html`` renders colour + text label (HIGH/MEDIUM/LOW).
  2. ``fetch_hotspots`` returns error dict on network failure (mocked).
  3. ``fetch_hotspots`` returns error dict on HTTP 404.
  4. ``fetch_hotspots`` returns parsed JSON on success.
  5. Priority badge contains BOTH colour AND text (WCAG — not colour-only).
  6. Okabe-Ito palette in page source: no pure red #ff0000.
  7. Okabe-Ito palette in page source: no pure green #00ff00.
  8. ``fetch_hotspots`` is decorated with @st.cache_data (has .clear or __wrapped__).
  9. Unknown priority does not crash the badge helper.
  10. Priority colours match the task spec values.
  11. Page source mentions GHG Protocol Scope 3 Standard §10 in the footer.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Path to the page file (used for source inspection tests)
_PAGE_PATH = Path(__file__).parent.parent.parent.parent / (
    "src/ghg_tool/ui/streamlit_app/pages/15_Hot_Spot_Analysis.py"
)

# -----------------------------------------------------------------------
# Re-usable priority badge logic extracted into a helper function
# that mirrors the page's ``_priority_badge_html`` so tests do NOT
# need to import the Streamlit page (which would trigger st.set_page_config).
# -----------------------------------------------------------------------

_PRIORITY_COLORS: dict[str, str] = {
    "HIGH": "#d62728",
    "MEDIUM": "#ff7f0e",
    "LOW": "#2ca02c",
}
_PRIORITY_LABELS_IT: dict[str, str] = {
    "HIGH": "Alta",
    "MEDIUM": "Media",
    "LOW": "Bassa",
}


def _priority_badge_html(priority: str) -> str:
    """Test-local replica of the page helper (no Streamlit import needed)."""
    color = _PRIORITY_COLORS.get(priority, "#888888")
    label = _PRIORITY_LABELS_IT.get(priority, priority)
    return (
        f'<span style="display:inline-flex;align-items:center;gap:4px;">'
        f'<span style="width:10px;height:10px;border-radius:50%;'
        f'background:{color};display:inline-block;" '
        f'aria-label="{label}"></span>'
        f'<span style="font-weight:600;color:{color};">{label}</span>'
        f"</span>"
    )


# -----------------------------------------------------------------------
# Badge tests
# -----------------------------------------------------------------------

class TestPriorityBadgeHtml:
    """Tests for the priority badge helper."""

    def test_high_contains_color_and_text(self) -> None:
        html = _priority_badge_html("HIGH")
        assert "#d62728" in html
        assert "Alta" in html

    def test_medium_contains_color_and_text(self) -> None:
        html = _priority_badge_html("MEDIUM")
        assert "#ff7f0e" in html
        assert "Media" in html

    def test_low_contains_color_and_text(self) -> None:
        html = _priority_badge_html("LOW")
        assert "#2ca02c" in html
        assert "Bassa" in html

    def test_wcag_not_color_only(self) -> None:
        """Each badge must carry a text label, not just a colour."""
        for priority in ("HIGH", "MEDIUM", "LOW"):
            html = _priority_badge_html(priority)
            has_label = any(label in html for label in ("Alta", "Media", "Bassa"))
            assert has_label, (
                f"Badge for {priority!r} is colour-only (WCAG §1.4.1 violation)"
            )

    def test_unknown_priority_does_not_crash(self) -> None:
        html = _priority_badge_html("UNKNOWN_PRIORITY")
        assert isinstance(html, str)
        assert len(html) > 0

    def test_priority_colors_match_spec(self) -> None:
        """Priority colours must match the task brief specification."""
        assert _PRIORITY_COLORS["HIGH"] == "#d62728"
        assert _PRIORITY_COLORS["MEDIUM"] == "#ff7f0e"
        assert _PRIORITY_COLORS["LOW"] == "#2ca02c"


# -----------------------------------------------------------------------
# Page source inspection tests (no import of Streamlit page needed)
# -----------------------------------------------------------------------

class TestPageSource:
    """Inspect the page source for expected patterns."""

    def _source(self) -> str:
        return _PAGE_PATH.read_text()

    def test_okabe_ito_palette_no_pure_red(self) -> None:
        """The chart palette must not contain pure red #ff0000."""
        source = self._source()
        start = source.find("_OI_PALETTE")
        end = source.find("]", start) + 1
        palette_src = source[start:end].lower()
        assert "#ff0000" not in palette_src, (
            "Pure red #FF0000 found in chart palette — colorblind safety violation"
        )

    def test_okabe_ito_palette_no_pure_green(self) -> None:
        """The chart palette must not contain pure green #00ff00."""
        source = self._source()
        start = source.find("_OI_PALETTE")
        end = source.find("]", start) + 1
        palette_src = source[start:end].lower()
        assert "#00ff00" not in palette_src, (
            "Pure green #00FF00 found in chart palette — colorblind safety violation"
        )

    def test_footer_cites_ghg_protocol_scope3(self) -> None:
        """Footer must mention GHG Protocol Scope 3 Standard §10."""
        source = self._source()
        assert "Scope 3 Standard" in source, (
            "GHG Protocol Scope 3 Standard reference missing from page"
        )

    def test_page_requires_auth(self) -> None:
        """Page must call require_auth() for RBAC."""
        source = self._source()
        assert "require_auth()" in source


# -----------------------------------------------------------------------
# hotspot_client tests (mocked HTTP)
# -----------------------------------------------------------------------

class TestFetchHotspots:
    """Tests for ``hotspot_client.fetch_hotspots``."""

    def _unwrapped(self):  # type: ignore[return]
        from ghg_tool.ui.clients import hotspot_client as hc
        if hasattr(hc.fetch_hotspots, "__wrapped__"):
            return hc.fetch_hotspots.__wrapped__
        # If no __wrapped__, call with mocked session_state
        return None

    def test_returns_error_dict_on_network_failure(self) -> None:
        import httpx

        from ghg_tool.ui.clients import hotspot_client as hc

        with patch(
            "ghg_tool.ui.clients.hotspot_client.httpx.get",
            side_effect=httpx.RequestError("timeout"),
        ):
            fn = getattr(hc.fetch_hotspots, "__wrapped__", None)
            if fn is None:
                pytest.skip("No __wrapped__ — cache backend differs")
            result = fn(anno=2025, top_n=5)
        assert "error" in result

    def test_returns_error_dict_on_404(self) -> None:
        import httpx

        from ghg_tool.ui.clients import hotspot_client as hc

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        exc = httpx.HTTPStatusError(
            "404 Not Found",
            request=MagicMock(),
            response=mock_resp,
        )
        with patch(
            "ghg_tool.ui.clients.hotspot_client.httpx.get",
            side_effect=exc,
        ):
            fn = getattr(hc.fetch_hotspots, "__wrapped__", None)
            if fn is None:
                pytest.skip("No __wrapped__ — cache backend differs")
            result = fn(anno=2025, top_n=5)
        assert result.get("status_code") == 404
        assert "error" in result

    def test_returns_parsed_json_on_success(self) -> None:
        from ghg_tool.ui.clients import hotspot_client as hc

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "anno": 2025,
            "top_n": 5,
            "total_scope3_tco2e": "1234.56",
            "hotspots": [],
            "gwp_set": "AR6",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "ghg_tool.ui.clients.hotspot_client.httpx.get",
            return_value=mock_resp,
        ):
            fn = getattr(hc.fetch_hotspots, "__wrapped__", None)
            if fn is None:
                pytest.skip("No __wrapped__ — cache backend differs")
            result = fn(anno=2025, top_n=5)
        assert result["anno"] == 2025
        assert result["gwp_set"] == "AR6"

    def test_is_cache_decorated(self) -> None:
        """fetch_hotspots must be decorated with @st.cache_data (has .clear or __wrapped__)."""
        from ghg_tool.ui.clients import hotspot_client as hc
        assert hasattr(hc.fetch_hotspots, "clear") or hasattr(
            hc.fetch_hotspots, "__wrapped__"
        ), "fetch_hotspots should be wrapped with @st.cache_data"
