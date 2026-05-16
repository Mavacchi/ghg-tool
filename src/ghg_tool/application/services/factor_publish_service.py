"""FactorPublishService — orchestrates the two-eyes factor publish workflow.

Extracts the business logic from the factor_catalog router so the router
keeps only HTTP orchestration (auth, dependency resolution, HTTP response).

The service owns:
- ``_assert_publishable`` — pre-condition checks (tbc / null value).
- ``_do_publish`` — the actual False->True transition + audit write.
- ``publish`` — full orchestration: fetch factor, assert publishable, branch
  on approval state, create PENDING row (202) or execute publish (200).

Returns typed ``PublishResult`` so the router can map to HTTP responses
without knowing domain semantics.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.infrastructure.db.models.audit_log import AuditLog
from ghg_tool.infrastructure.db.models.factor import FactorCatalog
from ghg_tool.infrastructure.db.models.factor_publish_approval import FactorPublishApproval
from ghg_tool.infrastructure.db.repositories.factor_catalog_repository import (
    FactorCatalogRepository,
)
from ghg_tool.infrastructure.security import siem

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result types — returned by publish() so the router maps to HTTP responses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublishResultApprovalRequested:
    """First admin called /publish -> PENDING approval created, 202 expected."""

    outcome: Literal["approval_requested"] = "approval_requested"
    approval_id: uuid.UUID = uuid.UUID(int=0)


@dataclass(frozen=True)
class PublishResultPublished:
    """Second admin called /publish -> factor published, 200 expected.

    ``factor_response`` holds the validated Pydantic response model.  It is
    typed as ``Any`` here to avoid a circular import with ``ghg_tool.api``
    (which imports ``ghg_tool.api.main`` on package init).  The router casts
    it to ``FactorCatalogPublishResponse`` before returning.
    """

    outcome: Literal["published"] = "published"
    factor_response: Any = None


PublishResult = PublishResultApprovalRequested | PublishResultPublished


# ---------------------------------------------------------------------------
# Domain errors — raised by the service; router maps these to HTTP responses
# ---------------------------------------------------------------------------


class FactorNotFoundError(Exception):
    """Factor UUID not found within the caller's tenant."""


class FactorAlreadyPublishedError(Exception):
    """Factor is already published (409)."""

    def __init__(self, factor_id: str, version: str) -> None:
        self.factor_id = factor_id
        self.version = version
        super().__init__(f"Factor {factor_id}/{version} is already published")


class FactorTbcError(Exception):
    """Factor is marked is_tbc=True and cannot be published (422)."""

    def __init__(self, factor_id: str, version: str) -> None:
        self.factor_id = factor_id
        self.version = version
        super().__init__(f"Factor {factor_id}/{version} is marked TBC")


class FactorNullValueError(Exception):
    """Factor has NULL value and is_licence_only=False (422)."""

    def __init__(self, factor_id: str, version: str) -> None:
        self.factor_id = factor_id
        self.version = version
        super().__init__(f"Factor {factor_id}/{version} has NULL value")


class SelfApprovalCreatorError(Exception):
    """Creator of the factor tried to approve publication (409, ISAE 3000)."""


class SelfApprovalForbiddenError(Exception):
    """Same proposer tried to approve their own pending request (409)."""


class PublishRaceConflictError(Exception):
    """Concurrent publisher won the race; UPDATE rowcount was 0 (409)."""

    def __init__(self, factor_id: str, version: str) -> None:
        self.factor_id = factor_id
        self.version = version
        super().__init__(f"Factor {factor_id}/{version} was published concurrently")


# ---------------------------------------------------------------------------
# UserContext protocol — decoupled from CurrentUser to avoid api -> service dep
# ---------------------------------------------------------------------------


