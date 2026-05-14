"""SIEM webhook forwarder for security-relevant audit events.

When ``GHG_SIEM_WEBHOOK_URL`` env var is set, the API POSTs a small JSON
payload to that URL on every audit-relevant event (factor publish,
correction, waiver, user creation, repeated already_published spikes).
The forwarder is best-effort: failures are logged and never block the
primary operation. A 2-second timeout caps the worst-case latency.

Production note: for high-volume deployments the forwarder should sit
behind a queue (e.g. Redis stream) rather than a synchronous HTTP POST.
This implementation is the minimum viable signal that gets the audit
trail off-box; the queue is a follow-up.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_TIMEOUT_S = 2.0
_HEADER_NAME = "X-Carbontrace-Event"


def _webhook_url() -> str | None:
    """Return the configured webhook URL or None if SIEM forwarding is off."""
    url = os.environ.get("GHG_SIEM_WEBHOOK_URL", "").strip()
    return url if url else None


def emit(
    *,
    event: str,
    correlation_id: str | uuid.UUID | None,
    tenant_id: str | uuid.UUID | None = None,
    user_sub: str | None = None,
    severity: str = "INFO",
    payload: dict[str, Any] | None = None,
) -> None:
    """Forward an event to the configured SIEM endpoint.

    No-op when ``GHG_SIEM_WEBHOOK_URL`` is unset. Never raises - any
    network / serialisation failure is logged and swallowed so the
    caller's primary operation is unaffected.

    Args:
        event: Short event name (e.g. ``factor_published``).
        correlation_id: Request correlation UUID (or None).
        tenant_id: Tenant UUID for multi-tenant deployments.
        user_sub: Authenticated user's sub claim (truncated by caller).
        severity: One of INFO / WARN / ALERT / CRITICAL.
        payload: Free-form event-specific dict. No PII / no secrets.
    """
    url = _webhook_url()
    if not url:
        return

    body = {
        "event": event,
        "severity": severity,
        "correlation_id": str(correlation_id) if correlation_id else None,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "user_sub": user_sub[:8] if user_sub else None,
        "ts_unix": time.time(),
        "payload": payload or {},
    }
    try:
        # Local import - httpx is already a project dep; the lazy import
        # keeps the module light when SIEM is disabled.
        import httpx  # noqa: PLC0415

        resp = httpx.post(
            url,
            json=body,
            headers={_HEADER_NAME: event},
            timeout=_TIMEOUT_S,
        )
        if resp.status_code >= 400:
            logger.warning(
                "siem_webhook_non_2xx",
                status=resp.status_code,
                event=event,
            )
    except Exception as exc:  # noqa: BLE001 - best-effort fire-and-forget
        logger.warning(
            "siem_webhook_failed",
            event=event,
            error_class=type(exc).__name__,
        )
