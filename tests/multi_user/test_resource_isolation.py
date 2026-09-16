from __future__ import annotations

from pathlib import Path

import pytest

from tests.services.session.pg_helpers import pg_session_runtime


@pytest.mark.asyncio
async def test_book_paths_and_pg_session_scopes_are_per_authenticated_owner(
    as_user, pg_dsn: str
) -> None:
    from deeptutor.book.storage import BookStorage

    shared_book_id = "shared-book-id"

    async with pg_session_runtime(pg_dsn, resource="multi-user-resource-isolation") as runtime:
        victim = await runtime.create_user("victim")
        attacker = await runtime.create_user("attacker")

        with as_user(victim.user_id):
            victim_book_root = BookStorage().book_root(shared_book_id)
            victim_session_scope = runtime.store(victim).store_scope

        with as_user(attacker.user_id):
            attacker_book_root = BookStorage().book_root(shared_book_id)
            attacker_session_scope = runtime.store(attacker).store_scope

    assert victim_book_root != attacker_book_root
    assert victim_session_scope != attacker_session_scope
    assert victim_session_scope.backend == "postgres"
    assert attacker_session_scope.backend == "postgres"
    assert victim_session_scope.tenant_id == attacker_session_scope.tenant_id
    assert victim_session_scope.owner_id != attacker_session_scope.owner_id
    assert victim.user_id in str(victim_book_root)
    assert attacker.user_id in str(attacker_book_root)


def test_partner_data_is_admin_anchored_not_user_scoped(as_user) -> None:
    """Partners are process-wide resources anchored at the admin workspace.

    Unlike the per-user resources above, the partner tree must NOT follow the
    request user's scope: partner runtimes execute inside a synthetic partner
    scope whose own workspace lives below ``data/partners``, so resolving the
    base dir through the contextvar would recurse the layout. Access control
    is enforced at the API layer instead.
    """
    from deeptutor.services.partners.manager import PartnerManager

    manager = PartnerManager()

    with as_user("u_victim"):
        victim_dir = manager._partners_dir
    with as_user("u_attacker"):
        attacker_dir = manager._partners_dir

    assert victim_dir == attacker_dir
    assert Path(victim_dir).as_posix().endswith("data/partners")
    assert "u_victim" not in str(victim_dir)
