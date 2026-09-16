"""Owner resolution for scopes that are not people.

A partner runs as a synthetic user: it owns a workspace but never an account.
Assets keyed to an account — OAuth credentials above all — must therefore
resolve to the human who owns the partner (#711), while workspace-keyed assets
(rag, skills, notebooks, memory) stay with the partner itself.
"""

from __future__ import annotations

import re
import uuid

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import (
    current_owner_id,
    get_admin_path_service,
    get_current_path_service,
    get_owner_path_service,
)
from deeptutor.services.partners.scope import (
    is_partner_user_id,
    partner_user,
    partner_user_id,
)


def test_is_partner_user_id_separates_synthetic_scopes_from_people() -> None:
    assert is_partner_user_id(partner_user_id("ada"))
    assert not is_partner_user_id("u_alice")


def test_a_person_owns_themselves(mu_isolated_root, as_user) -> None:
    with as_user("u_alice"):
        assert get_owner_path_service().get_user_root() == (
            get_current_path_service().get_user_root()
        )


def test_partner_scope_resolves_to_its_owner(mu_isolated_root) -> None:
    """The partner's own root has no credentials; the owner's does."""
    token = set_current_user(partner_user("ada"))
    try:
        partner_root = get_current_path_service().get_user_root()
        owner_root = get_owner_path_service().get_user_root()
    finally:
        reset_current_user(token)

    assert partner_root == mu_isolated_root / "data" / "partners" / "ada" / "workspace" / "user"
    assert owner_root == get_admin_path_service().get_user_root()
    assert owner_root != partner_root


def test_no_active_scope_falls_back_to_the_current_path_service(mu_isolated_root) -> None:
    assert get_owner_path_service().get_user_root() == (get_current_path_service().get_user_root())


def test_tenant_scope_has_safe_owner_id_without_filesystem_owner_path(
    mu_isolated_root,
) -> None:
    """Per-account system state needs a tenant-safe key, but no local workspace fallback."""

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    def resolve(tenant_id: str) -> str:
        token = set_current_user(
            CurrentUser(
                id="same/user@example.com",
                username="same",
                role="user",
                scope=UserScope(
                    kind="tenant",
                    tenant_id=tenant_id,
                    user_id="same/user@example.com",
                    root=None,
                ),
            )
        )
        try:
            owner_id = current_owner_id()
            with pytest.raises(PermissionError, match="explicit owner provider"):
                get_owner_path_service()
            return owner_id
        finally:
            reset_current_user(token)

    first = resolve(tenant_a)
    assert first == resolve(tenant_a)
    assert first != resolve(tenant_b)
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", first)
