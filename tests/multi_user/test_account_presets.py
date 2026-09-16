# ruff: noqa: F811
# pytest fixture 重导出与注入参数同名。
"""Account preset persistence, expansion, and admin HTTP behavior."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401


@pytest.fixture
def preset_client(pg_dsn, tmp_path):
    from tests.fixtures.default_pg_auth import pg_auth_client

    with pg_auth_client(
        pg_dsn,
        tmp_path / "resources",
        admin="admin",
        learner="seed-learner",
        ordinary="seed-standard",
    ) as client:
        yield client, client.users()["admin"], client.app.state.tokens


def test_legacy_and_new_standard_users_default_to_standard(preset_client):
    client, _, _ = preset_client
    assert client.users()["seed-standard"]["preset"] == "standard"


def test_learning_surface_routing_matches_complete_path_segments():
    from deeptutor.api.routers.auth import _learning_surface_for_path

    assert _learning_surface_for_path("/api/reading/materials") == "reading"
    assert _learning_surface_for_path("/api/courses/course/state") == "reading"
    assert _learning_surface_for_path("/api/question-notebook/entries") == "chat"
    assert _learning_surface_for_path("/api/reading-private") == ""
    assert _learning_surface_for_path("/api/questions") == ""


@pytest.mark.parametrize("preset", ["standard", "custom"])
def test_non_learner_presets_do_not_install_a_learning_grant(preset_client, preset):
    client, _admin, _tokens = preset_client

    response = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": f"{preset}-user",
            "password": "reading-password-1",
            "preset": preset,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["preset"] == preset

    assert client.users()[body["username"]]["learning_policy"] is None


def test_learner_preset_expands_to_a_conservative_grant(preset_client):

    client, _admin, _tokens = preset_client

    response = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "student",
            "password": "reading-password-1",
            "preset": "learner",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "user"
    assert body["preset"] == "learner"

    # PG 账号策略是权威，完整资源 grants 的接线另由领域任务承担。
    assert client.users()[body["username"]]["learning_policy"] == {
        "age_band": "9-12",
        "locked_persona": "teacher",
        "allowed_capabilities": ["chat", "immersive_reading"],
        "default_capability": "immersive_reading",
        "allowed_surfaces": ["chat", "reading"],
        "reading": {
            "allow_upload": False,
            "material_ids": [],
            "extensions": [],
        },
    }


def test_learner_creation_rolls_back_when_grant_initialization_fails(preset_client, monkeypatch):

    client, _admin, _tokens = preset_client

    original = client.identity._audit

    async def fail_account_commit(c, actor, action, target, result):
        if action == "create_user":
            raise RuntimeError("account policy transaction failed")
        return await original(c, actor, action, target, result)

    monkeypatch.setattr(client.identity, "_audit", fail_account_commit)
    response = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "student",
            "password": "reading-password-1",
            "preset": "learner",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Account service unavailable"
    assert "student" not in client.users()


def test_learner_accounts_cannot_disable_the_learning_policy(preset_client):
    client, _admin, _tokens = preset_client
    created = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "student",
            "password": "reading-password-1",
            "preset": "learner",
        },
    ).json()

    response = client.put(
        f"/api/multi-user/users/{created['user_id']}/grants",
        headers={"Authorization": "Bearer admin-token"},
        json={"grant": {"learning_policy": None}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Learner accounts must retain a learning policy."


@pytest.mark.parametrize("preset", ["learner", "custom"])
def test_pocketbase_setting_cannot_replace_pg_preset_authority(preset_client, monkeypatch, preset):
    import deeptutor.services.auth as auth_service

    client, _admin, _tokens = preset_client
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", True)
    response = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "remote-student",
            "password": "reading-password-1",
            "preset": preset,
        },
    )

    assert response.status_code == 201
    assert response.json()["preset"] == preset


def test_auth_status_returns_the_effective_learning_policy(preset_client):
    client, _admin, tokens = preset_client
    created = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "student",
            "password": "reading-password-1",
            "preset": "learner",
        },
    ).json()
    token = client.call("login", "student", "reading-password-1", client="status-test")
    tokens["learner-token"] = token
    response = client.get(
        "/api/auth/status",
        headers={"Authorization": "Bearer learner-token"},
    )

    assert response.status_code == 200
    assert response.json()["preset"] == "learner"
    assert response.json()["learning_policy"]["default_capability"] == ("immersive_reading")


def test_assigning_a_material_copies_the_admin_material_once(
    preset_client, as_user, seed_user, tmp_path
):
    from deeptutor.multi_user.paths import get_path_service_for_scope, scope_for_user
    from deeptutor.reading import ReadingStore

    client, admin, _tokens = preset_client
    learner = seed_user("student")
    source = tmp_path / "lesson.txt"
    source.write_text("Assigned reading passage.", encoding="utf-8")
    with as_user(admin["id"], role="admin", username="admin"):
        material = ReadingStore().ingest(source)

    grant = {
        "enabled_tools": [],
        "mcp_tools": [],
        "cli_apps": [],
        "exec_enabled": False,
        "learning_policy": {
            "age_band": "9-12",
            "locked_persona": "teacher",
            "allowed_capabilities": ["chat", "immersive_reading"],
            "default_capability": "immersive_reading",
            "allowed_surfaces": ["chat", "reading"],
            "reading": {
                "allow_upload": False,
                "material_ids": [material.material_id],
                "extensions": [],
            },
        },
    }
    response = client.put(
        f"/api/multi-user/users/{learner['id']}/grants",
        headers={"Authorization": "Bearer admin-token"},
        json={"grant": grant},
    )

    assert response.status_code == 200, response.text
    user_root = get_path_service_for_scope(
        scope_for_user(learner["id"], is_admin=False)
    ).get_workspace_feature_dir("reading")
    staged = user_root / material.material_id
    assert staged.is_dir()
