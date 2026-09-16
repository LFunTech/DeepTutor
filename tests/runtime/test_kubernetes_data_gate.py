from __future__ import annotations

import json
from pathlib import Path
import uuid

import pytest


def _write_postgres_config(path: Path, tenant_id: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "tenant_id": tenant_id,
                "resource": "kubernetes-runtime-test",
                "signing_secret": "env:TEST_SIGNING_SECRET",
                "auth_epoch_secret": "env:TEST_AUTH_EPOCH_SECRET",
                "bootstrap_secret": "env:TEST_BOOTSTRAP_SECRET",
            }
        ),
        encoding="utf-8",
    )
    return path


def _runtime_env(config: Path, *, mode: str | None = None) -> dict[str, str]:
    env = {
        "DEEPTUTOR_POSTGRES_CONFIG": str(config),
        "DEEPTUTOR_DATABASE_URL": "postgresql://runtime-user:runtime-password@db.example:5432/deeptutor",
        "TEST_SIGNING_SECRET": "s" * 48,
        "TEST_AUTH_EPOCH_SECRET": "epoch-kubernetes-runtime-test",
        "TEST_BOOTSTRAP_SECRET": "b" * 48,
    }
    if mode is not None:
        env["DEEPTUTOR_RUNTIME_MODE"] = mode
    return env


def test_data_gate_blocks_forbidden_local_authority_and_unknown_data_paths(tmp_path: Path) -> None:
    """若 production gate 忘记检查本地权威或未知 data 写入，本测试应失败。"""

    from deeptutor.runtime.data_gate import (
        DataUseCategory,
        DataUseDeclaration,
        RuntimeDataGate,
        RuntimeMode,
    )

    data_root = tmp_path / "data"
    mode = RuntimeMode.from_environ({"DEEPTUTOR_RUNTIME_MODE": "kubernetes"})
    gate = RuntimeDataGate(
        data_root,
        declarations=(
            DataUseDeclaration(
                name="owner_resources",
                relative_path="postgres-resources",
                category=DataUseCategory.FORBIDDEN_AUTHORITY,
                owner_boundary="tenant/owner",
                entrypoints=("DefaultPostgresRuntime",),
            ),
            DataUseDeclaration(
                name="turn_scratch",
                relative_path="user/.runtime",
                category=DataUseCategory.SCRATCH,
                owner_boundary="process",
                entrypoints=("TurnRuntimeManager",),
            ),
        ),
        mode=mode,
    )

    report = gate.evaluate(
        active_authorities={"owner_resources": "local"},
        observed_paths=(data_root / "unexpected" / "state.json",),
    )

    assert report.ready is False
    assert {finding.code for finding in report.blockers} == {
        "data_forbidden_authority",
        "data_unknown_path",
    }
    assert "runtime-password" not in report.safe_summary()


def test_default_data_inventory_covers_required_paths_and_boundaries() -> None:
    """若 A1 inventory 漏掉关键 data 路径、类别或入口边界，本测试应失败。"""

    from deeptutor.runtime.data_gate import (
        DataUseCategory,
        default_data_use_inventory,
    )

    inventory = {item.name: item for item in default_data_use_inventory()}
    expected = {
        "settings": DataUseCategory.FORBIDDEN_AUTHORITY,
        "system": DataUseCategory.FORBIDDEN_AUTHORITY,
        "system_user_secrets": DataUseCategory.FORBIDDEN_AUTHORITY,
        "owner_resources": DataUseCategory.FORBIDDEN_AUTHORITY,
        "workspace": DataUseCategory.FORBIDDEN_AUTHORITY,
        "skills": DataUseCategory.FORBIDDEN_AUTHORITY,
        "personas": DataUseCategory.FORBIDDEN_AUTHORITY,
        "notebooks": DataUseCategory.FORBIDDEN_AUTHORITY,
        "knowledge_bases": DataUseCategory.FORBIDDEN_AUTHORITY,
        "memory": DataUseCategory.FORBIDDEN_AUTHORITY,
        "partners": DataUseCategory.FORBIDDEN_AUTHORITY,
        "runtime_state": DataUseCategory.SCRATCH,
        "logs": DataUseCategory.CACHE,
        "parse_cache": DataUseCategory.CACHE,
        "offline_import_input": DataUseCategory.OFFLINE_IMPORT_INPUT,
    }

    assert {name: inventory[name].category for name in expected} == expected
    assert inventory["skills"].normalized_path().as_posix() == "user/workspace/skills"
    assert inventory["personas"].normalized_path().as_posix() == "user/workspace/personas"
    for name in expected:
        item = inventory[name]
        assert item.owner_boundary
        assert item.entrypoints
        assert not item.normalized_path().is_absolute()


def test_data_gate_allows_declared_scratch_in_local_development(tmp_path: Path) -> None:
    """若 local-dev 被 production data 约束误拒，本测试应失败。"""

    from deeptutor.runtime.data_gate import (
        DataUseCategory,
        DataUseDeclaration,
        RuntimeDataGate,
        RuntimeMode,
    )

    data_root = tmp_path / "data"
    gate = RuntimeDataGate(
        data_root,
        declarations=(
            DataUseDeclaration(
                name="turn_scratch",
                relative_path="user/.runtime",
                category=DataUseCategory.SCRATCH,
                owner_boundary="process",
                entrypoints=("TurnRuntimeManager",),
            ),
        ),
        mode=RuntimeMode.from_environ({}),
    )

    report = gate.evaluate(observed_paths=(data_root / "user" / ".runtime" / "turn.json",))

    assert report.ready is True
    assert report.blockers == ()


