"""显式文件资源与 Codex owner 创建点；只有合成载荷。"""

import uuid

import pytest

from deeptutor.core.providers import ApplicationProviders, provider_context
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.persistence.resources import OwnerResourceProvider


def test_resources_reject_symlinks_and_keep_tenant_owner_separate(tmp_path):
    root = tmp_path / "private"
    resources = OwnerResourceProvider(root)
    assert not root.exists()
    tenant, other = str(uuid.uuid4()), str(uuid.uuid4())
    obj = resources.write_avatar(tenant, "same-id", b"png", "png")
    assert resources.read_avatar(tenant, "same-id", obj) == b"png"
    with pytest.raises(FileNotFoundError):
        resources.read_avatar(other, "same-id", obj)
    with pytest.raises(FileNotFoundError):
        resources.read_avatar(tenant, "other-id", obj)
    evil = tmp_path / "link"
    evil.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        OwnerResourceProvider(evil).write_avatar(tenant, "same-id", b"bad", "png")
    resources.delete_avatar(tenant, "same-id", obj)
    with pytest.raises(FileNotFoundError):
        resources.read_avatar(tenant, "same-id", obj)


def test_codex_roots_resolve_explicit_tenant_owner_without_local_migration(tmp_path):
    from deeptutor.multi_user.personal_models import owner_catalog_service
    from deeptutor.services.codex_auth.service import _codex_secrets_root

    resources = OwnerResourceProvider(tmp_path / "resources")
    paths = []
    for tenant in [str(uuid.uuid4()), str(uuid.uuid4())]:
        scope = UserScope(kind="tenant", tenant_id=tenant, user_id="same", root=None)
        token = set_current_user(
            CurrentUser(id="same", username="same", role="tenant_admin", scope=scope)
        )
        try:
            with provider_context(ApplicationProviders(resources=resources)):
                secret = _codex_secrets_root()
                catalog = owner_catalog_service().path
                assert str(resources.root) in str(secret) and str(resources.root) in str(catalog)
                assert tenant in str(secret) and tenant in str(catalog)
                paths.append(secret)
        finally:
            reset_current_user(token)
    assert paths[0] != paths[1]


def test_global_path_helper_cannot_swallow_missing_identity():
    from deeptutor.services.path_service import get_path_service

    with pytest.raises(PermissionError):
        get_path_service()


@pytest.fixture
def pg_owner(tmp_path, monkeypatch):
    from deeptutor.services.codex_auth import service

    monkeypatch.setattr(service, "load_system_settings", lambda: {"frontend_port": 3000})
    resources = OwnerResourceProvider(tmp_path / "resources")
    tenant = str(uuid.uuid4())
    token = set_current_user(
        CurrentUser(
            id="alice",
            username="alice",
            role="user",
            scope=UserScope(kind="tenant", tenant_id=tenant, user_id="alice", root=None),
        )
    )
    try:
        with provider_context(ApplicationProviders(resources=resources)):
            yield resources, tenant
    finally:
        reset_current_user(token)


def test_pg_owner_catalog_rejects_final_symlink(pg_owner, tmp_path):
    from deeptutor.multi_user.personal_models import owner_catalog_service

    resources, tenant = pg_owner
    root = resources.owner_root(tenant, "alice", "models")
    outside = tmp_path / "outside-catalog.json"
    outside.write_text("{}")
    (root / "model_catalog.json").symlink_to(outside)
    with pytest.raises((PermissionError, OSError)):
        owner_catalog_service().load()
    assert outside.read_text() == "{}"


@pytest.mark.parametrize("level", ["resource", "tenant", "owner", "kind"])
@pytest.mark.parametrize("kind", ["models", "secrets"])
def test_cached_owner_adapters_reject_replaced_ancestors(pg_owner, tmp_path, level, kind):
    from deeptutor.multi_user.personal_models import owner_catalog_service
    from deeptutor.services.codex_auth.contracts import CodexAuthError
    from deeptutor.services.codex_auth.service import get_codex_oauth_service

    resources, tenant = pg_owner
    if kind == "models":
        adapter = owner_catalog_service()
        adapter.save({"marker": "alice"})
        read = adapter.load

        def write():
            return adapter.save({"marker": "overwrite"})
    else:
        adapter = get_codex_oauth_service()._store
        adapter.save_catalog_cache({"marker": "alice"})
        read = adapter.load_catalog_cache

        def write():
            return adapter.save_catalog_cache({"marker": "overwrite"})

    root = resources.owner_root(tenant, "alice", kind)
    victim = {
        "resource": resources.root,
        "tenant": root.parent.parent,
        "owner": root.parent,
        "kind": root,
    }[level]
    moved = tmp_path / "moved"
    victim.rename(moved)
    victim.symlink_to(moved, target_is_directory=True)
    for operation in (read, write):
        with pytest.raises((OSError, PermissionError, CodexAuthError)):
            operation()
    assert "overwrite" not in "".join(p.read_text() for p in moved.rglob("*.json"))


