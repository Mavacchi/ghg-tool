"""Unit tests for formula-injection sanitisation in Streamlit exports (BUG-07).

Verifies that cells whose first character is in ``{=, +, -, @, \\t, \\r}`` are
prefixed with a single quote before serialisation to CSV and XLSX.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from ghg_tool.ui.streamlit_app.lib.exports import (
    _FORMULA_TRIGGER_CHARS,
    _df_to_csv_bytes,
    _df_to_xlsx_bytes,
    _sanitise_cell,
    _sanitise_dataframe,
)

# ---------------------------------------------------------------------------
# _sanitise_cell unit tests
# ---------------------------------------------------------------------------


class TestSanitiseCell:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            # Confirmed injection triggers
            ('=cmd|"/c calc"!A1', '\'=cmd|"/c calc"!A1'),
            ("+1234", "'+1234"),
            ("-ROUND(A1)", "'-ROUND(A1)"),
            ("@SUM(A1:A9)", "'@SUM(A1:A9)"),
            ("\tspace", "'\tspace"),
            ("\rcarriage", "'\rcarriage"),
            # Safe values — must not be prefixed
            ("normal string", "normal string"),
            ("123.45", "123.45"),
            ("", ""),
            # Non-string types — must pass through unchanged
            (42, 42),
            (3.14, 3.14),
            (None, None),
            (True, True),
        ],
    )
    def test_sanitise_cell(self, raw: object, expected: object) -> None:
        assert _sanitise_cell(raw) == expected

    def test_trigger_chars_complete(self) -> None:
        """Verify the trigger set contains exactly the documented characters."""
        expected = frozenset({"=", "+", "-", "@", "\t", "\r"})
        assert expected == _FORMULA_TRIGGER_CHARS

    def test_empty_string_not_prefixed(self) -> None:
        """Empty string has no first character — must not be prefixed."""
        assert _sanitise_cell("") == ""

    def test_non_trigger_first_char_not_prefixed(self) -> None:
        for ch in "abcABC0123 !#$%^&*()":
            assert _sanitise_cell(ch + "rest") == ch + "rest"


# ---------------------------------------------------------------------------
# _sanitise_dataframe unit tests
# ---------------------------------------------------------------------------


class TestSanitiseDataframe:
    def test_note_column_formula_injection(self) -> None:
        """Core BUG-07 scenario: note field with formula-injection payload."""
        df = pd.DataFrame(
            {
                "facility_id": ["FAC1"],
                "tco2e": [1.5],
                "note": ['=cmd|"/c calc"!A1'],
            }
        )
        result = _sanitise_dataframe(df)
        assert result["note"].iloc[0] == '\'=cmd|"/c calc"!A1'

    def test_non_string_columns_unchanged(self) -> None:
        df = pd.DataFrame({"x": [1, 2, 3], "y": [1.0, 2.0, 3.0]})
        result = _sanitise_dataframe(df)
        pd.testing.assert_frame_equal(result, df)

    def test_none_returns_none(self) -> None:
        assert _sanitise_dataframe(None) is None

    def test_multiple_trigger_rows(self) -> None:
        df = pd.DataFrame(
            {"note": ["=A1", "+B2", "-C3", "@D4", "safe", "\ttab", "\rret"]}
        )
        result = _sanitise_dataframe(df)
        # Indices 0-3 and 5-6 are trigger characters; index 4 is safe.
        trigger_indices = [0, 1, 2, 3, 5, 6]
        for i in trigger_indices:
            val = result["note"].iloc[i]
            assert val.startswith("'"), f"Row {i} not prefixed: {val!r}"
        # Safe row (index 4) must NOT be prefixed.
        assert result["note"].iloc[4] == "safe"


# ---------------------------------------------------------------------------
# _df_to_csv_bytes integration tests
# ---------------------------------------------------------------------------


class TestDfToCsvBytes:
    def test_formula_injection_in_csv(self) -> None:
        """BUG-07: row with note='=cmd...' exports with a leading single-quote prefix."""
        df = pd.DataFrame(
            {
                "facility_id": ["FAC1"],
                "note": ["=DANGEROUS_FORMULA"],
            }
        )
        csv_bytes = _df_to_csv_bytes(df)
        csv_text = csv_bytes.decode("utf-8")
        # The sanitised cell starts with a single-quote prefix; the raw formula
        # must not appear as the first character in the field value.
        assert "'=DANGEROUS_FORMULA" in csv_text, (
            f"Expected prefixed formula in CSV; got: {csv_text!r}"
        )
        # The raw formula without the prefix must not appear standalone.
        # CSV quoting may wrap the value; check the raw cell value via the
        # sanitised dataframe directly.
        sanitised_df = _sanitise_dataframe(df)
        assert sanitised_df["note"].iloc[0] == "'=DANGEROUS_FORMULA"

    def test_none_returns_empty_bytes(self) -> None:
        assert _df_to_csv_bytes(None) == b""

    def test_safe_values_unmodified_in_csv(self) -> None:
        df = pd.DataFrame({"a": ["hello"], "b": [42]})
        csv_bytes = _df_to_csv_bytes(df)
        assert b"hello" in csv_bytes


# ---------------------------------------------------------------------------
# _df_to_xlsx_bytes integration tests
# ---------------------------------------------------------------------------


class TestDfToXlsxBytes:
    def test_formula_injection_in_xlsx(self) -> None:
        """BUG-07: XLSX cell value for formula-injection note is prefixed."""
        pytest.importorskip("openpyxl")
        import openpyxl

        df = pd.DataFrame(
            {
                "facility_id": ["FAC1"],
                "note": ['=cmd|"/c calc"!A1'],
            }
        )
        xlsx_bytes = _df_to_xlsx_bytes(df)
        assert xlsx_bytes  # non-empty

        # Load the workbook and verify the cell value.
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
        ws = wb.active
        # Row 1 is header; row 2 is data.  note is column 2 (B).
        note_cell = ws.cell(row=2, column=2).value
        assert note_cell == '\'=cmd|"/c calc"!A1', (
            f"Expected prefixed formula, got: {note_cell!r}"
        )

    def test_none_returns_empty_bytes(self) -> None:
        assert _df_to_xlsx_bytes(None) == b""
