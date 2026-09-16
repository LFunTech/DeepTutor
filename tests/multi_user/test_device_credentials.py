# ruff: noqa: F811
# pytest fixture 重导出与注入参数同名。
"""原设备凭证场景改用同一 PG 身份/session，非 MarginNote device。"""

from datetime import datetime, timedelta, timezone
import json

import psycopg
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401


def _auth(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def device_client(pg_dsn, tmp_path):
    from tests.fixtures.default_pg_auth import pg_auth_client

    with pg_auth_client(
        pg_dsn, tmp_path / "resources", admin="root", learner="learner", ordinary="ordinary"
    ) as client:
        yield client


def issue(client, **kwargs):
    body = {
        "user_id": client.users()["learner"]["id"],
        "device_name": "Learner tablet",
        "expires_in_days": 30,
        "daily_limit_minutes": 5,
        **kwargs,
    }
    response = client.post("/api/auth/devices", headers=_auth("admin-token"), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def login(client, device, pin=None):
    client.cookies.clear()
    response = client.post(
        "/api/auth/device-login",
        json={"pairing_code": device["pairing_code"], "pin": pin or device["pin"]},
    )
    return response, client.cookies.get("dt_token")


def test_admin_issue_lists_and_secrets_are_not_persisted(device_client, pg_dsn):
    client = device_client
    created = issue(client)
    assert created["pairing_code"].startswith("dc_")
    assert len(created["pin"]) == 6 and created["pin"].isdigit()
    listed = client.get("/api/auth/devices", headers=_auth("admin-token")).json()["devices"]
    assert listed[0]["username"] == "learner" and listed[0]["daily_limit_minutes"] == 5
    assert "pin_hash" not in listed[0] and "pairing_code_hash" not in listed[0]
    with psycopg.connect(pg_dsn) as c:
        data = c.execute("SELECT row_to_json(d) FROM enterprise.device_credentials d").fetchall()
        audit = c.execute("SELECT row_to_json(a) FROM enterprise.audit a").fetchall()
    assert created["pairing_code"] not in json.dumps(data + audit, default=str)
    assert created["pin"] not in json.dumps(data + audit, default=str)


def test_only_admins_can_issue_device_credentials(device_client):
    client = device_client
    body = {
        "user_id": client.users()["learner"]["id"],
        "device_name": "Pad",
        "expires_in_days": 30,
        "daily_limit_minutes": 5,
    }
    assert (
        client.post("/api/auth/devices", headers=_auth("user-token"), json=body).status_code == 403
    )
    assert client.post("/api/auth/devices", json=body).status_code == 401
    body["user_id"] = client.users()["root"]["id"]
    assert (
        client.post("/api/auth/devices", headers=_auth("admin-token"), json=body).status_code == 400
    )
    body["user_id"] = client.users()["ordinary"]["id"]
    assert (
        client.post("/api/auth/devices", headers=_auth("admin-token"), json=body).status_code == 400
    )


def test_only_admins_can_list_and_revoke_device_credentials(device_client):
    client = device_client
    device = issue(client)["device"]
    assert client.get("/api/auth/devices", headers=_auth("user-token")).status_code == 403
    assert (
        client.delete("/api/auth/devices/" + device["id"], headers=_auth("user-token")).status_code
        == 403
    )
    assert client.delete("/api/auth/devices/" + device["id"]).status_code == 401


def test_device_login_returns_normal_identity_and_revocation_invalidates_token(device_client):
    client = device_client
    device = issue(client)
    response, token = login(client, device)
    assert response.json()["role"] == "user" and response.json()["ok"]
    assert not response.json()["is_admin"]
    assert response.json()["device_credential_id"] == device["device"]["id"]
    assert client.get("/api/auth/profile", headers=_auth(token)).json()["username"] == "learner"
    assert (
        client.delete(
            "/api/auth/devices/" + device["device"]["id"], headers=_auth("admin-token")
        ).status_code
        == 200
    )
    assert client.get("/api/auth/profile", headers=_auth(token)).status_code == 401
    assert login(client, device)[0].status_code == 401


def test_relogin_rotates_the_lease_and_charges_elapsed_usage(device_client, pg_dsn):
    client = device_client
    device = issue(client)
    _, old = login(client, device)
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "UPDATE enterprise.device_credentials SET last_heartbeat_at=now()-interval '60 seconds'"
        )
    response, new = login(client, device)
    assert response.status_code == 200 and old != new
    assert client.get("/api/auth/profile", headers=_auth(old)).status_code == 401
    heartbeat = client.post("/api/auth/device/heartbeat", headers=_auth(new)).json()
    assert heartbeat["used_seconds"] >= 60 and heartbeat["remaining_seconds"] <= 240


def test_pin_failures_are_rate_limited(device_client, pg_dsn):
    client = device_client
    device = issue(client)
    wrong = "111111" if device["pin"] != "111111" else "222222"
    for _ in range(5):
        assert login(client, device, wrong)[0].status_code == 401
    assert login(client, device)[0].status_code == 401
    with psycopg.connect(pg_dsn) as c:
        row = c.execute(
            "SELECT failed_pin_attempts,pin_locked_until FROM enterprise.device_credentials"
        ).fetchone()
        assert row[0] >= 5 and row[1] > datetime.now(timezone.utc)
        c.execute(
            "UPDATE enterprise.device_credentials SET pin_locked_until=now()-interval '1 second'"
        )
    assert login(client, device)[0].status_code == 200


def test_expired_and_deleted_accounts_fail_closed(device_client, pg_dsn):
    client = device_client
    expired = issue(client)
    with psycopg.connect(pg_dsn) as c:
        c.execute("UPDATE enterprise.device_credentials SET expires_at=now()-interval '1 second'")
    assert login(client, expired)[0].status_code == 401
    device = issue(client)
    _, token = login(client, device)
    assert client.delete("/api/auth/users/learner", headers=_auth("admin-token")).status_code == 200
    assert client.get("/api/auth/profile", headers=_auth(token)).status_code == 401
    assert login(client, device)[0].status_code == 401


def test_disabled_account_fails_closed(device_client):
    client = device_client
    device = issue(client)
    _, token = login(client, device)
    uid = client.users()["learner"]["id"]
    client.call("set_enabled", client.app.state.tokens["admin-token"], uid, False)
    assert client.get("/api/auth/profile", headers=_auth(token)).status_code == 401
    assert login(client, device)[0].status_code == 401
    client.call("set_enabled", client.app.state.tokens["admin-token"], uid, True)
    assert login(client, device)[0].status_code == 401  # 世代变化不可恢复旧设备授权。


def test_heartbeat_enforces_freshness_daily_limit_and_day_rollover(device_client, pg_dsn):
    client = device_client
    device = issue(client)
    _, token = login(client, device)
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "UPDATE enterprise.device_credentials SET usage_day=current_date-1,used_seconds=300,last_heartbeat_at=now()-interval '2 seconds'"
        )
    response = client.post("/api/auth/device/heartbeat", headers=_auth(token))
    assert response.status_code == 200 and response.json()["ok"]
    assert response.json()["used_seconds"] < 300
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "UPDATE enterprise.device_credentials SET used_seconds=299,last_heartbeat_at=now()-interval '2 seconds'"
        )
    response = client.post("/api/auth/device/heartbeat", headers=_auth(token))
    assert response.status_code == 200 and not response.json()["ok"]
    assert response.json()["remaining_seconds"] == 0
    assert client.get("/api/auth/profile", headers=_auth(token)).status_code == 401


