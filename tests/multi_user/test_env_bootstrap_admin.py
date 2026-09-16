# ruff: noqa: F811
# pytest fixture 重导出与注入参数同名。
"""旧 env 首管理员成功路径的 PG 切换反向回归。

旧测试的 env overlay / first visitor promotion 已明确取消；这些名称保留为
参数 ID，验证相同入口不能再从 AUTH_ENABLED/用户名/hash 创建或提权主体。
"""

import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401

LEGACY_SCENARIOS = [
    "first_created_account_is_not_promoted_when_env_admin_exists",
    "admin_can_still_create_an_explicit_admin_when_env_admin_exists",
    "env_admin_still_resolves_after_first_account_is_created",
    "env_admin_can_log_in_after_first_account_is_created",
    "env_admin_is_never_written_into_the_user_store",
    "stored_record_wins_over_env_bootstrap_admin",
    "adopting_the_bootstrap_username_keeps_admin_role",
    "env_admin_appears_exactly_once_in_the_admin_user_list",
    "is_first_user_is_false_when_only_the_env_admin_exists",
    "first_account_is_promoted_when_no_env_admin_exists",
    "second_account_is_not_promoted_when_no_env_admin_exists",
    "partial_env_credentials_do_not_count_as_an_admin",
    "is_first_user_is_true_for_a_genuinely_empty_deployment",
]


@pytest.mark.parametrize("legacy_scenario", LEGACY_SCENARIOS)
def test_legacy_env_is_not_runtime_identity_authority(
    pg_dsn, tmp_path, monkeypatch, legacy_scenario
):
    from tests.fixtures.default_pg_auth import pg_auth_client

    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_USERNAME", "operator")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", "old-env-hash")
    # 不读取旧 data；这里只证明默认 router 不调用旧身份权威。
    from deeptutor.multi_user import identity as legacy

    def forbidden(*args, **kwargs):
        raise AssertionError("默认 PG auth 不得读取旧身份: " + legacy_scenario)

    monkeypatch.setattr(legacy, "load_users", forbidden)
    monkeypatch.setattr(legacy, "get_user_by_id", forbidden)
    with pg_auth_client(pg_dsn, tmp_path / "resources") as client:
        assert client.get("/api/auth/status").json()["authenticated"] is False
        assert client.get("/api/auth/users").status_code == 401
        assert client.get("/api/auth/is_first_user").json() == {"is_first_user": False}
        assert (
            client.post(
                "/api/auth/register", json={"username": "operator", "password": "operator-password"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/login", json={"username": "operator", "password": "operator-password"}
            ).status_code
            == 401
        )
        listed = client.get(
            "/api/auth/users", headers={"Authorization": "Bearer admin-token"}
        ).json()
        assert len(listed) == 3
        assert [u["username"] for u in listed if u["role"] == "tenant_admin"] == ["alice"]


def test_admin_create_user_returns_role_user(pg_dsn, tmp_path):
    from tests.fixtures.default_pg_auth import pg_auth_client

    with pg_auth_client(pg_dsn, tmp_path / "resources") as client:
        response = client.post(
            "/api/auth/users",
            headers={"Authorization": "Bearer admin-token"},
            json={"username": "student", "password": "student-password"},
        )
        assert response.status_code == 201
        assert response.json()["role"] == "user" and not response.json()["is_admin"]


def test_bootstrap_admin_remains_listed_after_creating_an_account(pg_dsn, tmp_path):
    from tests.fixtures.default_pg_auth import pg_auth_client

    with pg_auth_client(pg_dsn, tmp_path / "resources") as client:
        old = client.users()["alice"]["id"]
        result = client.call("bootstrap", "alice", "different-password", secret="b" * 48)
        assert result["id"] == old
        assert (
            client.post(
                "/api/auth/login", json={"username": "alice", "password": "administrator-123"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/auth/login", json={"username": "alice", "password": "different-password"}
            ).status_code
            == 401
        )
        assert client.users()["alice"]["id"] == old


def test_bootstrap_admin_username_cannot_be_taken_by_a_new_account(pg_dsn, tmp_path):
    from tests.fixtures.default_pg_auth import pg_auth_client

    with pg_auth_client(pg_dsn, tmp_path / "resources") as client:
        response = client.post(
            "/api/auth/users",
            headers={"Authorization": "Bearer admin-token"},
            json={"username": "alice", "password": "attacker-password"},
        )
        assert response.status_code == 409
        with pytest.raises(ValueError):
            client.call("bootstrap", "another-admin", "attacker-password", secret="b" * 48)
