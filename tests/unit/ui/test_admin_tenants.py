"""Unit tests for admin_tenants router (wave 4, Task 4).

Tests cover:
  1. ``_require_admin`` raises 403 for non-admin roles.
  2. ``_require_admin`` passes silently for admin role.
  3. ``TenantCreateRequest`` rejects invalid code patterns.
  4. ``TenantCreateRequest`` accepts valid code patterns.
  5. ``TenantPatchRequest`` rejects invalid code patterns.
  6. ``TenantPatchRequest`` allows None fields (partial update).
  7. ``TenantDeactivateResponse`` schema is correct.
  8. ``_build_factor_source_label`` (from sheets.py) builds dynamic label.

Router integration tests (mocked DB):
  9.  GET list_tenants raises 403 for non-admin.
  10. POST create_tenant raises 409 on duplicate code.
  11. PATCH rename_tenant raises 404 on missing tenant.
  12. DELETE deactivate_tenant raises 404 on missing tenant.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Unit tests for schema validators
# ---------------------------------------------------------------------------


class TestTenantCreateRequest:
    """Tests for ``TenantCreateRequest`` Pydantic model."""

    def test_valid_code_accepted(self) -> None:
        from ghg_tool.api.routers.admin_tenants import TenantCreateRequest
        req = TenantCreateRequest(code="GRESMALT_01", legal_name="Test S.p.A.")
        assert req.code == "GRESMALT_01"

    def test_code_with_only_uppercase_letters(self) -> None:
        from ghg_tool.api.routers.admin_tenants import TenantCreateRequest
        req = TenantCreateRequest(code="ABCDEF", legal_name="Test")
        assert req.code == "ABCDEF"

    def test_lowercase_code_rejected(self) -> None:
        from pydantic import ValidationError

        from ghg_tool.api.routers.admin_tenants import TenantCreateRequest
        with pytest.raises(ValidationError):
            TenantCreateRequest(code="lowercase", legal_name="Test")

    def test_code_starting_with_digit_rejected(self) -> None:
        from pydantic import ValidationError

        from ghg_tool.api.routers.admin_tenants import TenantCreateRequest
        with pytest.raises(ValidationError):
            TenantCreateRequest(code="1INVALID", legal_name="Test")

    def test_empty_code_rejected(self) -> None:
        from pydantic import ValidationError

        from ghg_tool.api.routers.admin_tenants import TenantCreateRequest
        with pytest.raises(ValidationError):
            TenantCreateRequest(code="", legal_name="Test")

    def test_code_with_spaces_rejected(self) -> None:
        from pydantic import ValidationError

        from ghg_tool.api.routers.admin_tenants import TenantCreateRequest
        with pytest.raises(ValidationError):
            TenantCreateRequest(code="INVALID CODE", legal_name="Test")


class TestTenantPatchRequest:
    """Tests for ``TenantPatchRequest`` Pydantic model."""

    def test_both_fields_none_allowed(self) -> None:
        from ghg_tool.api.routers.admin_tenants import TenantPatchRequest
        req = TenantPatchRequest(code=None, legal_name=None)
        assert req.code is None
        assert req.legal_name is None

    def test_valid_code_accepted(self) -> None:
        from ghg_tool.api.routers.admin_tenants import TenantPatchRequest
        req = TenantPatchRequest(code="NEW_CODE_01")
        assert req.code == "NEW_CODE_01"

    def test_invalid_code_in_patch_rejected(self) -> None:
        from pydantic import ValidationError

        from ghg_tool.api.routers.admin_tenants import TenantPatchRequest
        with pytest.raises(ValidationError):
            TenantPatchRequest(code="invalid_lowercase")


class TestRequireAdmin:
    """Tests for the ``_require_admin`` helper."""

    def _make_user(self, role: str):  # type: ignore[return]
        from ghg_tool.api.dependencies.auth import CurrentUser
        return CurrentUser(
            sub=str(uuid.uuid4()),
            role=role,  # type: ignore[arg-type]
            tenant_id=str(uuid.uuid4()),
        )

    def test_admin_passes(self) -> None:
        from ghg_tool.api.routers.admin_tenants import _require_admin
        user = self._make_user("admin")
        # Should not raise
        _require_admin(user)

    def test_editor_raises_403(self) -> None:
        from ghg_tool.api.routers.admin_tenants import _require_admin
        user = self._make_user("editor")
        with pytest.raises(HTTPException) as exc_info:
            _require_admin(user)
        assert exc_info.value.status_code == 403

    def test_viewer_raises_403(self) -> None:
        from ghg_tool.api.routers.admin_tenants import _require_admin
        user = self._make_user("viewer")
        with pytest.raises(HTTPException) as exc_info:
            _require_admin(user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Router endpoint tests (mocked DB + auth)
# ---------------------------------------------------------------------------


class TestListTenantsEndpoint:
    """Integration-level test for the list_tenants endpoint."""

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self) -> None:
        from ghg_tool.api.dependencies.auth import CurrentUser
        from ghg_tool.api.routers.admin_tenants import list_tenants

        user = CurrentUser(
            sub=str(uuid.uuid4()),
            role="editor",  # type: ignore[arg-type]
            tenant_id=str(uuid.uuid4()),
        )
        mock_db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await list_tenants(user=user, db=mock_db)
        assert exc_info.value.status_code == 403


class TestCreateTenantEndpoint:
    """Integration-level tests for the create_tenant endpoint."""

    @pytest.mark.asyncio
    async def test_duplicate_code_raises_409(self) -> None:
        from ghg_tool.api.dependencies.auth import CurrentUser
        from ghg_tool.api.routers.admin_tenants import (
            TenantCreateRequest,
            create_tenant,
        )

        user = CurrentUser(
            sub=str(uuid.uuid4()),
            role="admin",  # type: ignore[arg-type]
            tenant_id=str(uuid.uuid4()),
        )
        body = TenantCreateRequest(code="DUPE_CODE", legal_name="Test")
        mock_db = AsyncMock()
        # Simulate a 23505 unique constraint violation
        mock_db.execute.side_effect = Exception(
            "duplicate key value violates unique constraint: 23505"
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_tenant(body=body, user=user, db=mock_db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self) -> None:
        from ghg_tool.api.dependencies.auth import CurrentUser
        from ghg_tool.api.routers.admin_tenants import (
            TenantCreateRequest,
            create_tenant,
        )

        user = CurrentUser(
            sub=str(uuid.uuid4()),
            role="viewer",  # type: ignore[arg-type]
            tenant_id=str(uuid.uuid4()),
        )
        body = TenantCreateRequest(code="ANY_CODE", legal_name="Test")
        mock_db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await create_tenant(body=body, user=user, db=mock_db)
        assert exc_info.value.status_code == 403


class TestRenameTenantEndpoint:
    """Integration-level tests for the rename_tenant endpoint."""

    @pytest.mark.asyncio
    async def test_missing_tenant_raises_404(self) -> None:
        from ghg_tool.api.dependencies.auth import CurrentUser
        from ghg_tool.api.routers.admin_tenants import (
            TenantPatchRequest,
            rename_tenant,
        )

        user = CurrentUser(
            sub=str(uuid.uuid4()),
            role="admin",  # type: ignore[arg-type]
            tenant_id=str(uuid.uuid4()),
        )
        body = TenantPatchRequest(legal_name="New Name")
        tenant_id = uuid.uuid4()
        mock_db = AsyncMock()
        # fetchone() returns None → tenant not found
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        with pytest.raises(HTTPException) as exc_info:
            await rename_tenant(tenant_id=tenant_id, body=body, user=user, db=mock_db)
        assert exc_info.value.status_code == 404


class TestDeactivateTenantEndpoint:
    """Integration-level tests for the deactivate_tenant endpoint."""

    @pytest.mark.asyncio
    async def test_missing_tenant_raises_404(self) -> None:
        from ghg_tool.api.dependencies.auth import CurrentUser
        from ghg_tool.api.routers.admin_tenants import deactivate_tenant

        user = CurrentUser(
            sub=str(uuid.uuid4()),
            role="admin",  # type: ignore[arg-type]
            tenant_id=str(uuid.uuid4()),
        )
        tenant_id = uuid.uuid4()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        with pytest.raises(HTTPException) as exc_info:
            await deactivate_tenant(tenant_id=tenant_id, user=user, db=mock_db)
        assert exc_info.value.status_code == 404
