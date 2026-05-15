"""Meta-test: grep guard ensuring no UPDATE ops.calc_runs statement exists in src/.

This test fails if any future PR introduces an UPDATE statement targeting
ops.calc_runs (with or without the schema prefix) anywhere under src/.

Normative basis:
  - Q2 Decision (compliance-agent): "No UPDATE ops.calc_runs statement may
    exist anywhere in calc_persistence.py. Add a code-level guard:
    grep -RnE 'UPDATE\\s+(ops\\.)?calc_runs' in pre-commit returns zero matches."
  - methodology.md §7 (Audit Trail Integrity): ops.calc_runs is append-only.
  - trg_deny_calc_runs_mutation (migration 0023_M22) enforces this at DB level;
    this test enforces it at source-code level.

This test requires no DB and runs in the standard unit test suite.  It is
cheap (~milliseconds) and must always pass — it is not marked as integration.
"""

from __future__ import annotations

import os
import re
import subprocess


_SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "src")
)

_PATTERN = re.compile(r"UPDATE\s+(ops\.)?calc_runs", re.IGNORECASE)


def test_no_update_calc_runs_in_src() -> None:
    """Assert that no Python source file under src/ contains UPDATE calc_runs.

    Uses Python re scanning rather than subprocess grep to ensure portability
    across CI environments where grep may have different flag semantics.

    Raises:
        AssertionError: if any match is found, listing each offending file and
            line number so the developer can fix it immediately.
    """
    violations: list[str] = []

    for root, dirs, files in os.walk(_SRC_DIR):
        # Skip compiled bytecode directories
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for filename in files:
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if _PATTERN.search(line):
                            violations.append(f"{filepath}:{lineno}: {line.rstrip()}")
            except (OSError, UnicodeDecodeError):
                # Skip files that cannot be read (binary, permissions, etc.)
                continue

    assert not violations, (
        "Q2 compliance violation: UPDATE ops.calc_runs found in src/ — "
        "ops.calc_runs is append-only (methodology §7 + migration 0023_M22).\n"
        "Offending lines:\n"
        + "\n".join(violations)
    )


def test_no_update_calc_runs_grep_subprocess() -> None:
    """Subprocess grep variant of the same guard (CI pre-commit hook equivalent).

    Skipped on platforms where grep is not available.  The Python re test above
    is the canonical check; this test provides defence-in-depth using the same
    tool a pre-commit hook would use.
    """
    try:
        result = subprocess.run(
            ["grep", "-RnE", r"UPDATE\s+(ops\.)?calc_runs", _SRC_DIR],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        # grep not available (Windows / restricted CI)
        return

    assert result.returncode != 0 or result.stdout.strip() == "", (
        "Q2 compliance violation: grep found UPDATE calc_runs in src/:\n"
        + result.stdout
    )
