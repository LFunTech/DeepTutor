import importlib.util
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.scope import TenantScope
from deeptutor_enterprise.stores.postgres.connection import Database
from jose import jwt
import pytest


@pytest.fixture
async def identity(pg_dsn):
    assert importlib.util.find_spec("deeptutor_enterprise.identity.service"), "PG 身份服务尚未实现"
    from deeptutor_enterprise.identity.service import IdentityService

    await MigrationRunner(pg_dsn).apply()
    async with Database(
        pg_dsn.replace("user=postgres", "user=dt_enterprise_app"), resource="identity-test"
    ) as db:
        service = IdentityService(
            db,
            tenant_id=str(uuid.uuid4()),
            signing_key="x" * 48,
            auth_epoch="epoch-1",
            bootstrap_secret="b" * 48,
        )
        yield service


async def test_bootstrap_idempotent_no_password_override(identity):
    with pytest.raises(PermissionError):
        await identity.bootstrap("admin", "long-password-1", secret="wrong")
    user = await identity.bootstrap("admin", "long-password-1", secret="b" * 48)
    again = await identity.bootstrap("admin", "different-password-2", secret="b" * 48)
    assert again["id"] == user["id"]
    token = await identity.login("admin", "long-password-1", client="cli")
    admin = await identity.authenticate(token)
    assert admin.role == "tenant_admin"
    with pytest.raises(PermissionError):
        await identity.login("admin", "different-password-2", client="cli")
    with pytest.raises(ValueError):
        await identity.bootstrap("new-admin", "long-password-1", secret="b" * 48)


async def test_revoke_disable_password_and_owner_permissions(identity):
    await identity.bootstrap("admin", "long-password-1", secret="b" * 48)
    admin = await identity.login("admin", "long-password-1", client="cli")
    user = await identity.create_user(admin, "ordinary", "long-password-2")
    original = await identity.login("ordinary", "long-password-2", client="cli")
    await identity.logout(original)
    with pytest.raises(PermissionError):
        await identity.authenticate(original)
    old = await identity.login("ordinary", "long-password-2", client="cli")
    await identity.set_enabled(admin, user["id"], False)
    with pytest.raises(PermissionError):
        await identity.authenticate(old)
    await identity.set_enabled(admin, user["id"], True)
    with pytest.raises(PermissionError):
        await identity.authenticate(old)
    fresh = await identity.login("ordinary", "long-password-2", client="cli")
    with pytest.raises(PermissionError):
        await identity.create_user(fresh, "intruder", "long-password-3")
    await identity.change_password(fresh, user["id"], "long-password-3")
    with pytest.raises(PermissionError):
        await identity.authenticate(fresh)
    with pytest.raises(PermissionError):
        await identity.login("ordinary", "long-password-2", client="cli")
    assert (
        await identity.authenticate(
            await identity.login("ordinary", "long-password-3", client="cli")
        )
    ).user_id == user["id"]


async def test_claim_tampering_and_audit_contains_no_secrets(identity):
    await identity.bootstrap("admin", "long-password-1", secret="b" * 48)
    token = await identity.login("admin", "long-password-1", client="cli")
    claims = jwt.get_unverified_claims(token)
    assert {"tid", "sub", "sid", "ver", "epoch", "iss", "aud", "iat", "exp"} <= claims.keys()
    for key, value in [
        ("tid", str(uuid.uuid4())),
        ("iss", "local"),
        ("aud", "other"),
        ("exp", 1),
        ("ver", 0),
        ("epoch", "old"),
    ]:
        invalid = jwt.encode({**claims, key: value}, "x" * 48, algorithm="HS256")
        with pytest.raises(PermissionError):
            await identity.authenticate(invalid)
    async with identity.db.transaction(TenantScope(identity.tenant_id, "audit")) as c:
        rows = await (await c.execute("SELECT * FROM enterprise.audit")).fetchall()
    assert rows
    assert all(secret not in str(rows) for secret in [token, "long-password-1", "x" * 48, "b" * 48])


async def test_unknown_and_wrong_password_identical_and_limited(identity):
    await identity.bootstrap("admin", "long-password-1", secret="b" * 48)
    messages = []
    for name in ["unknown", "admin"]:
        with pytest.raises(PermissionError) as error:
            await identity.login(name, "wrong", client="one-client")
        messages.append(str(error.value))
    assert messages[0] == messages[1]
    for _ in range(6):
        with pytest.raises(PermissionError):
            await identity.login("unknown", "wrong", client="one-client")
    from deeptutor_enterprise.identity.service import LoginRateLimited

    with pytest.raises(LoginRateLimited):
        await identity.login("admin", "long-password-1", client="one-client")


async def test_repeated_bootstrap_and_conflict_have_persistent_audit(identity):
    await identity.bootstrap("admin", "long-password-1", secret="b" * 48)
    await identity.bootstrap("admin", "different-password-2", secret="b" * 48)
    with pytest.raises(ValueError):
        await identity.bootstrap("someone-else", "different-password-2", secret="b" * 48)
    async with identity.db.transaction(TenantScope(identity.tenant_id, "audit")) as c:
        events = await (
            await c.execute("SELECT action,result FROM enterprise.audit ORDER BY id")
        ).fetchall()
    assert {"action": "bootstrap", "result": "replayed"} in events
    assert {"action": "bootstrap_conflict", "result": "denied"} in events


async def test_identity_denials_and_idempotent_maintenance_have_audit(identity):
    await identity.bootstrap("admin", "long-password-1", secret="b" * 48)
    token = await identity.login("admin", "long-password-1", client="audit")
    user = await identity.create_user(token, "ordinary", "long-password-2")
    await identity.set_enabled(token, user["id"], True)
    with pytest.raises(ValueError):
        await identity.create_user(token, "ordinary", "long-password-2")
    with pytest.raises(PermissionError):
        await identity.authenticate("invalid-token-must-not-be-stored")
    async with identity.db.transaction(TenantScope(identity.tenant_id, "audit")) as c:
        rows = await (
            await c.execute("SELECT action,result,target_id FROM enterprise.audit")
        ).fetchall()
    pairs = {(r["action"], r["result"]) for r in rows}
    assert {("enabled", "replayed"), ("create_user", "denied"), ("authenticate", "denied")} <= pairs
    assert "invalid-token-must-not-be-stored" not in str(rows)
