from __future__ import annotations

from types import SimpleNamespace

from deeptutor.core.providers import ApplicationProviders, provider_context
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.grants import load_grant, save_grant
from deeptutor.multi_user.models import CurrentUser, UserScope


def _current_user(actor) -> CurrentUser:
    return CurrentUser(
        id=actor.user_id,
        username=actor.username,
        role=actor.role,
        scope=UserScope(
            kind="tenant",
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            root=None,
        ),
    )


def test_grants_round_trip_in_pg_when_application_provider_is_bound(
    business_sync_database, business_actors, tmp_path, monkeypatch
) -> None:
    from deeptutor.multi_user import grants

    tenant = business_actors.tenants[0]
    admin = tenant.admin
    owner = tenant.owners[0]
    monkeypatch.setattr(grants, "GRANTS_DIR", tmp_path / "initial-grants")
    monkeypatch.setattr(
        grants,
        "get_user_by_id",
        lambda user_id: ("owner", {"role": "user"}) if user_id == owner.user_id else None,
    )
    providers = ApplicationProviders(
        container=SimpleNamespace(postgres_runtime=SimpleNamespace(sync_db=business_sync_database))
    )
    token = set_current_user(_current_user(admin))
    try:
        with provider_context(providers):
            saved = save_grant(owner.user_id, {"enabled_tools": ["reason"]})
    finally:
        reset_current_user(token)

    assert saved["enabled_tools"] == ["reason"]

    # Simulate local data deletion/recreation: the PG row, not GRANTS_DIR, is
    # the authority once a PG provider is bound.
    monkeypatch.setattr(grants, "GRANTS_DIR", tmp_path / "after-delete-grants")
    token = set_current_user(_current_user(admin))
    try:
        with provider_context(providers):
            loaded = load_grant(owner.user_id)
    finally:
        reset_current_user(token)

    assert loaded["enabled_tools"] == ["reason"]


def test_multi_user_assignment_target_resolves_pg_identity(
    business_sync_database, business_actors, tmp_path, monkeypatch
) -> None:
    from deeptutor.api.routers import multi_user
    from deeptutor.multi_user import grants

    tenant = business_actors.tenants[0]
    admin = tenant.admin
    owner = tenant.owners[0]
    monkeypatch.setattr(grants, "GRANTS_DIR", tmp_path / "missing-local-grants")
    providers = ApplicationProviders(
        container=SimpleNamespace(postgres_runtime=SimpleNamespace(sync_db=business_sync_database))
    )
    token = set_current_user(_current_user(admin))
    try:
        with provider_context(providers):
            username, record = multi_user._require_assignable_user(owner.user_id)
    finally:
        reset_current_user(token)

    assert username == owner.username
    assert record["id"] == owner.user_id
    assert record["role"] == "user"
