import dataclasses
import json

import pytest

from deeptutor.persistence.postgres.configuration import (
    CANONICAL_DATABASE_SECRET,
    CANONICAL_MIGRATION_DATABASE_SECRET,
    PostgresConfigurationError,
    PostgresDeploymentConfig,
)

TENANT_ID = "62ccf04e-0913-4fef-961e-ffbc6d8e449c"
DATABASE_DSN = "postgresql://runtime-user:runtime-password@db.example:5432/deeptutor"
MIGRATION_DSN = "host=db.example user=migration-user password=migration-password dbname=deeptutor"


def minimal_config(**updates):
    raw = {
        "version": 1,
        "tenant_id": TENANT_ID,
        "resource": "default-runtime",
        "signing_secret": "env:TEST_SIGNING_SECRET",
        "auth_epoch_secret": "env:TEST_AUTH_EPOCH_SECRET",
    }
    raw.update(updates)
    return PostgresDeploymentConfig.from_mapping(raw)


def test_default_configuration_uses_canonical_secret_refs_and_connection_bounds():
    config = minimal_config()

    assert config.database_secret.name == CANONICAL_DATABASE_SECRET
    assert config.migration_database_secret.name == CANONICAL_MIGRATION_DATABASE_SECRET
    assert config.backend_workers == 1
    assert dict(config.connection_kwargs()) == {
        "resource": "default-runtime",
        "max_size": 8,
        "max_waiting": 16,
        "timeout": 10.0,
        "statement_timeout_ms": 15_000,
        "transaction_timeout_ms": 30_000,
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.resource = "changed"


def test_runtime_and_migration_secrets_are_resolved_independently_and_redacted():
    config = minimal_config()
    env = {
        CANONICAL_DATABASE_SECRET: DATABASE_DSN,
        CANONICAL_MIGRATION_DATABASE_SECRET: MIGRATION_DSN,
        "TEST_SIGNING_SECRET": "signing-sentinel-" + "s" * 32,
        "TEST_AUTH_EPOCH_SECRET": "epoch-sentinel",
    }

    runtime = config.resolve_runtime(environ=env)
    migration = config.resolve_migration(environ=env)
    identity = config.resolve_identity(environ=env)

    assert runtime.reveal() == DATABASE_DSN
    assert migration.reveal() == MIGRATION_DSN
    assert identity.signing_key.reveal() == env["TEST_SIGNING_SECRET"]
    assert identity.auth_epoch.reveal() == "epoch-sentinel"
    exposed = (
        repr((config, runtime, migration, identity))
        + json.dumps(config.to_safe_dict())
        + json.dumps(dataclasses.asdict(identity), default=str)
    )
    for sentinel in (
        "runtime-password",
        "migration-password",
        "signing-sentinel",
        "epoch-sentinel",
    ):
        assert sentinel not in exposed


def test_runtime_resolution_does_not_fall_back_to_migration_or_legacy_aliases():
    config = minimal_config()
    for env in (
        {CANONICAL_MIGRATION_DATABASE_SECRET: MIGRATION_DSN},
        {"DT_DATABASE_DSN": DATABASE_DSN},
    ):
        with pytest.raises(PostgresConfigurationError) as error:
            config.resolve_runtime(environ=env)
        assert error.value.code == "postgres_secret_missing"
        assert DATABASE_DSN not in str(error.value)

    with pytest.raises(PostgresConfigurationError) as error:
        config.resolve_migration(environ={CANONICAL_DATABASE_SECRET: DATABASE_DSN})
    assert error.value.code == "postgres_migration_secret_missing"


def test_runtime_accepts_quoted_conninfo_values_containing_uri_delimiter():
    config = minimal_config()
    dsn = (
        "host=db.example user=runtime-user dbname=deeptutor "
        "password='literal://suffix with space' application_name='Deep Tutor'"
    )

    resolved = config.resolve_runtime(environ={CANONICAL_DATABASE_SECRET: dsn})

    assert resolved.reveal() == dsn


def test_migration_resolution_accepts_runtime_dsn_reference_or_value_without_leaking():
    same_reference = minimal_config(
        migration_database_secret="env:DEEPTUTOR_DATABASE_URL",
    )
    env = {CANONICAL_DATABASE_SECRET: DATABASE_DSN}

    assert same_reference.resolve_migration(environ=env).reveal() == DATABASE_DSN

    default_config = minimal_config()
    shared_value = default_config.resolve_migration(
        environ={
            CANONICAL_DATABASE_SECRET: DATABASE_DSN,
            CANONICAL_MIGRATION_DATABASE_SECRET: DATABASE_DSN,
        }
    )
    assert shared_value.reveal() == DATABASE_DSN
    assert DATABASE_DSN not in repr(shared_value)


@pytest.mark.parametrize(
    "dsn",
    [
        "sqlite:///tmp/state.db",
        "pocketbase://pb.example/state",
        "https://db.example/deeptutor",
        "postgresql://db.example/deeptutor",
        "postgresql://runtime-user@db.example",
        "host=db.example dbname=deeptutor",
        "host=db.example user=runtime-user",
        "not a dsn secret-sentinel",
    ],
)
def test_runtime_rejects_non_postgres_or_implicit_database_values_without_leaking(dsn):
    config = minimal_config()
    with pytest.raises(PostgresConfigurationError) as error:
        config.resolve_runtime(environ={CANONICAL_DATABASE_SECRET: dsn})
    assert error.value.code == "postgres_dsn_invalid"
    assert dsn not in str(error.value)
    assert "secret-sentinel" not in repr(error.value)


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"storage_backend": "sqlite"}, "postgres_backend_required"),
        ({"storage_backend": "pocketbase"}, "postgres_backend_required"),
        ({"database_path": "/tmp/legacy-secret.sqlite3"}, "postgres_backend_required"),
        ({"pocketbase_url": "https://pb-secret.example"}, "postgres_backend_required"),
        ({"database_secret": "env:DT_DATABASE_DSN"}, "postgres_config_invalid"),
        ({"signing_secret": "literal-signing-secret"}, "postgres_config_invalid"),
        ({"auth_epoch_secret": "env:../../bad"}, "postgres_config_invalid"),
    ],
)
def test_default_core_rejects_legacy_backend_and_invalid_secret_references(updates, code):
    with pytest.raises(PostgresConfigurationError) as error:
        minimal_config(**updates)
    assert error.value.code == code
    assert not any(str(value) in str(error.value) for value in updates.values())


