"""Unit tests for FactorPublishService — _assert_publishable branches.

Covers:
- _assert_publishable: passes when value is set and is_tbc=False.
- _assert_publishable: raises FactorTbcError when is_tbc=True.
- _assert_publishable: raises FactorNullValueError when value=None, is_licence_only=False.
- _assert_publishable: passes when value=None AND is_licence_only=True.
- publish: raises FactorNotFoundError when repo returns None.
- publish: raises FactorAlreadyPublishedError when factor.is_published=True.
- publish: returns PublishResultApprovalRequested (202) on first call (no pending approval).
- publish: raises SelfApprovalForbiddenError when same proposer calls again.
- publish: returns PublishResultPublished (200) when second admin approves.
- publish: raises SelfApprovalCreatorError when creator tries to approve.

All DB access is mocked via AsyncMock; no live PostgreSQL instance required.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

import pytest

from ghg_tool.application.services.factor_publish_service import (
    FactorAlreadyPublishedError,
    FactorNotFoundError,
    FactorNullValueError,
    FactorPublishService,
    FactorTbcError,
    PublishRaceConflictError,
    PublishResultApprovalRequested,
    PublishResultPublished,
    SelfApprovalCreatorError,
    SelfApprovalForbiddenError,
    UserContext,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT = str(uuid.uuid4())
_ESG1 = str(uuid.uuid4())
_ESG2 = str(uuid.uuid4())
_CREATOR = str(uuid.uuid4())
_FACTOR_UUID = uuid.uuid4()
_APPROVAL_UUID = uuid.uuid4()
_CORRELATION_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_factor(
    *,
    is_published: bool = False,
    is_tbc: bool = False,
    is_licence_only: bool = False,
    value: float | None = 1.23,
    created_by: str | None = None,
) -> MagicMock:
    factor = MagicMock()
    factor.id = _FACTOR_UUID
    factor.tenant_id = uuid.UUID(_TENANT)
    factor.factor_id = "TEST_FACTOR_SVC_001"
    factor.version = "v1"
    factor.gwp_set = "AR6"
    factor.source = "DEFRA"
    factor.scope = 1
    factor.is_published = is_published
    factor.is_tbc = is_tbc
    factor.is_licence_only = is_licence_only
    factor.value = value
    factor.created_by = uuid.UUID(created_by) if created_by else None
    factor.published_at = None
    factor.published_by = None
    factor.biogenic_co2_kg_per_unit = None
    factor.unit = "kgCO2e/unit"
    factor.vintage = "2024"
    factor.valid_from = date(2024, 1, 1)
    factor.valid_to = None
    factor.applicability_note = None
    factor.pdf_source_uri = None
    factor.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    factor.substance = "CO2"
    factor.category = "combustion"
    return factor


def _make_approval(*, proposed_by: str, decision: str = "PENDING") -> MagicMock:
    approval = MagicMock()
    approval.id = _APPROVAL_UUID
    approval.tenant_id = uuid.UUID(_TENANT)
    approval.factor_id = _FACTOR_UUID
    approval.proposed_by = uuid.UUID(proposed_by)
    approval.decision = decision
    approval.approved_by = None
    approval.approved_at = None
    approval.reason_code = "INITIAL_PUBLICATION"
    approval.correlation_id = uuid.UUID(_CORRELATION_ID)
    return approval


def _make_user(sub: str = _ESG1) -> UserContext:
    return UserContext(sub=sub, role="admin", tenant_id=_TENANT)


def _make_body() -> Any:
    """Return a minimal publish request body mock (avoids circular api import)."""
    body = MagicMock()
    body.reason_code = "INITIAL_PUBLICATION"
    return body


def _make_session(
    *,
    factor: MagicMock | None,
    pending_approval: MagicMock | None = None,
    update_rowcount: int = 1,
) -> AsyncMock:
    """Build an AsyncMock session with common execute side-effects.

    Sequence:
      1. FactorCatalogRepository.get_by_uuid -> factor (scalar_one_or_none)
      2. SELECT pending approval -> pending_approval (scalar_one_or_none)
      3. (optional) conditional UPDATE -> rowcount
    """
    session = AsyncMock()
    session.flush = AsyncMock(return_value=None)
    session.add = MagicMock(return_value=None)

    get_by_uuid_result = MagicMock()
    get_by_uuid_result.scalar_one_or_none = MagicMock(return_value=factor)

    pending_result = MagicMock()
    pending_result.scalar_one_or_none = MagicMock(return_value=pending_approval)

    update_result = MagicMock()
    update_result.rowcount = update_rowcount

    session.execute = AsyncMock(
        side_effect=[get_by_uuid_result, pending_result, update_result]
    )

    async def _refresh(obj: Any) -> None:
        if obj is factor and factor is not None and not obj.is_published:
            obj.is_published = True
            obj.published_at = datetime(2026, 5, 14, tzinfo=UTC)
            obj.published_by = _ESG2

    session.refresh = _refresh
    return session


# ---------------------------------------------------------------------------
# _assert_publishable tests
# ---------------------------------------------------------------------------


class TestAssertPublishable:
    """Unit tests for FactorPublishService._assert_publishable (static)."""

    def test_passes_when_value_set_and_not_tbc(self) -> None:
        factor = _make_factor(value=1.23, is_tbc=False, is_licence_only=False)
        # Must not raise.
        FactorPublishService._assert_publishable(factor)

    def test_raises_factor_tbc_error_when_is_tbc_true(self) -> None:
        factor = _make_factor(is_tbc=True, value=None)
        with pytest.raises(FactorTbcError) as exc_info:
            FactorPublishService._assert_publishable(factor)
        assert exc_info.value.factor_id == "TEST_FACTOR_SVC_001"
        assert exc_info.value.version == "v1"

    def test_raises_null_value_error_when_value_none_not_licence_only(self) -> None:
        factor = _make_factor(is_tbc=False, value=None, is_licence_only=False)
        with pytest.raises(FactorNullValueError) as exc_info:
            FactorPublishService._assert_publishable(factor)
        assert exc_info.value.factor_id == "TEST_FACTOR_SVC_001"

    def test_passes_when_value_none_but_is_licence_only(self) -> None:
        factor = _make_factor(is_tbc=False, value=None, is_licence_only=True)
        # licence-only with NULL value is valid — must not raise.
        FactorPublishService._assert_publishable(factor)

    def test_tbc_check_takes_precedence_over_null_value(self) -> None:
        """When both is_tbc=True and value=None, TBC error should be raised first."""
        factor = _make_factor(is_tbc=True, value=None, is_licence_only=False)
        with pytest.raises(FactorTbcError):
            FactorPublishService._assert_publishable(factor)


# ---------------------------------------------------------------------------
# publish() tests — FactorNotFoundError and FactorAlreadyPublishedError
# ---------------------------------------------------------------------------


class TestPublishFactorLookup:
    """publish() raises domain errors for missing/already-published factors."""

    @pytest.mark.asyncio
    async def test_raises_not_found_when_repo_returns_none(self) -> None:
        session = _make_session(factor=None)
        svc = FactorPublishService(session=session)

        with pytest.raises(FactorNotFoundError):
            await svc.publish(
                _FACTOR_UUID,
                _make_body(),
                user=_make_user(),
                correlation_id=_CORRELATION_ID,
            )

    @pytest.mark.asyncio
    async def test_raises_already_published_when_factor_is_published(self) -> None:
        factor = _make_factor(is_published=True, value=1.0)
        session = _make_session(factor=factor)
        svc = FactorPublishService(session=session)

        with pytest.raises(FactorAlreadyPublishedError) as exc_info:
            await svc.publish(
                _FACTOR_UUID,
                _make_body(),
                user=_make_user(),
                correlation_id=_CORRELATION_ID,
            )
        assert exc_info.value.factor_id == "TEST_FACTOR_SVC_001"


# ---------------------------------------------------------------------------
# publish() tests — first call (no pending approval)
# ---------------------------------------------------------------------------


class TestPublishFirstCall:
    """publish() returns PublishResultApprovalRequested on first call."""

    @pytest.mark.asyncio
    async def test_returns_approval_requested_with_approval_id(self) -> None:
        factor = _make_factor(value=1.23)
        session = _make_session(factor=factor, pending_approval=None)
        svc = FactorPublishService(session=session)

        result = await svc.publish(
            _FACTOR_UUID,
            _make_body(),
            user=_make_user(_ESG1),
            correlation_id=_CORRELATION_ID,
        )

        assert isinstance(result, PublishResultApprovalRequested)
        assert result.outcome == "approval_requested"
        assert isinstance(result.approval_id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_session_add_called_for_approval_and_audit(self) -> None:
        factor = _make_factor(value=2.0)
        session = _make_session(factor=factor, pending_approval=None)
        added: list[Any] = []
        session.add = MagicMock(side_effect=lambda obj: added.append(obj))
        svc = FactorPublishService(session=session)

        await svc.publish(
            _FACTOR_UUID,
            _make_body(),
            user=_make_user(_ESG1),
            correlation_id=_CORRELATION_ID,
        )

        # At minimum: the new approval row + audit log row.
        assert len(added) >= 2

    @pytest.mark.asyncio
    async def test_raises_tbc_error_before_creating_approval(self) -> None:
        factor = _make_factor(is_tbc=True, value=None)
        session = _make_session(factor=factor, pending_approval=None)
        svc = FactorPublishService(session=session)

        with pytest.raises(FactorTbcError):
            await svc.publish(
                _FACTOR_UUID,
                _make_body(),
                user=_make_user(_ESG1),
                correlation_id=_CORRELATION_ID,
            )

        # session.add should NOT have been called.
        session.add.assert_not_called()


# ---------------------------------------------------------------------------
# publish() tests — self-approval scenarios
# ---------------------------------------------------------------------------


class TestPublishSelfApproval:
    """Enforces ISAE 3000 two-eyes principle."""

    @pytest.mark.asyncio
    async def test_raises_self_approval_forbidden_same_proposer(self) -> None:
        factor = _make_factor(value=1.0)
        approval = _make_approval(proposed_by=_ESG1)
        session = _make_session(factor=factor, pending_approval=approval)
        svc = FactorPublishService(session=session)

        # Same user (_ESG1) as the proposer.
        with pytest.raises(SelfApprovalForbiddenError):
            await svc.publish(
                _FACTOR_UUID,
                _make_body(),
                user=_make_user(_ESG1),
                correlation_id=_CORRELATION_ID,
            )

    @pytest.mark.asyncio
    async def test_raises_self_approval_creator_when_creator_approves(self) -> None:
        # _CREATOR created the factor AND is now trying to approve.
        factor = _make_factor(value=1.0, created_by=_CREATOR)
        # A different proposer made the pending approval (not the creator).
        approval = _make_approval(proposed_by=_ESG1)
        session = _make_session(factor=factor, pending_approval=approval)
        svc = FactorPublishService(session=session)

        with pytest.raises(SelfApprovalCreatorError):
            await svc.publish(
                _FACTOR_UUID,
                _make_body(),
                # The creator (_CREATOR) is now trying to approve.
                user=_make_user(_CREATOR),
                correlation_id=_CORRELATION_ID,
            )


# ---------------------------------------------------------------------------
# publish() tests — second admin approves (200 path)
# ---------------------------------------------------------------------------


class TestPublishSecondAdmin:
    """Second admin successfully publishes the factor."""

    @pytest.mark.asyncio
    async def test_returns_published_result_on_second_admin_call(self) -> None:
        factor = _make_factor(value=5.0)
        # Approval was proposed by _ESG1; second caller is _ESG2.
        approval = _make_approval(proposed_by=_ESG1)
        session = _make_session(
            factor=factor, pending_approval=approval, update_rowcount=1
        )
        svc = FactorPublishService(session=session)

        # Mock the response model since factor is a MagicMock.
        with patch.object(
            svc,
            "_do_publish",
            wraps=None,
        ):
            # Use the real _do_publish but mock FactorCatalogPublishResponse.model_validate.
            pass

        result = await svc.publish(
            _FACTOR_UUID,
            _make_body(),
            user=_make_user(_ESG2),
            correlation_id=_CORRELATION_ID,
        )

        assert isinstance(result, PublishResultPublished)
        assert result.outcome == "published"

    @pytest.mark.asyncio
    async def test_raises_race_conflict_when_update_rowcount_zero(self) -> None:
        factor = _make_factor(value=3.0)
        approval = _make_approval(proposed_by=_ESG1)
        # rowcount=0 simulates concurrent publisher winning the race.
        session = _make_session(
            factor=factor, pending_approval=approval, update_rowcount=0
        )
        svc = FactorPublishService(session=session)

        with pytest.raises(PublishRaceConflictError):
            await svc.publish(
                _FACTOR_UUID,
                _make_body(),
                user=_make_user(_ESG2),
                correlation_id=_CORRELATION_ID,
            )