class UserContext:
    """Minimal user information needed by the service.

    Accepts the ``CurrentUser`` Pydantic model from the router layer directly
    (structural typing — duck-typed). Also accepts plain objects with the same
    attributes in tests.
    """

    def __init__(self, sub: str, role: str, tenant_id: str) -> None:
        self.sub = sub
        self.role = role
        self.tenant_id = tenant_id

    @classmethod
    def from_current_user(cls, user: Any) -> "UserContext":
        """Build a UserContext from a CurrentUser dependency."""
        return cls(sub=user.sub, role=user.role, tenant_id=user.tenant_id)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class FactorPublishService:
    """Orchestrates the two-eyes factor publish workflow.

    Injected with a repository for factor lookup and the async session for
    writing audit rows. The session is owned by the caller (router); the
    service does not commit or rollback.

    Args:
        session: Async SQLAlchemy session (transaction managed by router/middleware).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = FactorCatalogRepository(session)

    # ------------------------------------------------------------------
    # Pre-condition checks
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_publishable(factor: FactorCatalog) -> None:
        """Raise a domain error if the factor cannot be published.

        Args:
            factor: Draft FactorCatalog ORM row.

        Raises:
            FactorTbcError: If ``is_tbc=True``.
            FactorNullValueError: If ``value`` is NULL and not licence-only.
        """
        if factor.is_tbc:
            raise FactorTbcError(factor.factor_id, factor.version)

        if factor.value is None and not factor.is_licence_only:
            raise FactorNullValueError(factor.factor_id, factor.version)

    # ------------------------------------------------------------------
    # Publish transition
    # ------------------------------------------------------------------

    async def _do_publish(
        self,
        *,
        factor: FactorCatalog,
        user: UserContext,
        approval: FactorPublishApproval,
        correlation_id: str,
        client_ip: str | None,
        user_agent: str | None,
        log: Any,
    ) -> Any:
        """Returns a FactorCatalogPublishResponse (typed as Any to avoid circular import)."""
        """Execute the False->True publish transition and write audit rows.

        Called only when a second admin approves an existing PENDING row.
        Runs entirely within the caller's DB session (same transaction as the
        approval UPDATE).

        Args:
            factor: Draft FactorCatalog ORM row.
            user: Authenticated approving admin.
            approval: The PENDING FactorPublishApproval row being approved.
            correlation_id: Request trace ID.
            client_ip: Caller IP address for audit.
            user_agent: Caller user-agent header for audit.
            log: Bound structlog logger.

        Returns:
            FactorCatalogPublishResponse with is_published=True.

        Raises:
            SelfApprovalCreatorError: If the factor creator tries to approve.
            PublishRaceConflictError: If a concurrent publisher won the race.
        """
        now_utc = datetime.now(tz=UTC)

        # C-006 / C-004: creator cannot also approve (ISAE 3000 two-eyes).
        factor_created_by = getattr(factor, "created_by", None)
        if factor_created_by is not None and str(factor_created_by) == user.sub:
            log.warning(
                "publish_factor_self_approval_creator_blocked",
                factor_id=factor.factor_id,
                user_sub=user.sub[:8],
            )
            siem.emit(
                event="factor_self_approval_creator_attempt",
                correlation_id=correlation_id,
                tenant_id=user.tenant_id,
                user_sub=user.sub,
                severity="HIGH",
                payload={
                    "factor_id": factor.factor_id,
                    "version": factor.version,
                    "created_by": str(factor_created_by),
                    "approver": user.sub,
                },
            )
            raise SelfApprovalCreatorError()

        # Conditional UPDATE guards against concurrent publishers.
        update_stmt = (
            update(FactorCatalog)
            .where(
                FactorCatalog.id == factor.id,
                FactorCatalog.tenant_id == uuid.UUID(user.tenant_id),
                FactorCatalog.is_published.is_(False),
            )
            .values(
                is_published=True,
                published_by=user.sub,
                published_at=now_utc,
            )
        )
        result = await self._session.execute(update_stmt)
        if result.rowcount != 1:
            log.warning("publish_factor_race_lost")
            raise PublishRaceConflictError(factor.factor_id, factor.version)

        # Mark the approval row as APPROVED.
        approval.decision = "APPROVED"
        approval.approved_by = uuid.UUID(user.sub)
        approval.approved_at = now_utc

        await self._session.refresh(factor)

        after_state: dict[str, Any] = {
            "factor_id": factor.factor_id,
            "version": factor.version,
            "gwp_set": factor.gwp_set,
            "source": factor.source,
            "scope": factor.scope,
            "published_by": user.sub,
            "published_at": now_utc.isoformat(),
            "reason_code": approval.reason_code,
            "approved_by": user.sub,
            "approval_id": str(approval.id),
        }
        self._session.add(
            AuditLog(
                tenant_id=uuid.UUID(user.tenant_id),
                correlation_id=uuid.UUID(correlation_id),
                user_role=user.role,
                action="factor_published",
                resource="factor_catalog",
                resource_id=factor.id,
                request_method="POST",
                request_path=f"/api/v1/factor-catalog/{factor.id}/publish",
                status_code=200,
                ip_address=client_ip,
                user_agent=user_agent,
                after_state=after_state,
            )
        )
        await self._session.flush()

        log.info(
            "factor_published",
            factor_id=factor.factor_id,
            version=factor.version,
            gwp_set=factor.gwp_set,
            published_by=user.sub,
            reason_code=approval.reason_code,
            approval_id=str(approval.id),
        )

        siem.emit(
            event="factor_published",
            correlation_id=correlation_id,
            tenant_id=user.tenant_id,
            user_sub=user.sub,
            severity="INFO",
            payload={
                "factor_id": factor.factor_id,
                "version": factor.version,
                "gwp_set": factor.gwp_set,
                "reason_code": approval.reason_code,
                "approval_id": str(approval.id),
            },
        )

        # Deferred import to avoid circular dependency with ghg_tool.api.
        from ghg_tool.api.schemas.factor_schemas import FactorCatalogPublishResponse  # noqa: PLC0415

        return FactorCatalogPublishResponse.model_validate(factor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish(
        self,
        factor_uuid: uuid.UUID,
        body: Any,
        *,
        user: UserContext,
        correlation_id: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> PublishResult:
        """``body`` is a FactorCatalogPublishRequest (typed as Any to avoid circular import)."""
        """Orchestrate the full two-eyes publish workflow.

        State machine:
        - No approval row + draft factor -> create PENDING row -> return
          PublishResultApprovalRequested (router returns 202).
        - PENDING row + same proposer -> SelfApprovalForbiddenError (409).
        - PENDING row + different admin -> publish + APPROVED -> return
          PublishResultPublished (router returns 200).
        - Factor already published -> FactorAlreadyPublishedError (409).

        Args:
            factor_uuid: UUID primary key of the draft factor row.
            body: Publish request payload with ``reason_code``.
            user: Authenticated admin context.
            correlation_id: Request trace ID.
            client_ip: Client IP for audit.
            user_agent: User-agent header for audit.

        Returns:
            PublishResultApprovalRequested or PublishResultPublished.

        Raises:
            FactorNotFoundError: Factor UUID not found in tenant.
            FactorAlreadyPublishedError: Factor is already published.
            FactorTbcError: Factor is marked TBC.
            FactorNullValueError: Factor has NULL value and is not licence-only.
            SelfApprovalForbiddenError: Same proposer cannot approve.
            SelfApprovalCreatorError: Creator cannot approve their own factor.
            PublishRaceConflictError: Concurrent publisher won.
        """
        log = logger.bind(
            correlation_id=correlation_id,
            user=user.sub[:8],
            tenant_id=user.tenant_id,
            factor_uuid=str(factor_uuid),
        )

        factor = await self._repo.get_by_uuid(
            tenant_id=uuid.UUID(user.tenant_id),
            factor_uuid=factor_uuid,
        )

        if factor is None:
            log.warning("publish_factor_not_found")
            raise FactorNotFoundError(f"Factor {factor_uuid} not found")

        if factor.is_published:
            log.warning("publish_factor_already_published")
            raise FactorAlreadyPublishedError(factor.factor_id, factor.version)

        # Run publish pre-conditions (tbc / null value) before touching approvals.
        self._assert_publishable(factor)

        # Fetch existing PENDING approval (if any).
        stmt = select(FactorPublishApproval).where(
            FactorPublishApproval.factor_id == factor.id,
            FactorPublishApproval.tenant_id == uuid.UUID(user.tenant_id),
            FactorPublishApproval.decision == "PENDING",
        )
        result = await self._session.execute(stmt)
        pending = result.scalar_one_or_none()

        if pending is None:
            # State 1: No PENDING row -> create it, signal 202.
            new_approval = FactorPublishApproval(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(user.tenant_id),
                factor_id=factor.id,
                proposed_by=uuid.UUID(user.sub),
                decision="PENDING",
                correlation_id=uuid.UUID(correlation_id),
                reason_code=body.reason_code,
            )
            self._session.add(new_approval)

            self._session.add(
                AuditLog(
                    tenant_id=uuid.UUID(user.tenant_id),
                    correlation_id=uuid.UUID(correlation_id),
                    user_role=user.role,
                    action="factor_approval_requested",
                    resource="factor_catalog",
                    resource_id=factor.id,
                    request_method="POST",
                    request_path=f"/api/v1/factor-catalog/{factor.id}/publish",
                    status_code=202,
                    ip_address=client_ip,
                    user_agent=user_agent,
                    after_state={
                        "approval_id": str(new_approval.id),
                        "factor_id": factor.factor_id,
                        "version": factor.version,
                        "reason_code": body.reason_code,
                        "proposed_by": user.sub,
                    },
                )
            )

            await self._session.flush()

            log.info(
                "factor_approval_requested",
                approval_id=str(new_approval.id),
                factor_id=factor.factor_id,
                reason_code=body.reason_code,
            )

            siem.emit(
                event="factor_approval_requested",
                correlation_id=correlation_id,
                tenant_id=user.tenant_id,
                user_sub=user.sub,
                severity="INFO",
                payload={
                    "factor_id": factor.factor_id,
                    "approval_id": str(new_approval.id),
                    "reason_code": body.reason_code,
                },
            )

            return PublishResultApprovalRequested(
                outcome="approval_requested",
                approval_id=new_approval.id,
            )

        # State 2: PENDING row exists + same proposer -> 409.
        if str(pending.proposed_by) == user.sub:
            log.warning("publish_factor_self_approval_blocked")
            raise SelfApprovalForbiddenError()

        # State 3: PENDING row + different admin -> approve and publish.
        factor_response = await self._do_publish(
            factor=factor,
            user=user,
            approval=pending,
            correlation_id=correlation_id,
            client_ip=client_ip,
            user_agent=user_agent,
            log=log,
        )
        return PublishResultPublished(outcome="published", factor_response=factor_response)
