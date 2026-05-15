"""Root conftest for the worktree.

Ensures the worktree's own src/ directory takes precedence over the
editable-install path of the main repository.  This is necessary because
all git worktrees share the same Python environment (and the same .pth
file that points at the main repo's src/).

Without this, pytest would import ghg_tool from /home/user/ghg-tool/src
rather than from this worktree, causing locally-edited modules (e.g.
api/routers/factor_catalog.py, api/schemas/factor_schemas.py) to be
ignored.
"""

from __future__ import annotations

import pathlib
import sys

# Prepend this worktree's src/ so it shadows the main-repo editable install.
_WORKTREE_SRC = str(pathlib.Path(__file__).parent / "src")
if _WORKTREE_SRC not in sys.path:
    sys.path.insert(0, _WORKTREE_SRC)
