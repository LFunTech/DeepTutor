"""账号 schema 的连续历史与先验源目录门禁。"""

import hashlib

import psycopg
import pytest

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner


@pytest.mark.parametrize("source", [1, 2])
async def test_accounts_upgrade_from_verified_schema_one(pg_dsn, source):
    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    assert len(migrations) == 12, "账号后续迁移必须保持 0001–0012 连续历史"
    first = migrations[:source]
    runner._migrations = lambda: first
    await runner.apply()
    before = None
    if source == 2:
        with psycopg.connect(pg_dsn) as c:
            tenant = "00000000-0000-0000-0000-000000000017"
            c.execute(
                "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) VALUES (%s,'not_required','e')",
                (tenant,),
            )
            c.execute(
                "INSERT INTO enterprise.users(tenant_id,id,username,role,preset) VALUES (%s,'learner','learner','user','learner')",
                (tenant,),
            )
            c.execute(
                "INSERT INTO enterprise.device_credentials(tenant_id,user_id,id,device_name,pairing_code_hash,pin_hash,auth_version,auth_epoch,expires_at,daily_limit_minutes,used_seconds,generation) VALUES (%s,'learner','device','Pad','synthetic-code','synthetic-hash',1,'e',now()+interval '1 day',5,127,9)",
                (tenant,),
            )
            before = c.execute(
                "SELECT row_to_json(d) FROM enterprise.device_credentials d"
            ).fetchone()[0]
    runner._migrations = lambda: migrations
    await runner.apply()
    await runner.verify()
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        if before is not None:
            after = c.execute(
                "SELECT row_to_json(d) FROM enterprise.device_credentials d"
            ).fetchone()[0]
            assert after.pop("usage_remainder_us") == 0
            assert after == before
        assert c.execute(
            "SELECT version,checksum FROM enterprise.schema_history ORDER BY version"
        ).fetchall() == [(v, hashlib.sha256(sql.encode()).hexdigest()) for v, sql in migrations]
        assert c.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='enterprise' AND table_name='users' AND column_name='deleted_at'"
        ).fetchone()


@pytest.mark.parametrize("source", [1, 2])
async def test_upgrade_rejects_source_drift_before_new_ddl(pg_dsn, source):
    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    assert len(migrations) == 12, "账号后续迁移必须保持 0001–0012 连续历史"
    runner._migrations = lambda: migrations[:source]
    await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        c.execute("ALTER TABLE enterprise.users DISABLE ROW LEVEL SECURITY")
    runner._migrations = lambda: migrations
    with pytest.raises(RuntimeError, match="RLS"):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone()[0] == source
        assert (
            c.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema='enterprise' AND table_name='device_credentials' AND column_name='usage_remainder_us'"
            ).fetchone()[0]
            == 0
        )
        if source == 1:
            assert (
                c.execute("SELECT to_regclass('enterprise.device_credentials')").fetchone()[0]
                is None
            )


@pytest.mark.parametrize("source", [1, 2])
async def test_target_verification_failure_rolls_back_upgrade(pg_dsn, source):
    runner = MigrationRunner(pg_dsn)
    migrations = runner._migrations()
    runner._migrations = lambda: migrations[:source]
    await runner.apply()
    runner._migrations = lambda: migrations
    original = runner._verify_schema

    async def reject_target(c, version=None):
        if version is None:
            raise RuntimeError("target catalog verification failed")
        return await original(c, version)

    runner._verify_schema = reject_target
    with pytest.raises(RuntimeError, match="target catalog"):
        await runner.apply()
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT count(*) FROM enterprise.schema_history").fetchone()[0] == source
        assert (
            c.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema='enterprise' AND table_name='device_credentials' AND column_name='usage_remainder_us'"
            ).fetchone()[0]
            == 0
        )
        if source == 1:
            assert (
                c.execute("SELECT to_regclass('enterprise.device_credentials')").fetchone()[0]
                is None
            )
