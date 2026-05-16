"""Celery application factory — REV-WAVE3-007.

Instantiates the shared ``celery_app`` object used by all task modules and by
the worker process launched via:

    celery -A ghg_tool.infrastructure.celery_app worker ...

Environment variables:
    CELERY_BROKER_URL         Redis broker (default redis://localhost:6379/1).
    CELERY_RESULT_BACKEND     Redis result backend (default redis://localhost:6379/2).

Task configuration:
    task_serializer / accept_content / result_serializer = "json"
        Enforces JSON-only serialisation; protects against pickle-based
        deserialization attacks (SEC baseline).
    timezone = "UTC" / enable_utc = True
        All timestamps are UTC — consistent with the rest of the platform.
    task_track_started = True
        Workers publish STARTED state so callers can distinguish queued from
        actively-running jobs.
    task_time_limit = 600
        10-minute hard kill — PDF/Excel renders should never take longer.
    task_soft_time_limit = 540
        9-minute soft warning — allows graceful cleanup before hard kill.
"""

from __future__ import annotations

import os
from typing import Final

from celery import Celery

celery_app = Celery(
    "ghg_tool",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
)

# Task execution limits — calibrated for WeasyPrint PDF builds + Excel reports.
_TASK_HARD_LIMIT_S: Final[int] = 600
_TASK_SOFT_LIMIT_S: Final[int] = 540
_RESULT_TTL_S: Final[int] = 86_400  # 24 hours

celery_app.conf.update(
    # Serialisation — JSON only (no pickle)
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Time zone
    timezone="UTC",
    enable_utc=True,
    # State tracking
    task_track_started=True,
    # Time limits (seconds)
    task_time_limit=_TASK_HARD_LIMIT_S,       # hard kill at 10 min
    task_soft_time_limit=_TASK_SOFT_LIMIT_S,  # soft warning at 9 min
    # Result expiry — keep results for 24 h so status polls can be served
    result_expires=_RESULT_TTL_S,
)