@pytest.mark.parametrize("kind", ["models", "secrets"])
@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_cached_owner_adapters_reject_final_links(pg_owner, tmp_path, kind, link):
    import os

    from deeptutor.multi_user.personal_models import owner_catalog_service
    from deeptutor.services.codex_auth.contracts import CodexAuthError
    from deeptutor.services.codex_auth.service import get_codex_oauth_service

    if kind == "models":
        adapter = owner_catalog_service()
        path = adapter.path
        operations = (adapter.load, lambda: adapter.save({"marker": "bad"}))
    else:
        adapter = get_codex_oauth_service()._store
        adapter.current_generation()
        path = adapter.catalog_cache_path
        operations = (
            adapter.load_catalog_cache,
            lambda: adapter.save_catalog_cache({"marker": "bad"}),
            adapter.clear_catalog_cache,
        )
    outside = tmp_path / "other-owner.json"
    outside.write_text('{"marker":"untouched"}')
    if link == "symlink":
        path.symlink_to(outside)
    else:
        os.link(outside, path)
    for operation in operations:
        with pytest.raises((OSError, PermissionError, CodexAuthError)):
            operation()
    assert outside.read_text() == '{"marker":"untouched"}'


@pytest.mark.parametrize("kind", ["models", "secrets"])
async def test_public_state_callback_keeps_owner_fd_boundary_after_cache(
    pg_owner, tmp_path, monkeypatch, kind
):
    from deeptutor.services.codex_auth import service as module
    from tests.services.codex_auth.test_service import (
        FakeCallback,
        FakeCatalog,
        FakeOAuthClient,
        _snapshot,
    )

    resources, tenant = pg_owner
    service = module.get_codex_oauth_service()
    callback = FakeCallback()

    async def callback_factory(state):
        callback.expected_state = state
        return callback

    service._callback_factory = callback_factory
    service._oauth = FakeOAuthClient()  # 仅替代外部 OAuth 网络，不替代真实 store/catalog。
    service._catalog = FakeCatalog(_snapshot("test"))
    await service.start_login()
    operation = service._operation
    root = resources.owner_root(tenant, "alice", kind)
    moved = tmp_path / "moved-owner"
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
    monkeypatch.setattr(module, "_SERVICE_INSTANCES", {"cached-owner": service})
    # 公开 callback 无 HTTP 身份/资源 context，必须继续用启动时绑定的能力。
    import asyncio
    from contextvars import Context

    async def deliver():
        await module.deliver_codex_oauth_callback("synthetic-code", operation.state_secret, None)

    await asyncio.create_task(deliver(), context=Context())
    await operation.task
    assert operation.operation_state == "failed"
    assert not list(moved.rglob("credentials.v1.json"))
    assert not list(moved.rglob("model_catalog.json"))


def test_owner_codex_generation_atomic_updates_and_concurrency(pg_owner):
    from concurrent.futures import ThreadPoolExecutor

    from deeptutor.services.codex_auth.contracts import CodexAuthError
    from deeptutor.services.codex_auth.service import get_codex_oauth_service
    from tests.services.codex_auth.test_storage import _credentials

    store = get_codex_oauth_service()._store
    first = store.commit_credentials(_credentials("first"), expected_generation=0)

    def commit(token):
        try:
            store.commit_credentials(_credentials(token), expected_generation=first.generation)
            return "committed"
        except CodexAuthError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit, ["one", "two"])) == ["committed", "generation_changed"]
    assert store.current_generation() == 2
    assert store.load_credentials().generation == 2
    store.save_catalog_cache({"models": []})
    assert store.load_catalog_cache() == {"models": []}
    assert store.clear_credentials(expected_generation=2) == 3
    assert store.load_credentials() is None and store.load_catalog_cache() is None
    assert not list(store.root.glob(".*.tmp"))
