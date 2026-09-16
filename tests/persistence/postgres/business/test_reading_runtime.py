"""1.19: reading API/runtime must consume the PG reading catalog, not _catalog.sqlite3."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytestmark = pytest.mark.asyncio


def _reading_root(resource_root, actor):
    return (
        resource_root
        / str(uuid.UUID(actor.tenant_id))
        / hashlib.sha256(actor.user_id.encode()).hexdigest()
        / "reading"
    )


def _app():
    from deeptutor.api.routers import reading

    app = FastAPI()
    app.include_router(reading.router, prefix="/api/reading")
    return app


async def test_material_unit_route_uses_pg_content_mapping_without_sqlite_catalog(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: ReadingStore falls back to alias/_catalog.sqlite3 instead of PG content_id."""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    from deeptutor.reading import ReadingStore
    import deeptutor.reading.store as reading_store_module
    from deeptutor.services.path_service import PathService

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(business_actors.tenants[0].owners[0].identity))
    try:
        actor = business_actors.tenants[0].owners[0]
        content_id = "a" * 16
        material_id = "rm_bbbbbbbbbbbb"
        resource_root = tmp_path / "resources"
        reading_root = (
            resource_root
            / str(uuid.UUID(actor.tenant_id))
            / hashlib.sha256(actor.user_id.encode()).hexdigest()
            / "reading"
        )
        ReadingStore(reading_root).ingest_units(
            content_id,
            filename="pg-source.md",
            title="PG source",
            units=["This unit is addressed through the PG catalog alias."],
            mime="text/markdown",
        )
        catalog = AsyncReadingCatalogStore(
            business_sync_database,
            pg_scope_factory(actor),
        )
        await catalog.run(
            lambda u: u.upsert_material(
                content_id=content_id,
                material_id=material_id,
                filename="alias.md",
                title="Alias title",
                source_kind="file",
                mime="text/markdown",
                status="ready",
            )
        )

        def forbid_sqlite_catalog(*_args, **_kwargs):
            raise AssertionError("reading API must not read _catalog.sqlite3")

        monkeypatch.setattr(reading_store_module.sqlite3, "connect", forbid_sqlite_catalog)

        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                resources=OwnerResourceProvider(resource_root),
            )
        ):
            response = TestClient(_app()).get(
                f"/api/reading/materials/{material_id}/units/1"
            )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "locator": 1,
            "unit": "section",
            "text": "This unit is addressed through the PG catalog alias.",
        }
    finally:
        reset_current_user(token)
        PathService.reset_instance()