def test_invalid_or_extra_configuration_never_echoes_input_secrets(tmp_path):
    path = tmp_path / "deployment.json"
    raw = {
        "version": 1,
        "tenant_id": TENANT_ID,
        "resource": "default-runtime",
        "signing_secret": "env:TEST_SIGNING_SECRET",
        "auth_epoch_secret": "env:TEST_AUTH_EPOCH_SECRET",
        "unexpected": "pydantic-extra-secret-sentinel",
    }
    path.write_text(json.dumps(raw), encoding="utf8")

    with pytest.raises(PostgresConfigurationError) as error:
        PostgresDeploymentConfig.from_file(path)

    assert error.value.code == "postgres_config_invalid"
    assert "pydantic-extra-secret-sentinel" not in str(error.value)
    assert "pydantic-extra-secret-sentinel" not in repr(error.value)


def test_configuration_file_is_explicit_and_does_not_discover_dotenv_or_create_state(
    tmp_path, monkeypatch
):
    working = tmp_path / "working"
    working.mkdir()
    (working / ".env").write_text(f"{CANONICAL_DATABASE_SECRET}={DATABASE_DSN}\n", encoding="utf8")
    config_path = tmp_path / "deployment.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "tenant_id": TENANT_ID,
                "resource": "default-runtime",
                "signing_secret": "env:TEST_SIGNING_SECRET",
                "auth_epoch_secret": "env:TEST_AUTH_EPOCH_SECRET",
            }
        ),
        encoding="utf8",
    )
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    monkeypatch.chdir(working)

    config = PostgresDeploymentConfig.from_file(config_path)
    with pytest.raises(PostgresConfigurationError) as error:
        config.resolve_runtime(environ={})

    assert error.value.code == "postgres_secret_missing"
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert after == before


def test_identity_values_match_core_identity_service_bounds_and_bootstrap_is_opt_in():
    config = minimal_config(bootstrap_secret="env:TEST_BOOTSTRAP_SECRET", token_seconds=60)
    environment = {
        "TEST_SIGNING_SECRET": "s" * 32,
        "TEST_AUTH_EPOCH_SECRET": "epoch-1",
    }

    regular = config.resolve_identity(environ=environment)
    assert regular.bootstrap_secret is None

    with pytest.raises(PostgresConfigurationError) as missing:
        config.resolve_identity(environ=environment, include_bootstrap=True)
    assert missing.value.code == "postgres_bootstrap_secret_missing"

    for invalid in (
        {**environment, "TEST_SIGNING_SECRET": "short"},
        {**environment, "TEST_AUTH_EPOCH_SECRET": ""},
    ):
        with pytest.raises(PostgresConfigurationError) as error:
            config.resolve_identity(environ=invalid)
        assert error.value.code == "postgres_identity_secret_invalid"
