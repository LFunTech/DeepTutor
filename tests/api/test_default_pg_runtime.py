# ruff: noqa: F811
"""默认 Web/API runtime 的 PG-only 装配契约。"""

from __future__ import annotations

import json
from pathlib import Path
import uuid

from fastapi import FastAPI
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401


def _reset_runtime_singletons(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(home))
    for name in (
        "DEEPTUTOR_POSTGRES_CONFIG",
        "DEEPTUTOR_DATABASE_URL",
        "DEEPTUTOR_MIGRATION_DATABASE_URL",
        "TEST_SIGNING_SECRET",
        "TEST_AUTH_EPOCH_SECRET",
        "TEST_BOOTSTRAP_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    from deeptutor.app.container import set_application_container
    from deeptutor.runtime.launcher import _reset_runtime_singletons as reset_runtime_paths

    set_application_container(None)
    reset_runtime_paths()


def _write_postgres_config(path: Path, tenant_id: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "tenant_id": tenant_id,
                "resource": "default-web-api",
                "signing_secret": "env:TEST_SIGNING_SECRET",
                "auth_epoch_secret": "env:TEST_AUTH_EPOCH_SECRET",
                "bootstrap_secret": "env:TEST_BOOTSTRAP_SECRET",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_default_pg_config_path_is_outside_deletable_data_directory(tmp_path: Path) -> None:
    """删除 runtime `data/` 不应连 PG 部署配置位置一起删除。"""

    from deeptutor.app.postgres_runtime import default_postgres_config_path

    home = tmp_path / "home"
    path = default_postgres_config_path(environ={}, home=home)

    assert path == home / "config" / "postgres.json"
    assert "data" not in path.relative_to(home).parts


def test_default_pg_config_can_survive_runtime_data_deletion(tmp_path: Path) -> None:
    """默认 PG 配置在 runtime home/config 下时，清空 data 后仍可加载。"""

    from deeptutor.app.postgres_runtime import load_default_postgres_config

    home = tmp_path / "home"
    tenant_id = str(uuid.uuid4())
    _write_postgres_config(home / "config" / "postgres.json", tenant_id)
    data = home / "data"
    (data / "user" / "settings").mkdir(parents=True)
    (data / "user" / "settings" / "ephemeral.json").write_text("{}", encoding="utf-8")

    import shutil

    shutil.rmtree(data)
    config = load_default_postgres_config(environ={}, home=home)

    assert str(config.tenant_id) == tenant_id


def _patch_lifespan_side_effect_sentinels(monkeypatch: pytest.MonkeyPatch, side_effects: list[str]):
    from deeptutor.api import main
    from deeptutor.app.container import ApplicationContainer

    async def legacy_migration_must_not_run(self):  # pragma: no cover - RED 失败路径标记
        side_effects.append("legacy_migration")
        raise AssertionError("startup legacy migration ran before PostgreSQL preflight")

    def llm_must_not_start():  # pragma: no cover - RED 失败路径标记
        side_effects.append("llm")
        raise AssertionError("LLM initialized before PostgreSQL preflight")

    class BackgroundMustNotStart:  # pragma: no cover - RED 失败路径标记
        def __init__(self, *args, **kwargs):
            side_effects.append("background")
            raise AssertionError("background services started before PostgreSQL preflight")

    monkeypatch.setattr(main, "validate_tool_consistency", lambda: None)
    monkeypatch.setattr(
        ApplicationContainer,
        "run_startup_data_migrations",
        legacy_migration_must_not_run,
    )
    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", llm_must_not_start)
    monkeypatch.setattr(
        "deeptutor.runtime.background_leader.BackgroundLeaderSupervisor",
        BackgroundMustNotStart,
    )
    return main


@pytest.mark.asyncio
async def test_lifespan_refuses_missing_pg_config_before_legacy_or_background_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺默认 PG 配置应先失败；若改回启动旧迁移/模型/后台，本测试会失败。"""

    _reset_runtime_singletons(monkeypatch, tmp_path / "home")

    from deeptutor.api import main
    from deeptutor.persistence.postgres.configuration import PostgresConfigurationError

    side_effects: list[str] = []
    _patch_lifespan_side_effect_sentinels(monkeypatch, side_effects)

    app = FastAPI(lifespan=main.lifespan)
    with pytest.raises(PostgresConfigurationError) as error:
        async with app.router.lifespan_context(app):
            raise AssertionError("lifespan must not become ready without PostgreSQL")

    assert error.value.code == "postgres_config_missing"
    assert side_effects == []
    assert getattr(app.state, "ready", False) is False


@pytest.mark.asyncio
async def test_lifespan_refuses_executor_conflict_before_model_or_background(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已有真实执行者时默认服务拒绝启动，且不会先启动模型/后台。"""

    _reset_runtime_singletons(monkeypatch, tmp_path / "home")
    tenant_id = str(uuid.uuid4())
    config = _write_postgres_config(tmp_path / "postgres.json", tenant_id)
    runtime_dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    monkeypatch.setenv("DEEPTUTOR_POSTGRES_CONFIG", str(config))
    monkeypatch.setenv("DEEPTUTOR_DATABASE_URL", runtime_dsn)
    monkeypatch.setenv("TEST_SIGNING_SECRET", "s" * 48)
    monkeypatch.setenv("TEST_AUTH_EPOCH_SECRET", "epoch-default-runtime")
    monkeypatch.setenv("TEST_BOOTSTRAP_SECRET", "b" * 48)

    from deeptutor.persistence.postgres.connection import Database
    from deeptutor.persistence.postgres.executor import ExecutorLease
    from deeptutor.persistence.postgres.identity.service import IdentityService
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

    await MigrationRunner(pg_dsn).apply()
    async with Database(runtime_dsn, resource="bootstrap-default-runtime") as db:
        identity = IdentityService(
            db,
            tenant_id=tenant_id,
            signing_key="s" * 48,
            auth_epoch="epoch-default-runtime",
            bootstrap_secret="b" * 48,
        )
        await identity.bootstrap("admin", "administrator-123", secret="b" * 48)

    side_effects: list[str] = []
    main = _patch_lifespan_side_effect_sentinels(monkeypatch, side_effects)
    competing = ExecutorLease(runtime_dsn, resource="default-web-api")
    await competing.acquire()
    try:
        app = FastAPI(lifespan=main.lifespan)
        with pytest.raises(RuntimeError, match="another executor"):
            async with app.router.lifespan_context(app):
                raise AssertionError("lifespan must not become ready with an executor conflict")
        assert side_effects == []
        assert getattr(app.state, "ready", False) is False
    finally:
        await competing.close()


@pytest.mark.asyncio
async def test_default_container_assembles_real_pg_store_auth_and_domain_providers(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认容器必须使用真实 PG 权威，并保留完整 capability 目录而非 chat-only。"""

    _reset_runtime_singletons(monkeypatch, tmp_path / "home")
    tenant_id = str(uuid.uuid4())
    config = _write_postgres_config(tmp_path / "postgres.json", tenant_id)
    runtime_dsn = pg_dsn.replace("user=postgres", "user=dt_enterprise_app")
    monkeypatch.setenv("DEEPTUTOR_POSTGRES_CONFIG", str(config))
    monkeypatch.setenv("DEEPTUTOR_DATABASE_URL", runtime_dsn)
    monkeypatch.setenv("TEST_SIGNING_SECRET", "s" * 48)
    monkeypatch.setenv("TEST_AUTH_EPOCH_SECRET", "epoch-default-runtime")
    monkeypatch.setenv("TEST_BOOTSTRAP_SECRET", "b" * 48)

    from deeptutor.persistence.postgres.connection import Database
    from deeptutor.persistence.postgres.identity.service import IdentityService
    from deeptutor.persistence.postgres.learning import AsyncLearningStore
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.postgres.session import PostgresSessionStore

    await MigrationRunner(pg_dsn).apply()
    async with Database(runtime_dsn, resource="bootstrap-default-runtime") as db:
        identity = IdentityService(
            db,
            tenant_id=tenant_id,
            signing_key="s" * 48,
            auth_epoch="epoch-default-runtime",
            bootstrap_secret="b" * 48,
        )
        await identity.bootstrap("admin", "administrator-123", secret="b" * 48)

    from deeptutor.app.container import ApplicationContainer
    from deeptutor.learning.runtime import LearningRuntime
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )

    container = ApplicationContainer.build()
    capability_names = {m["name"] for m in container.capability_registry.get_manifests()}
    assert {"chat", "mastery_path", "immersive_reading", "course_study"} <= capability_names

    await container.start()
    token_context = None
    try:
        assert container.auth_provider is not None
        token = await container.auth_provider.identity.login(
            "admin", "administrator-123", client="default-container-test"
        )
        token_context = set_current_user(user_from_token_payload(await container.auth_provider.decode(token)))

        store = container.store_provider.get()
        assert isinstance(store, PostgresSessionStore)
        assert store.scope.tenant_id == tenant_id
        assert store.scope.user_id
        assert (await store.create_session(title="default pg"))["title"] == "default pg"

        learning = container.learning_provider.get()
        assert isinstance(learning, LearningRuntime)
        assert isinstance(learning._store, AsyncLearningStore)

        reading = container.reading_provider.get()
        assert isinstance(reading, AsyncReadingCatalogStore)
    finally:
        if token_context is not None:
            reset_current_user(token_context)
        await container.close()


def test_default_container_build_exports_runtime_objectstore_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """若默认容器没有暴露 runtime ObjectStore provider，附件路由会回落本地资源。"""

    from copy import deepcopy
    from types import SimpleNamespace

    from deeptutor.app import container as container_module
    from deeptutor.app.postgres_runtime import DefaultPostgresRuntime
    from deeptutor.services.config.runtime_settings import (
        DEFAULT_AUTH_SETTINGS,
        DEFAULT_INTEGRATIONS_SETTINGS,
        DEFAULT_SYSTEM_SETTINGS,
    )

    object_store = object()
    fake_runtime = SimpleNamespace(
        store_provider=object(),
        auth_provider=object(),
        learning_provider=object(),
        reading_provider=object(),
        resources=None,
        object_store=object_store,
    )

    monkeypatch.setattr(
        container_module,
        "load_auth_settings",
        lambda: {**DEFAULT_AUTH_SETTINGS, "cookie_secure": False},
    )
    monkeypatch.setattr(container_module, "load_system_settings", lambda: deepcopy(DEFAULT_SYSTEM_SETTINGS))
    monkeypatch.setattr(
        container_module,
        "load_integrations_settings",
        lambda: deepcopy(DEFAULT_INTEGRATIONS_SETTINGS),
    )
    monkeypatch.setattr(
        DefaultPostgresRuntime,
        "from_environment",
        classmethod(lambda cls, **kwargs: fake_runtime),
    )

    container = container_module.ApplicationContainer.build()

    assert container.object_store_provider is object_store
    assert container.providers.object_store is object_store
