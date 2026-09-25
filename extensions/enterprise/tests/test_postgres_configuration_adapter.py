import asyncio
import json
import uuid

from deeptutor_enterprise.configuration import DeploymentConfig
import pytest

from deeptutor.persistence.postgres.configuration import PostgresConfigurationError


def deployment(**updates):
    values = {
        "version": 1,
        "tenant_id": uuid.uuid4(),
        "resource": "adapter-test",
        "database_secret": "env:DT_DATABASE_DSN",
        "signing_secret": "env:DT_SIGNING_SECRET",
        "auth_epoch_secret": "env:DT_AUTH_EPOCH_SECRET",
        "bootstrap_secret": "env:DT_BOOTSTRAP_SECRET",
        "origins": ("https://school.example",),
        "models": (
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "test-model",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_MODEL_SECRET",
                "allowed_roles": ("user", "tenant_admin"),
            },
        ),
    }
    values.update(updates)
    return DeploymentConfig(**values)


def test_enterprise_adapter_maps_pool_fields_and_rejects_conflicting_canonical_dsn(monkeypatch):
    from deeptutor_enterprise.configuration import postgres_configuration

    explicit = "postgresql://app:legacy-sentinel@db.example/deeptutor"
    config = deployment(
        max_size=3,
        max_waiting=5,
        timeout=7.5,
        statement_timeout_ms=1234,
        transaction_timeout_ms=5678,
    )
    monkeypatch.setenv("DT_DATABASE_DSN", explicit)
    monkeypatch.setenv("DEEPTUTOR_DATABASE_URL", explicit)

    postgres = postgres_configuration(config)
    assert dict(postgres.connection_kwargs()) == {
        "resource": "adapter-test",
        "max_size": 3,
        "max_waiting": 5,
        "timeout": 7.5,
        "statement_timeout_ms": 1234,
        "transaction_timeout_ms": 5678,
    }
    assert postgres.resolve_runtime().reveal() == explicit

    monkeypatch.setenv(
        "DEEPTUTOR_DATABASE_URL",
        "postgresql://other:canonical-conflict-sentinel@db.example/deeptutor",
    )
    with pytest.raises(PostgresConfigurationError) as error:
        postgres.resolve_runtime()
    assert error.value.code == "postgres_config_conflict"
    assert "sentinel" not in str(error.value)


def test_enterprise_from_file_hides_extra_field_values(tmp_path):
    raw = deployment().model_dump(mode="json")
    raw["unexpected"] = "pydantic-extra-sentinel"
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(raw), encoding="utf8")

    with pytest.raises(PostgresConfigurationError) as error:
        DeploymentConfig.from_file(path)

    assert error.value.code == "postgres_config_invalid"
    assert "pydantic-extra-sentinel" not in str(error.value)
    assert "pydantic-extra-sentinel" not in repr(error.value)


