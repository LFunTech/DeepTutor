"""默认账号能力使用真实 PG，管理员只有账号管理权。"""

import uuid

import psycopg
import pytest

from deeptutor.persistence.postgres.connection import Database
from deeptutor.persistence.postgres.identity.service import IdentityService
from deeptutor.persistence.postgres.migrations.runner import MigrationRunner


@pytest.fixture
async def accounts(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    async with Database(
        pg_dsn.replace("user=postgres", "user=dt_enterprise_app"), resource="accounts"
    ) as db:
        service = IdentityService(
            db,
            tenant_id=str(uuid.uuid4()),
            signing_key="s" * 48,
            auth_epoch="epoch1",
            bootstrap_secret="b" * 48,
        )
        await service.bootstrap("admin", "administrator-123", secret="b" * 48)
        token = await service.login("admin", "administrator-123", client="test")
        yield service, token


async def test_profile_preset_and_management(accounts):
    service, admin = accounts
    learner = await service.create_user(admin, "learner", "learner-password", preset="learner")
    token = await service.login("learner", "learner-password", client="learner")
    info = await service.profile(token)
    assert info["id"] == learner["id"] and info["preset"] == "learner"
    assert info["learning_policy"]["allowed_capabilities"] == ["chat", "immersive_reading"]
    assert info["learning_policy"]["reading"] == {
        "allow_upload": False,
        "material_ids": [],
        "extensions": [],
    }
    assert len(await service.list_users(admin)) == 2
    with pytest.raises(PermissionError):
        await service.list_users(token)
    with pytest.raises(PermissionError):
        await service.profile(token, username="admin")
    await service.update_learner_profile(admin, {"age": 10}, username="learner")
    assert (await service.profile(token))["learner_profile"] == {"schema_version": 1, "age": 10}
    await service.update_learner_profile(token, {"language": "中文"})
    assert (await service.profile(admin, username="learner"))["learner_profile"][
        "language"
    ] == "中文"
    await service.set_role(admin, "learner", "tenant_admin")
    with pytest.raises(PermissionError):
        await service.authenticate(token)
    fresh = await service.login("learner", "learner-password", client="learner")
    assert (await service.authenticate(fresh)).role == "tenant_admin"
    with pytest.raises(ValueError):
        await service.set_role(admin, "admin", "user")


async def test_deleted_account_cannot_be_reenabled_and_name_can_be_reused(accounts):
    service, admin = accounts
    user = await service.create_user(admin, "student", "student-password", preset="learner")
    old = await service.login("student", "student-password", client="student")
    await service.delete_user(admin, "student")
    with pytest.raises(PermissionError):
        await service.authenticate(old)
    with pytest.raises(PermissionError):
        await service.login("student", "student-password", client="student")
    with pytest.raises(LookupError):
        await service.set_enabled(admin, user["id"], True)
    with pytest.raises(LookupError):
        await service.change_password(admin, user["id"], "reset-password-1")
    assert len(await service.list_users(admin)) == 1
    recreated = await service.create_user(admin, "student", "different-password")
    assert recreated["id"] != user["id"]


async def test_device_sessions_rotate_revoke_and_limit(accounts, pg_dsn):
    service, admin = accounts
    user = await service.create_user(admin, "learner", "learner-password", preset="learner")
    device, code, pin = await service.issue_device(admin, user["id"], "Pad", 30, 5)
    assert "pin_hash" not in device and "pairing_code_hash" not in device
    token = await service.device_login(code, pin, client="pad")
    actor = await service.authenticate(token)
    assert actor.user_id == user["id"] and actor.role == "user"
    newer = await service.device_login(code, pin, client="pad")
    with pytest.raises(PermissionError):
        await service.authenticate(token)
    heartbeat = await service.device_heartbeat(newer)
    assert heartbeat["remaining_seconds"] <= 300
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "UPDATE enterprise.device_credentials SET used_seconds=299,last_heartbeat_at=now()-interval '2 seconds'"
        )
    heartbeat = await service.device_heartbeat(newer)
    assert heartbeat["limit_reached"]
    with pytest.raises(PermissionError):
        await service.authenticate(newer)
    await service.revoke_device(admin, device["id"])
    with pytest.raises(PermissionError):
        await service.device_login(code, pin, client="pad")


