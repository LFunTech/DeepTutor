"""接流量前确认明确 hook、初始化状态及不可回退的认证世代。"""

import os
import uuid

from deeptutor_enterprise.bootstrap import Enterprise
from deeptutor_enterprise.configuration import DeploymentConfig
from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn


@pytest.fixture
def deployment(pg_dsn, monkeypatch):
    for name, value in {
        "PREFLIGHT_DB": single_database_user_dsn(pg_dsn),
        "PREFLIGHT_MODEL": "model-only-secret",
        "PREFLIGHT_SIGN": "s" * 48,
        "PREFLIGHT_EPOCH": "epoch-1",
        "PREFLIGHT_BOOT": "b" * 48,
    }.items():
        monkeypatch.setenv(name, value)
    return DeploymentConfig(
        version=1,
        tenant_id=uuid.uuid4(),
        resource="preflight",
        database_secret="env:PREFLIGHT_DB",
        signing_secret="env:PREFLIGHT_SIGN",
        auth_epoch_secret="env:PREFLIGHT_EPOCH",
        bootstrap_secret="env:PREFLIGHT_BOOT",
        origins=("https://school.example",),
        models=(
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "test",
                "base_url": "https://model.example/v1",
                "secret": "env:PREFLIGHT_MODEL",
                "allowed_roles": ("user", "tenant_admin"),
            },
        ),
    )


def test_missing_or_incompatible_hook_fails_before_database(deployment, monkeypatch):
    from deeptutor.core import providers

    monkeypatch.setattr(providers, "APPLICATION_HOOK_VERSION", 0, raising=False)
    with pytest.raises(RuntimeError, match="hook"):
        Enterprise(deployment)


async def test_startup_requires_initialized_tenant_and_matching_epoch(
    pg_dsn, deployment, monkeypatch
):
    await MigrationRunner(os.environ["PREFLIGHT_DB"]).apply()
    enterprise = Enterprise(deployment)
    try:
        with pytest.raises(RuntimeError, match="tenant"):
            await enterprise.start()
    finally:
        await enterprise.close()
    from deeptutor_enterprise.stores.postgres.connection import Database

    enterprise = Enterprise(deployment)
    async with enterprise.db:
        await enterprise.identity.bootstrap("admin", "long-password-1", secret="b" * 48)
    monkeypatch.setenv("PREFLIGHT_EPOCH", "new-external-epoch")
    changed = Enterprise(deployment)
    try:
        with pytest.raises(RuntimeError, match="tenant"):
            await changed.start()
    finally:
        await changed.close()


def test_missing_secret_fails_closed_without_revealing_value(deployment, monkeypatch):
    monkeypatch.delenv("PREFLIGHT_MODEL")
    with pytest.raises(RuntimeError, match="Secret") as error:
        Enterprise(deployment)
    assert "model-only-secret" not in str(error.value)


def test_core_version_mismatch_fails_before_database(deployment, monkeypatch):
    from deeptutor_enterprise import bootstrap

    monkeypatch.setattr(bootstrap, "version", lambda package: "9.0.0")
    with pytest.raises(RuntimeError, match="core version"):
        Enterprise(deployment)


async def test_schema_mismatch_still_blocks_enterprise_composition(pg_dsn, deployment):
    await MigrationRunner(os.environ["PREFLIGHT_DB"]).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute("ALTER TABLE enterprise.sessions DISABLE ROW LEVEL SECURITY")
    enterprise = Enterprise(deployment)
    try:
        with pytest.raises(RuntimeError, match="schema drift"):
            await enterprise.start()
    finally:
        await enterprise.close()


def test_sdk_ambient_headers_rejected_before_application_initialization(deployment, monkeypatch):
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "Authorization: implicit-credential-must-not-leak")
    with pytest.raises(Exception) as error:
        Enterprise(deployment)
    assert "implicit-credential-must-not-leak" not in str(error.value)
