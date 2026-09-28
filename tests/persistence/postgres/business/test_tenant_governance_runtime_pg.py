"""租户生命周期和 turn command 的真实 PG 去 CHECK 负例。"""

from __future__ import annotations

import psycopg
import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("constraint", "field", "unknown"),
    [
        (
            "tenants_external_eligibility_check",
            "external_eligibility",
            "future-eligibility",
        ),
        (
            "tenants_provisioning_status_check",
            "provisioning_status",
            "future-provisioning",
        ),
        ("tenants_recovery_state_check", "recovery_state", "future-recovery"),
    ],
)
async def test_existing_session_rejects_unknown_tenant_values_without_db_checks(
    business_actors,
    migrated_pg,
    constraint,
    field,
    unknown,
):
    actor = business_actors.tenants[0].admin
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
        await c.execute(f"ALTER TABLE enterprise.tenants DROP CONSTRAINT IF EXISTS {constraint}")
        await c.execute(
            f"UPDATE enterprise.tenants SET {field}=%s WHERE id=%s",
            (unknown, actor.tenant_id),
        )

    with pytest.raises(PermissionError, match="authentication required"):
        await business_actors.tenants[0].identity_service.authenticate(actor.token)


async def test_finish_command_rejects_unknown_kind_without_db_check(
    pg_session_store_factory,
    business_actors,
    migrated_pg,
):
    actor = business_actors.tenants[0].admin
    store = pg_session_store_factory(actor)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
        await c.execute(
            "ALTER TABLE enterprise.turn_commands DROP CONSTRAINT IF EXISTS turn_commands_kind_check"
        )
        await c.execute(
            "INSERT INTO enterprise.sessions(tenant_id,owner_id,id,title) "
            "VALUES(%s,%s,'command-session','Command session')",
            (actor.tenant_id, actor.user_id),
        )
        await c.execute(
            "INSERT INTO enterprise.turns"
            "(tenant_id,user_id,session_id,id,capability,status,owner_id,state_version) "
            "VALUES(%s,%s,'command-session','command-turn','chat','waiting_input',%s,7)",
            (actor.tenant_id, actor.user_id, actor.user_id),
        )
        await c.execute(
            "INSERT INTO enterprise.turn_commands"
            "(tenant_id,owner_id,session_id,turn_id,command_id,kind,fingerprint,accepted,state_version) "
            "VALUES(%s,%s,'command-session','command-turn','command','future-command','fp',true,7)",
            (actor.tenant_id, actor.user_id),
        )

    with pytest.raises(ValueError, match="Unknown command kind"):
        await store.finish_command("command-turn", "command", False)
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
        row = await (
            await c.execute(
                "SELECT accepted FROM enterprise.turn_commands "
                "WHERE tenant_id=%s AND owner_id=%s AND turn_id='command-turn' AND command_id='command'",
                (actor.tenant_id, actor.user_id),
            )
        ).fetchone()
    assert row[0] is True