def test_remote_cli_does_not_resolve_local_database_or_identity_secrets(
    tmp_path, monkeypatch, capsys
):
    from deeptutor_enterprise import cli

    path = tmp_path / "deployment.json"
    path.write_text(deployment().model_dump_json(), encoding="utf8")
    monkeypatch.setenv("REMOTE_TOKEN", "remote-token-sentinel")

    async def remote(args, config):
        return {"remote": True, "resource": config.resource}

    monkeypatch.setattr(cli, "_remote_session", remote)
    result = cli.main(
        [
            "--config",
            str(path),
            "session",
            "list",
            "--auth-token-env",
            "REMOTE_TOKEN",
            "--server",
            "https://school.example",
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {"remote": True, "resource": "adapter-test"}


def test_schema_cli_accepts_shared_runtime_dsn_and_rejects_canonical_conflict(
    tmp_path, monkeypatch, capsys
):
    from deeptutor_enterprise import cli

    constructed = []

    class RecordingRunner:
        def __init__(self, dsn):
            constructed.append(dsn)

        async def plan(self):
            return []

    monkeypatch.setattr("deeptutor_enterprise.migrations.runner.MigrationRunner", RecordingRunner)

    path = tmp_path / "deployment.json"
    path.write_text(deployment().model_dump_json(), encoding="utf8")
    monkeypatch.setenv(
        "DEEPTUTOR_DATABASE_URL", "postgresql://app:runtime-sentinel@db.example/deeptutor"
    )

    assert cli.main(["--config", str(path), "schema", "plan", "--dsn-env", "MISSING"]) == 1
    first_error = capsys.readouterr().err
    assert "runtime-sentinel" not in first_error

    monkeypatch.setenv(
        "MIGRATION_OVERRIDE",
        "postgresql://migration:explicit-sentinel@db.example/deeptutor",
    )
    monkeypatch.setenv(
        "DEEPTUTOR_MIGRATION_DATABASE_URL",
        "postgresql://other:canonical-sentinel@db.example/deeptutor",
    )
    assert (
        cli.main(
            [
                "--config",
                str(path),
                "schema",
                "plan",
                "--dsn-env",
                "MIGRATION_OVERRIDE",
            ]
        )
        == 1
    )
    second_error = capsys.readouterr().err
    assert "sentinel" not in second_error
    assert constructed == []

    monkeypatch.delenv("DEEPTUTOR_MIGRATION_DATABASE_URL")
    assert (
        cli.main(
            [
                "--config",
                str(path),
                "schema",
                "plan",
                "--dsn-env",
                "DEEPTUTOR_DATABASE_URL",
            ]
        )
        == 0
    )
    third_output = capsys.readouterr()
    assert "runtime-sentinel" not in third_output.out
    assert "runtime-sentinel" not in third_output.err
    assert constructed == ["postgresql://app:runtime-sentinel@db.example/deeptutor"]


@pytest.mark.asyncio
async def test_bootstrap_secret_is_resolved_only_for_explicit_call_and_never_retained(
    pg_dsn, monkeypatch
):
    from deeptutor_enterprise.bootstrap import Enterprise
    from deeptutor_enterprise.migrations.runner import MigrationRunner

    from deeptutor.persistence.postgres.identity.service import IdentityService

    await MigrationRunner(pg_dsn).apply()
    app_dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    for name, value in {
        "DT_DATABASE_DSN": app_dsn,
        "DEEPTUTOR_DATABASE_URL": app_dsn,
        "DT_SIGNING_SECRET": "s" * 48,
        "DT_AUTH_EPOCH_SECRET": "epoch-1",
        "DT_MODEL_SECRET": "model-secret",
    }.items():
        monkeypatch.setenv(name, value)
    config = deployment()

    enterprise = Enterprise(config)
    assert enterprise.identity._bootstrap is None
    async with enterprise.db:
        with pytest.raises(PostgresConfigurationError) as missing:
            await enterprise.identity.bootstrap("admin", "long-password-1", secret="b" * 48)
    assert missing.value.code == "postgres_bootstrap_secret_missing"
    assert enterprise.identity._bootstrap is None

    monkeypatch.setenv("DT_BOOTSTRAP_SECRET", "b" * 48)
    bootstrap_enterprise = Enterprise(config)
    async with bootstrap_enterprise.db:
        admin = await bootstrap_enterprise.identity.bootstrap(
            "admin", "long-password-1", secret="b" * 48
        )
    assert bootstrap_enterprise.identity._bootstrap is None

    monkeypatch.delenv("DT_BOOTSTRAP_SECRET")
    regular = Enterprise(config)
    async with regular.db:
        token = await regular.identity.login("admin", "long-password-1", client="lazy-secret")
        assert (await regular.identity.authenticate(token)).user_id == admin["id"]
    assert regular.identity._bootstrap is None

    started = asyncio.Event()

    async def cancelled_hash(password):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setenv("DT_BOOTSTRAP_SECRET", "b" * 48)
    monkeypatch.setattr(IdentityService, "_hash", staticmethod(cancelled_hash))
    task = asyncio.create_task(
        regular.identity.bootstrap("admin", "long-password-1", secret="b" * 48)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert regular.identity._bootstrap is None
