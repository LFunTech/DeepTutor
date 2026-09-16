# ruff: noqa: F811
# pytest fixture 重导出与注入参数同名。
"""#481 的 async ContextVar 回归：PG tenant+owner，不再接受空身份 admin。"""

import inspect
import uuid

from fastapi import Depends
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401


def test_require_auth_is_async_def():
    from deeptutor.api.routers.auth import require_admin, require_auth

    assert inspect.iscoroutinefunction(require_auth)
    assert inspect.iscoroutinefunction(require_admin)


def test_install_current_user_rejects_none_instead_of_local_admin():
    from deeptutor.api.routers.auth import _install_current_user

    with pytest.raises(PermissionError):
        _install_current_user(None)


@pytest.mark.parametrize("role", ["user", "tenant_admin"])
def test_install_current_user_maps_payload_to_scoped_user(role):
    from deeptutor.api.routers.auth import _install_current_user
    from deeptutor.multi_user.context import get_current_user, reset_current_user
    from deeptutor.services.auth import TokenPayload

    tenant = str(uuid.uuid4())
    token = _install_current_user(
        TokenPayload(username="alice", role=role, user_id="alice", tenant_id=tenant)
    )
    try:
        user = get_current_user()
        assert user.id == "alice" and user.role == role
        assert user.scope.kind == "tenant" and user.scope.tenant_id == tenant
        assert user.scope.root is None
        assert user.can_manage_accounts == (role == "tenant_admin")
        assert not user.is_admin  # 旧全局资源管理员权不由 tenant_admin 获得。
    finally:
        reset_current_user(token)


def test_local_admin_token_payload_is_not_a_runtime_auth_factory():
    from deeptutor.api.routers import auth

    assert not hasattr(auth, "_local_admin_token_payload")


@pytest.fixture
def context_client(pg_dsn, tmp_path):
    from deeptutor.api.routers.auth import require_auth
    from deeptutor.multi_user.context import get_current_user
    from tests.fixtures.default_pg_auth import pg_auth_client

    with pg_auth_client(pg_dsn, tmp_path / "resources") as client:

        @client.app.get("/whoami")
        async def whoami(_=Depends(require_auth)):
            user = get_current_user()
            return {
                "seen": user.username,
                "role": user.role,
                "scope_kind": user.scope.kind,
                "root": user.scope.root,
            }

        yield client


def test_require_auth_propagates_user_contextvar_to_endpoint(context_client):
    response = context_client.get("/whoami", headers={"Authorization": "Bearer user-token"})
    assert response.status_code == 200
    assert response.json() == {"seen": "bob", "role": "user", "scope_kind": "tenant", "root": None}


def test_require_auth_propagates_admin_contextvar_to_endpoint(context_client):
    response = context_client.get("/whoami", headers={"Authorization": "Bearer admin-token"})
    assert response.status_code == 200
    assert response.json() == {
        "seen": "alice",
        "role": "tenant_admin",
        "scope_kind": "tenant",
        "root": None,
    }


def test_path_service_requires_explicit_pg_resource_provider_through_dependency(context_client):
    from deeptutor.api.routers.auth import require_auth
    from deeptutor.services.path_service import get_path_service

    @context_client.app.get("/db-path")
    async def db_path(_=Depends(require_auth)):
        with pytest.raises(RuntimeError, match="local path service is unavailable"):
            get_path_service()
        return {"no_shared_path": True}

    assert context_client.get(
        "/db-path", headers={"Authorization": "Bearer admin-token"}
    ).json() == {"no_shared_path": True}