async def test_device_only_for_active_learner_and_generation_bound(accounts):
    service, admin = accounts
    ordinary = await service.create_user(admin, "ordinary", "ordinary-password")
    with pytest.raises(ValueError):
        await service.issue_device(admin, ordinary["id"], "Pad", 30, 5)
    learner = await service.create_user(admin, "learner", "learner-password", preset="learner")
    _, code, pin = await service.issue_device(admin, learner["id"], "Pad", 30, 5)
    token = await service.device_login(code, pin, client="pad")
    await service.change_password(admin, learner["id"], "new-password-12")
    with pytest.raises(PermissionError):
        await service.authenticate(token)
    with pytest.raises(PermissionError):
        await service.device_login(code, pin, client="pad")


@pytest.mark.parametrize("rotate", [False, True])
async def test_fractional_usage_survives_heartbeat_and_relogin(
    accounts, monkeypatch, pg_dsn, rotate
):
    from datetime import datetime, timedelta

    import deeptutor.persistence.postgres.identity.accounts as module

    service, admin = accounts
    user = await service.create_user(admin, "fractional", "learner-password", preset="learner")
    _, code, pin = await service.issue_device(admin, user["id"], "Pad", 30, 5)
    token = await service.device_login(code, pin, client="fractional")
    start = datetime.fromisoformat((await service.list_devices(admin))[0]["last_heartbeat_at"])

    class Clock(datetime):
        value = start

        @classmethod
        def now(cls, tz=None):
            return cls.value

    monkeypatch.setattr(module, "datetime", Clock)
    Clock.value = start + timedelta(milliseconds=750)
    assert (await service.device_heartbeat(token))["used_seconds"] == 0
    Clock.value = start + timedelta(milliseconds=1500)
    if rotate:
        old = token
        token = await service.device_login(code, pin, client="fractional")
        with pytest.raises(PermissionError):
            await service.authenticate(old)
    second = await service.device_heartbeat(token)
    assert second["used_seconds"] == 1
    with psycopg.connect(pg_dsn) as c:
        assert (
            c.execute("SELECT usage_remainder_us FROM enterprise.device_credentials").fetchone()[0]
            == 500000
        )
        c.execute("UPDATE enterprise.device_credentials SET used_seconds=299")
    Clock.value = start + timedelta(milliseconds=2250)
    assert (await service.device_heartbeat(token))["limit_reached"]
    with pytest.raises(PermissionError):
        await service.authenticate(token)


@pytest.mark.parametrize("rotate", [False, True])
async def test_fractional_usage_resets_at_utc_midnight(accounts, monkeypatch, pg_dsn, rotate):
    from datetime import datetime, timedelta, timezone

    import deeptutor.persistence.postgres.identity.accounts as module

    service, admin = accounts
    user = await service.create_user(admin, "midnight", "learner-password", preset="learner")
    _, code, pin = await service.issue_device(admin, user["id"], "Pad", 30, 5)
    token = await service.device_login(code, pin, client="midnight")
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    with psycopg.connect(pg_dsn) as c:
        c.execute(
            "UPDATE enterprise.device_credentials SET usage_day=%s,used_seconds=299,last_heartbeat_at=%s",
            (midnight.date() - timedelta(days=1), midnight - timedelta(milliseconds=750)),
        )

    class Clock(datetime):
        value = midnight + timedelta(milliseconds=750)

        @classmethod
        def now(cls, tz=None):
            return cls.value

    monkeypatch.setattr(module, "datetime", Clock)
    if rotate:
        token = await service.device_login(code, pin, client="midnight")
    assert (await service.device_heartbeat(token))["used_seconds"] == 0
    Clock.value = midnight + timedelta(milliseconds=1500)
    assert (await service.device_heartbeat(token))["used_seconds"] == 1