def test_default_postgres_runtime_refuses_local_owner_resources_in_kubernetes_mode(
    tmp_path: Path,
) -> None:
    """若默认 PG runtime 在 K8s mode 仍装配本地 OwnerResourceProvider，本测试应失败。"""

    from deeptutor.app.postgres_runtime import DefaultPostgresRuntime
    from deeptutor.persistence.postgres.configuration import PostgresConfigurationError

    config = _write_postgres_config(tmp_path / "postgres.json", str(uuid.uuid4()))

    with pytest.raises(PostgresConfigurationError) as error:
        DefaultPostgresRuntime.from_environment(
            environ=_runtime_env(config, mode="kubernetes"),
            home=tmp_path / "home",
        )

    assert error.value.code == "production_data_provider_required"
    assert "runtime-password" not in str(error.value)


def test_default_postgres_runtime_keeps_local_owner_resources_for_local_development(
    tmp_path: Path,
) -> None:
    """若 production gate 破坏本地 PG-only 开发模式，本测试应失败。"""

    from deeptutor.app.postgres_runtime import DefaultPostgresRuntime
    from deeptutor.persistence.resources import OwnerResourceProvider

    config = _write_postgres_config(tmp_path / "postgres.json", str(uuid.uuid4()))

    runtime = DefaultPostgresRuntime.from_environment(
        environ=_runtime_env(config),
        home=tmp_path / "home",
    )

    assert isinstance(runtime.resources, OwnerResourceProvider)
    assert runtime.resource_root == (tmp_path / "home" / "data" / "postgres-resources").resolve()


def test_default_postgres_runtime_uses_s3_objectstore_in_kubernetes_mode(
    tmp_path: Path,
) -> None:
    """若 K8s mode 配好 S3-compatible provider 仍装配本地 owner resource，本测试会失败。"""

    from deeptutor.app.postgres_runtime import DefaultPostgresRuntime
    from deeptutor.runtime.externalized_providers import S3CompatibleObjectStore

    config = _write_postgres_config(tmp_path / "postgres.json", str(uuid.uuid4()))
    env = _runtime_env(config, mode="kubernetes")
    env.update(
        {
            "DEEPTUTOR_OBJECTSTORE_ENDPOINT": "https://objects.example.test",
            "DEEPTUTOR_OBJECTSTORE_REGION": "us-test-1",
            "DEEPTUTOR_OBJECTSTORE_BUCKET": "deeptutor-runtime",
            "DEEPTUTOR_OBJECTSTORE_ACCESS_KEY_REF": "env:TEST_S3_ACCESS_KEY",
            "DEEPTUTOR_OBJECTSTORE_SECRET_KEY_REF": "env:TEST_S3_SECRET_KEY",
            "TEST_S3_ACCESS_KEY": "access-value-must-not-be-read-during-construction",
            "TEST_S3_SECRET_KEY": "secret-value-must-not-be-read-during-construction",
        }
    )

    runtime = DefaultPostgresRuntime.from_environment(
        environ=env,
        home=tmp_path / "home",
    )

    assert isinstance(runtime.object_store, S3CompatibleObjectStore)
    assert runtime.resources is None
    assert not (tmp_path / "home" / "data" / "postgres-resources").exists()
    safe_config = repr(runtime.object_store.config)
    assert "secret-value-must-not-be-read-during-construction" not in safe_config
    assert "access-value-must-not-be-read-during-construction" not in safe_config


@pytest.mark.asyncio
async def test_default_postgres_runtime_start_requires_objectstore_secret_before_pg_connection(
    tmp_path: Path,
) -> None:
    """若 ObjectStore Secret 缺失时仍继续连 PG 或输出明文，本测试会失败。"""

    from deeptutor.app.postgres_runtime import DefaultPostgresRuntime
    from deeptutor.persistence.postgres.configuration import PostgresConfigurationError

    config = _write_postgres_config(tmp_path / "postgres.json", str(uuid.uuid4()))
    env = _runtime_env(config, mode="kubernetes")
    env.update(
        {
            "DEEPTUTOR_OBJECTSTORE_ENDPOINT": "https://objects.example.test",
            "DEEPTUTOR_OBJECTSTORE_REGION": "us-test-1",
            "DEEPTUTOR_OBJECTSTORE_BUCKET": "deeptutor-runtime",
            "DEEPTUTOR_OBJECTSTORE_ACCESS_KEY_REF": "env:TEST_S3_ACCESS_KEY",
            "DEEPTUTOR_OBJECTSTORE_SECRET_KEY_REF": "env:TEST_S3_SECRET_KEY",
        }
    )

    runtime = DefaultPostgresRuntime.from_environment(
        environ=env,
        home=tmp_path / "home",
    )

    with pytest.raises(PostgresConfigurationError) as error:
        await runtime.start()

    assert error.value.code == "production_data_provider_required"
    assert "runtime-password" not in str(error.value)
    assert "TEST_S3_SECRET_KEY" not in str(error.value)


def test_path_service_refuses_forbidden_data_bootstrap_in_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """若 production startup 仍创建本地 settings/workspace 权威目录，本测试应失败。"""

    monkeypatch.setenv("DEEPTUTOR_RUNTIME_MODE", "production")

    from deeptutor.runtime.data_gate import DataGateError
    from deeptutor.services.path_service import PathService

    service = PathService(workspace_root=tmp_path / "data")

    with pytest.raises(DataGateError) as error:
        service.ensure_all_directories()

    assert "data_forbidden_authority" in str(error.value)
    assert not service.get_settings_dir().exists()
    assert not service.get_workspace_dir().exists()