async def test_workspace_routes_persist_tabs_in_pg_without_sqlite_catalog(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: workspace create/read/delete uses legacy ReadingCatalogStore."""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    import deeptutor.reading.catalog_store as legacy_catalog_module
    from deeptutor.services.path_service import PathService

    actor = business_actors.tenants[0].owners[0]
    catalog = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    material_id = "rm_cccccccccccc"
    await catalog.run(
        lambda u: u.upsert_material(
            content_id="c" * 16,
            material_id=material_id,
            filename="workspace.md",
            title="Workspace material",
            source_kind="file",
            mime="text/markdown",
            status="ready",
        )
    )

    def forbid_sqlite_catalog(*_args, **_kwargs):
        raise AssertionError("workspace API must not open _catalog.sqlite3")

    monkeypatch.setattr(legacy_catalog_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                resources=OwnerResourceProvider(tmp_path / "resources"),
            )
        ):
            client = TestClient(_app())
            created = client.post(
                "/api/reading/workspaces",
                json={"title": "PG workspace", "material_ids": [material_id]},
            )
            assert created.status_code == 201, created.text
            workspace = created.json()["workspace"]
            workspace_id = workspace["workspace_id"]
            assert workspace["active_material_id"] == material_id
            assert [tab["material"]["material_id"] for tab in workspace["tabs"]] == [material_id]

            fetched = client.get(f"/api/reading/workspaces/{workspace_id}")
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["workspace"]["title"] == "PG workspace"

            removed = client.delete(
                f"/api/reading/workspaces/{workspace_id}/materials/{material_id}"
            )
            assert removed.status_code == 200, removed.text
            assert removed.json()["workspace"]["tabs"] == []

            deleted = client.delete(f"/api/reading/workspaces/{workspace_id}")
            assert deleted.status_code == 200, deleted.text
            assert await catalog.run(lambda u: u.get_workspace(workspace_id)) is None
    finally:
        reset_current_user(token)
        PathService.reset_instance()


async def test_material_list_routes_project_pg_alias_and_payload_facts(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: material listing scans filesystem/SQLite instead of PG rows."""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    from deeptutor.reading import ReadingStore
    import deeptutor.reading.catalog_store as legacy_catalog_module
    import deeptutor.reading.store as reading_store_module
    from deeptutor.services.path_service import PathService

    actor = business_actors.tenants[0].owners[0]
    content_id = "d" * 16
    material_id = "rm_dddddddddddd"
    resource_root = tmp_path / "resources"
    reading_root = (
        resource_root
        / str(uuid.UUID(actor.tenant_id))
        / hashlib.sha256(actor.user_id.encode()).hexdigest()
        / "reading"
    )
    manifest = ReadingStore(reading_root).ingest_units(
        content_id,
        filename="payload.md",
        title="Payload title",
        units=["Payload body"],
        mime="text/markdown",
    )
    catalog = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    await catalog.run(
        lambda u: u.upsert_material(
            content_id=content_id,
            material_id=material_id,
            filename="alias-payload.md",
            title="Alias payload",
            source_kind="file",
            mime="text/markdown",
            status="ready",
        )
    )

    def forbid_sqlite_catalog(*_args, **_kwargs):
        raise AssertionError("reading material list must not open _catalog.sqlite3")

    monkeypatch.setattr(legacy_catalog_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setattr(reading_store_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                resources=OwnerResourceProvider(resource_root),
            )
        ):
            client = TestClient(_app())
            materials = client.get("/api/reading/materials")
            assert materials.status_code == 200, materials.text
            body = materials.json()
            assert [row["material_id"] for row in body] == [material_id]
            assert body[0]["title"] == "Alias payload"
            assert body[0]["unit_count"] == manifest.unit_count

            library = client.get("/api/reading/library/materials")
            assert library.status_code == 200, library.text
            row = library.json()["materials"][0]
            assert row["material_id"] == material_id
            assert row["title"] == "Alias payload"
            assert row["size_bytes"] == manifest.byte_size
            assert row["unit_count"] == manifest.unit_count
            assert library.json()["counts"]["all"] == 1

            duplicate = client.post(
                "/api/reading/library/duplicate-check",
                json={
                    "files": [
                        {
                            "filename": "alias-payload.md",
                            "content_id": content_id,
                            "size_bytes": manifest.byte_size,
                            "mime": "text/markdown",
                        }
                    ],
                    "urls": [],
                },
            )
            assert duplicate.status_code == 200, duplicate.text
            assert duplicate.json()["matches"][0]["material"]["material_id"] == material_id

            deleted = client.delete(f"/api/reading/materials/{material_id}")
            assert deleted.status_code == 200, deleted.text
            assert deleted.json()["material_id"] == material_id
            assert await catalog.run(lambda u: u.get_material(material_id)) is None
    finally:
        reset_current_user(token)
        PathService.reset_instance()


async def test_reading_session_routes_use_pg_workspace_catalog(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    pg_session_store_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: reading session routes attach to legacy catalog instead of PG."""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    import deeptutor.reading.catalog_store as legacy_catalog_module
    from deeptutor.services.path_service import PathService

    actor = business_actors.tenants[0].owners[0]
    catalog = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    session_store = pg_session_store_factory(actor)
    material_id = "rm_eeeeeeeeeeee"
    workspace_id = "reading-session-workspace"
    await catalog.run(
        lambda u: (
            u.upsert_material(
                content_id="e" * 16,
                material_id=material_id,
                filename="session.md",
                title="Session material",
                source_kind="file",
                mime="text/markdown",
                status="ready",
            ),
            u.create_workspace("Session workspace", [material_id], workspace_id=workspace_id),
        )
    )

    def forbid_sqlite_catalog(*_args, **_kwargs):
        raise AssertionError("reading session API must not open _catalog.sqlite3")

    monkeypatch.setattr(legacy_catalog_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                store=SimpleNamespace(get=lambda: session_store),
                resources=OwnerResourceProvider(tmp_path / "resources"),
            )
        ):
            client = TestClient(_app())
            created = client.post(
                f"/api/reading/workspaces/{workspace_id}/sessions",
                json={"title": "Read with tutor", "active_material_id": material_id},
            )
            assert created.status_code == 201, created.text
            session = created.json()["session"]
            session_id = session["session_id"]
            assert session["workspace_id"] == workspace_id
            assert session["active_material_id"] == material_id

            listed = client.get(f"/api/reading/workspaces/{workspace_id}/sessions")
            assert listed.status_code == 200, listed.text
            assert listed.json()["sessions"][0]["session_id"] == session_id

            renamed = client.patch(
                f"/api/reading/workspaces/{workspace_id}/sessions/{session_id}",
                json={"title": "Renamed reading"},
            )
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["session"]["title"] == "Renamed reading"

            deleted = client.delete(
                f"/api/reading/workspaces/{workspace_id}/sessions/{session_id}"
            )
            assert deleted.status_code == 200, deleted.text
            assert await catalog.run(lambda u: u.list_sessions(workspace_id)) == []
    finally:
        reset_current_user(token)
        PathService.reset_instance()


async def test_reading_tools_use_pg_catalog_and_resource_payloads(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: reading tools construct legacy stores/catalogs."""

    from deeptutor.capabilities.reading.tools import (
        BINDING_KWARG,
        WORKSPACE_KWARG,
        ReadingListTabsTool,
        ReadMaterialTool,
    )
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    from deeptutor.reading import ReadingStore
    import deeptutor.reading.catalog_store as legacy_catalog_module
    import deeptutor.reading.store as reading_store_module
    from deeptutor.services.path_service import PathService

    actor = business_actors.tenants[0].owners[0]
    content_id = "f" * 16
    material_id = "rm_ffffffffffff"
    workspace_id = "tool-workspace"
    resource_root = tmp_path / "resources"
    reading_root = (
        resource_root
        / str(uuid.UUID(actor.tenant_id))
        / hashlib.sha256(actor.user_id.encode()).hexdigest()
        / "reading"
    )
    ReadingStore(reading_root).ingest_units(
        content_id,
        filename="tool.md",
        title="Tool material",
        units=["tool body from pg alias"],
        mime="text/markdown",
    )
    catalog = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    await catalog.run(
        lambda u: (
            u.upsert_material(
                content_id=content_id,
                material_id=material_id,
                filename="tool-alias.md",
                title="Tool alias",
                source_kind="file",
                mime="text/markdown",
                status="ready",
            ),
            u.create_workspace("Tool workspace", [material_id], workspace_id=workspace_id),
        )
    )

    def forbid_sqlite_catalog(*_args, **_kwargs):
        raise AssertionError("reading tools must not open _catalog.sqlite3")

    monkeypatch.setattr(legacy_catalog_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setattr(reading_store_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                resources=OwnerResourceProvider(resource_root),
            )
        ):
            tabs = await ReadingListTabsTool().execute(**{WORKSPACE_KWARG: workspace_id})
            assert tabs.success, tabs.content
            assert tabs.metadata["tabs"][0]["material_id"] == material_id
            assert "tool body" not in tabs.content

            read = await ReadMaterialTool().execute(
                locators="1", **{BINDING_KWARG: {"material_id": material_id}}
            )
            assert read.success, read.content
            assert "tool body from pg alias" in read.content
    finally:
        reset_current_user(token)
        PathService.reset_instance()


async def test_upload_material_route_registers_pg_catalog_without_sqlite_catalog(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: uploaded materials are registered in legacy _catalog.sqlite3."""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    import deeptutor.reading.catalog_store as legacy_catalog_module
    import deeptutor.reading.store as reading_store_module
    from deeptutor.services.path_service import PathService

    actor = business_actors.tenants[0].owners[0]
    catalog = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    resource_root = tmp_path / "resources"

    def forbid_sqlite_catalog(*_args, **_kwargs):
        raise AssertionError("upload API must not write _catalog.sqlite3")

    monkeypatch.setattr(legacy_catalog_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setattr(reading_store_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                resources=OwnerResourceProvider(resource_root),
            )
        ):
            response = TestClient(_app(), raise_server_exceptions=False).post(
                "/api/reading/materials",
                files={"file": ("pg-upload.md", b"# PG upload\n\nBody from upload.", "text/markdown")},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["filename"] == "pg-upload.md"
        material_id = body["material_id"]
        record = await catalog.run(lambda u: u.get_material(material_id))
        assert record is not None
        assert record.filename == "pg-upload.md"
        assert (_reading_root(resource_root, actor) / record.content_id).is_dir()
    finally:
        reset_current_user(token)
        PathService.reset_instance()


async def test_import_url_route_queues_pg_workspace_without_sqlite_catalog(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: URL import queue still constructs the legacy catalog."""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    import deeptutor.reading.catalog_store as legacy_catalog_module
    from deeptutor.reading.ingestion import ReadingIngestionService, url_material_id
    from deeptutor.services.path_service import PathService

    actor = business_actors.tenants[0].owners[0]
    catalog = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    target_url = "https://example.com/pg-reading"
    expected_material_id = url_material_id(target_url)

    async def noop_process_url(self, material_id):  # noqa: ANN001
        return None

    def forbid_sqlite_catalog(*_args, **_kwargs):
        raise AssertionError("URL import API must not write _catalog.sqlite3")

    monkeypatch.setattr(ReadingIngestionService, "process_url", noop_process_url)
    monkeypatch.setattr(legacy_catalog_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                resources=OwnerResourceProvider(tmp_path / "resources"),
            )
        ):
            response = TestClient(_app(), raise_server_exceptions=False).post(
                "/api/reading/library/import-urls",
                json={
                    "urls": [target_url],
                    "workspace_title": "PG imports",
                    "workspace_id": "",
                },
            )

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["materials"][0]["material_id"] == expected_material_id
        assert body["workspace"]["tabs"][0]["material"]["material_id"] == expected_material_id
        record = await catalog.run(lambda u: u.get_material(expected_material_id))
        assert record is not None
        assert record.source_url == target_url
    finally:
        reset_current_user(token)
        PathService.reset_instance()


async def test_retry_import_route_updates_pg_status_without_sqlite_catalog(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: retrying an import still constructed the legacy catalog."""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    import deeptutor.reading.catalog_store as legacy_catalog_module
    from deeptutor.reading.ingestion import ReadingIngestionService
    from deeptutor.services.path_service import PathService

    actor = business_actors.tenants[0].owners[0]
    catalog = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    material_id = "retry-reading-material"
    await catalog.run(
        lambda u: u.upsert_material(
            content_id=material_id,
            material_id=material_id,
            filename="retry.url",
            title="Retry URL",
            source_kind="web",
            source_url="https://example.com/retry",
            mime="text/html",
            status="failed",
            error_code="web_fetch_failed",
            error_detail="boom",
        )
    )

    async def noop_retry(self, material_id):  # noqa: ANN001
        return None

    def forbid_sqlite_catalog(*_args, **_kwargs):
        raise AssertionError("retry API must not write _catalog.sqlite3")

    monkeypatch.setattr(ReadingIngestionService, "retry", noop_retry)
    monkeypatch.setattr(legacy_catalog_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                resources=OwnerResourceProvider(tmp_path / "resources"),
            )
        ):
            response = TestClient(_app(), raise_server_exceptions=False).post(
                f"/api/reading/materials/{material_id}/retry"
            )

        assert response.status_code == 202, response.text
        body = response.json()["material"]
        assert body["material_id"] == material_id
        assert body["status"] == "queued"
        record = await catalog.run(lambda u: u.get_material(material_id))
        assert record is not None
        assert record.status.value == "queued"
    finally:
        reset_current_user(token)
        PathService.reset_instance()


async def test_organize_reading_notes_uses_pg_workspace_and_resource_annotations(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: notes export reads workspace/materials from legacy catalog."""

    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    from deeptutor.reading import Annotation, ReadingStore
    import deeptutor.reading.catalog_store as legacy_catalog_module
    import deeptutor.reading.store as reading_store_module
    from deeptutor.services.path_service import PathService

    actor = business_actors.tenants[0].owners[0]
    content_id = "1" * 16
    material_id = "rm_111111111111"
    workspace_id = "notes-workspace"
    resource_root = tmp_path / "resources"
    store = ReadingStore(_reading_root(resource_root, actor))
    store.ingest_units(
        content_id,
        filename="notes.md",
        title="Notes payload",
        units=["highlight target"],
        mime="text/markdown",
    )
    catalog = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    record, _workspace = await catalog.run(
        lambda u: (
            u.upsert_material(
                content_id=content_id,
                material_id=material_id,
                filename="notes-alias.md",
                title="Notes alias",
                source_kind="file",
                mime="text/markdown",
                status="ready",
            ),
            u.create_workspace("Notes workspace", [material_id], workspace_id=workspace_id),
        )
    )
    ReadingStore(
        _reading_root(resource_root, actor),
        material_resolver=lambda candidate: record if candidate == material_id else None,
    ).save_annotation(
        material_id=material_id,
        annotation=Annotation(
            annotation_id="ann_notes",
            locator=1,
            quote="highlight target",
            note="important note",
            color="yellow",
        ),
    )

    def forbid_sqlite_catalog(*_args, **_kwargs):
        raise AssertionError("reading notes API must not open _catalog.sqlite3")

    monkeypatch.setattr(legacy_catalog_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setattr(reading_store_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                resources=OwnerResourceProvider(resource_root),
            )
        ):
            response = TestClient(_app(), raise_server_exceptions=False).post(
                f"/api/reading/workspaces/{workspace_id}/notes/organize",
                json={"material_ids": [material_id]},
            )

        assert response.status_code == 200, response.text
        notes = response.json()["notes"]
        assert notes["material_ids"] == [material_id]
        assert "Notes alias" in notes["markdown"]
        assert "important note" in notes["markdown"]
    finally:
        reset_current_user(token)
        PathService.reset_instance()


async def test_reading_capability_uses_pg_alias_for_prompt_and_locate_without_sqlite_catalog(
    business_sync_database,
    business_actors,
    pg_scope_factory,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production break caught: reading capability prompt/locate bypasses PG aliases."""

    from deeptutor.capabilities.reading.capability import (
        MATERIAL_ID_KEY,
        WORKSPACE_ID_KEY,
        ReadingCapability,
    )
    from deeptutor.core.context import UnifiedContext
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
        user_from_token_payload,
    )
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
    from deeptutor.persistence.resources import OwnerResourceProvider
    from deeptutor.reading import ReadingStore
    import deeptutor.reading.catalog_store as legacy_catalog_module
    import deeptutor.reading.store as reading_store_module
    from deeptutor.runtime.stream_bus import StreamBus
    from deeptutor.services.path_service import PathService

    actor = business_actors.tenants[0].owners[0]
    content_id = "2" * 16
    material_id = "rm_222222222222"
    workspace_id = "capability-workspace"
    resource_root = tmp_path / "resources"
    ReadingStore(_reading_root(resource_root, actor)).ingest_units(
        content_id,
        filename="capability.md",
        title="Capability payload",
        units=["Capability body contains a pg-only needle."],
        mime="text/markdown",
    )
    catalog = AsyncReadingCatalogStore(business_sync_database, pg_scope_factory(actor))
    await catalog.run(
        lambda u: (
            u.upsert_material(
                content_id=content_id,
                material_id=material_id,
                filename="capability-alias.md",
                title="Capability alias",
                source_kind="file",
                mime="text/markdown",
                status="ready",
            ),
            u.create_workspace("Capability workspace", [material_id], workspace_id=workspace_id),
        )
    )

    def forbid_sqlite_catalog(*_args, **_kwargs):
        raise AssertionError("reading capability must not open _catalog.sqlite3")

    monkeypatch.setattr(legacy_catalog_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setattr(reading_store_module.sqlite3, "connect", forbid_sqlite_catalog)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    token = set_current_user(user_from_token_payload(actor.identity))
    try:
        context = UnifiedContext(
            session_id="s1",
            user_message="Where is the pg-only needle?",
            metadata={
                MATERIAL_ID_KEY: material_id,
                WORKSPACE_ID_KEY: workspace_id,
            },
        )
        with provider_context(
            ApplicationProviders(
                reading=SimpleNamespace(get=lambda: catalog),
                resources=OwnerResourceProvider(resource_root),
            )
        ):
            capability = ReadingCapability()
            block = capability.system_block(context, language="en", prompts={})
            locate = await capability.pre_loop(context, StreamBus())

        assert block is not None
        assert "capability-alias.md" in block.content
        assert "Capability workspace" in block.content
        assert locate is not None
        assert "pg-only needle" in locate.content
    finally:
        reset_current_user(token)
        PathService.reset_instance()