def test_stale_heartbeat_cannot_access_authenticated_api(device_client, pg_dsn):
    client = device_client
    device = issue(client)
    _, token = login(client, device)
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "UPDATE enterprise.device_credentials SET last_heartbeat_at=now()-interval '301 seconds'"
        )
    assert client.get("/api/auth/profile", headers=_auth(token)).status_code == 401
    assert client.post("/api/auth/device/heartbeat", headers=_auth(token)).status_code == 401


def test_pocketbase_setting_cannot_replace_pg_device_identity(device_client, monkeypatch):
    from deeptutor.services import auth

    monkeypatch.setattr(auth, "POCKETBASE_ENABLED", True)
    client = device_client
    device = issue(client)
    assert login(client, device)[0].status_code == 200
    assert client.identity.tenant_id


def test_subsecond_heartbeats_and_rotation_cannot_erase_api_usage(device_client, monkeypatch):
    import deeptutor.persistence.postgres.identity.accounts as module

    client = device_client
    device = issue(client)
    _, token = login(client, device)
    start = datetime.fromisoformat(
        client.call("list_devices", client.app.state.tokens["admin-token"])[0]["last_heartbeat_at"]
    )

    class Clock(datetime):
        value = start

        @classmethod
        def now(cls, tz=None):
            return cls.value

    monkeypatch.setattr(module, "datetime", Clock)
    Clock.value = start + timedelta(milliseconds=750)
    first = client.post("/api/auth/device/heartbeat", headers=_auth(token))
    assert first.status_code == 200 and first.json()["used_seconds"] == 0
    Clock.value = start + timedelta(milliseconds=1500)
    _, rotated = login(client, device)
    assert client.get("/api/auth/profile", headers=_auth(token)).status_code == 401
    result = client.post("/api/auth/device/heartbeat", headers=_auth(rotated))
    assert result.status_code == 200 and result.json()["used_seconds"] == 1
    assert result.json()["remaining_seconds"] == 299
