"""GHG Accounting Tool — FastAPI application package.

Exposes the FastAPI ``app`` instance created in ``main.py``.  All routers
live under ``routers/``; shared Pydantic v2 schemas under ``schemas/``.
"""

from ghg_tool.api.main import app

__all__ = ["app"]
