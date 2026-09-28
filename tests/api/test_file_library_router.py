"""Request-scoped regression coverage for the file library API (issue #1437)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest_plugins = ("tests.fixtures.postgres",)

from deeptutor.services.auth import TokenPayload
from deeptutor.services.storage.file_library import reset_file_library_store

LibraryAppFactory = Callable[..., tuple[TestClient, Path]]


@pytest.fixture
def library_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pg_dsn: str) -> LibraryAppFactory:
    """Build a standalone FastAPI app with the PostgreSQL file_library router."""
    from uuid import uuid4

    import psycopg

    from deeptutor.api.routers import file_library
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.persistence.postgres.connection import SyncDatabase
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
    from deeptutor.persistence.postgres.scope import TenantScope
    from deeptutor.services.storage.file_library import FileLibraryStore
    from tests.fixtures.postgres import single_database_user_dsn

    asyncio.run(MigrationRunner(pg_dsn).apply())
    runtime_dsn = single_database_user_dsn(pg_dsn)
    tenant_id = str(uuid4())
    seeded_users = {
        "u_default": ("default", "tenant_admin"),
        "u_alice": ("alice", "user"),
        "u_bob": ("bob", "user"),
    }
    with psycopg.connect(pg_dsn) as connection:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO enterprise.tenants(
                    id, external_eligibility, local_enabled, provisioning_status,
                    auth_epoch, bootstrap_completed
                ) VALUES (%s,'not_required',true,'ready','file-library-api-test',true)
                """,
                (tenant_id,),
            )
            for user_id, (username, role) in seeded_users.items():
                connection.execute(
                    """
                    INSERT INTO enterprise.users(tenant_id,id,username,role)
                    VALUES (%s,%s,%s,%s)
                    """,
                    (tenant_id, user_id, username, role),
                )

    sync_db = SyncDatabase(
        runtime_dsn,
        resource=f"file-library-api-{uuid4().hex[:8]}",
        max_size=4,
        max_waiting=8,
    )
    sync_db.__enter__()
    stores: dict[str, FileLibraryStore] = {}

    def current_store() -> FileLibraryStore:
        user = get_current_user()
        key = f"{user.scope.tenant_id}:{user.id}"
        if key not in stores:
            stores[key] = FileLibraryStore(
                sync_db,
                TenantScope(user.scope.tenant_id, user.id),
                root=tmp_path / "library-files" / user.id,
            )
        return stores[key]

    monkeypatch.setattr(file_library._fl, "get_file_library_store", current_store)

    default_tokens = {
        "default-token": TokenPayload(
            username="default",
            role="tenant_admin",
            user_id="u_default",
            tenant_id=tenant_id,
        ),
        "alice-token": TokenPayload(
            username="alice",
            role="user",
            user_id="u_alice",
            tenant_id=tenant_id,
        ),
        "bob-token": TokenPayload(
            username="bob",
            role="user",
            user_id="u_bob",
            tenant_id=tenant_id,
        ),
    }

    class _AuthProvider:
        cookie_secure = False

        def __init__(self, payloads: dict[str, TokenPayload | None]) -> None:
            self.payloads = payloads

        async def decode(self, token: str) -> TokenPayload:
            payload = self.payloads.get(token)
            if payload is None:
                raise PermissionError("invalid token")
            return payload

    def make_app(
        auth_enabled: bool = False,
        tokens: dict[str, TokenPayload | None] | None = None,
    ) -> tuple[TestClient, Path]:
        del auth_enabled
        if tokens is None:
            payloads = default_tokens
        else:
            payloads = {}
            for token, payload in tokens.items():
                if payload is None or payload.tenant_id:
                    payloads[token] = payload
                else:
                    payloads[token] = TokenPayload(
                        username=payload.username,
                        role=payload.role,
                        user_id=payload.user_id,
                        tenant_id=tenant_id,
                    )
        app = FastAPI()
        app.state.auth_provider = _AuthProvider(payloads)
        app.include_router(file_library.router, prefix="/files/library")
        client = TestClient(app)
        if "default-token" in payloads:
            client.cookies.set("dt_token", "default-token")
        return client, tmp_path

    try:
        yield make_app
    finally:
        reset_file_library_store()
        sync_db.__exit__(None, None, None)


# ── tests ─────────────────────────────────────────────────────────────────


def test_add_file_returns_entry(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.post(
        "/files/library/",
        data={"filename": "report.txt", "mime_type": "text/plain"},
        files={"file": ("report.txt", b"Hello, world!", "text/plain")},
    )
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["filename"] == "report.txt"
    assert len(data["sha256"]) == 64
    assert data["size_bytes"] == 13
    assert data["is_deleted"] is False
    assert data["id"]


def test_add_file_deduplicates_by_hash(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    payload = {"filename": "dup.txt", "mime_type": "text/plain"}
    files = {"file": ("dup.txt", b"same content", "text/plain")}
    r1 = client.post("/files/library/", data=payload, files=files)
    r2 = client.post("/files/library/", data=payload, files=files)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


def test_add_file_different_content_gives_different_id(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r1 = client.post(
        "/files/library/",
        data={"filename": "a.txt", "mime_type": ""},
        files={"file": ("a.txt", b"content A", "")},
    )
    r2 = client.post(
        "/files/library/",
        data={"filename": "a.txt", "mime_type": ""},
        files={"file": ("a.txt", b"content B", "")},
    )
    assert r1.json()["id"] != r2.json()["id"]


def test_list_files_returns_active(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    client.post(
        "/files/library/",
        data={"filename": "f1.txt", "mime_type": ""},
        files={"file": ("f1.txt", b"data1", "")},
    )
    client.post(
        "/files/library/",
        data={"filename": "f2.txt", "mime_type": ""},
        files={"file": ("f2.txt", b"data2", "")},
    )
    response = client.get("/files/library/")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 2
    assert {e["filename"] for e in entries} == {"f1.txt", "f2.txt"}


def test_list_files_excludes_deleted(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "todelete.txt", "mime_type": ""},
        files={"file": ("todelete.txt", b"delete me", "")},
    )
    file_id = r.json()["id"]
    client.delete(f"/files/library/{file_id}")
    entries = client.get("/files/library/").json()
    assert file_id not in {e["id"] for e in entries}


def test_list_files_respects_limit_offset(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    for i in range(5):
        client.post(
            "/files/library/",
            data={"filename": f"f{i}.txt", "mime_type": ""},
            files={"file": (f"f{i}.txt", f"d{i}".encode(), "")},
        )
    page1 = client.get("/files/library/?limit=2&offset=0").json()
    page2 = client.get("/files/library/?limit=2&offset=2").json()
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["id"] != page2[0]["id"]


def test_search_files_returns_matches(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    client.post(
        "/files/library/",
        data={"filename": "quarterly_report.pdf", "mime_type": ""},
        files={"file": ("quarterly_report.pdf", b"Q3 report", "")},
    )
    client.post(
        "/files/library/",
        data={"filename": "photo.jpg", "mime_type": ""},
        files={"file": ("photo.jpg", b"photo bytes", "")},
    )
    results = client.get("/files/library/search?q=report").json()
    assert len(results) == 1
    assert results[0]["filename"] == "quarterly_report.pdf"


def test_search_files_no_match_returns_empty(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    client.post(
        "/files/library/",
        data={"filename": "alpha.txt", "mime_type": ""},
        files={"file": ("alpha.txt", b"alpha", "")},
    )
    results = client.get("/files/library/search?q=beta").json()
    assert results == []


def test_search_files_excludes_deleted(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "to_search.txt", "mime_type": ""},
        files={"file": ("to_search.txt", b"search me", "")},
    )
    file_id = r.json()["id"]
    client.delete(f"/files/library/{file_id}")
    results = client.get("/files/library/search?q=search").json()
    assert all(e["id"] != file_id for e in results)


def test_get_file_returns_entry(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "myfile.txt", "mime_type": "text/plain"},
        files={"file": ("myfile.txt", b"content", "text/plain")},
    )
    file_id = r.json()["id"]
    entry = client.get(f"/files/library/{file_id}").json()
    assert entry["id"] == file_id
    assert entry["filename"] == "myfile.txt"


def test_get_file_nonexistent_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.get("/files/library/nonexistent-id")
    assert response.status_code == 404


def test_delete_file_soft_deletes(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "delme.txt", "mime_type": ""},
        files={"file": ("delme.txt", b"delete", "")},
    )
    file_id = r.json()["id"]
    response = client.delete(f"/files/library/{file_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    entry = client.get(f"/files/library/{file_id}").json()
    assert entry["is_deleted"] is True


def test_delete_file_nonexistent_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.delete("/files/library/nonexistent-id")
    assert response.status_code == 404


def test_delete_file_idempotent(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "dupdel.txt", "mime_type": ""},
        files={"file": ("dupdel.txt", b"dup", "")},
    )
    file_id = r.json()["id"]
    r1 = client.delete(f"/files/library/{file_id}")
    r2 = client.delete(f"/files/library/{file_id}")
    assert r1.status_code == r2.status_code == 200


def test_restore_file_clears_deleted_flag(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "restoreme.txt", "mime_type": ""},
        files={"file": ("restoreme.txt", b"restore", "")},
    )
    file_id = r.json()["id"]
    client.delete(f"/files/library/{file_id}")
    response = client.post(f"/files/library/{file_id}/restore")
    assert response.status_code == 200
    assert response.json()["restored"] is True
    entry = client.get(f"/files/library/{file_id}").json()
    assert entry["is_deleted"] is False


def test_restore_file_nonexistent_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.post("/files/library/nonexistent-id/restore")
    assert response.status_code == 404


def test_restore_file_idempotent(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "active.txt", "mime_type": ""},
        files={"file": ("active.txt", b"active", "")},
    )
    file_id = r.json()["id"]
    r1 = client.post(f"/files/library/{file_id}/restore")
    r2 = client.post(f"/files/library/{file_id}/restore")
    assert r1.status_code == r2.status_code == 200


def test_download_library_file(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    content = b"downloadable content"
    r = client.post(
        "/files/library/",
        data={"filename": "download.txt", "mime_type": "text/plain"},
        files={"file": ("download.txt", content, "text/plain")},
    )
    file_id = r.json()["id"]
    response = client.get(f"/files/library/{file_id}/download")
    assert response.status_code == 200
    assert response.content == content


def test_download_deleted_file_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "del.txt", "mime_type": ""},
        files={"file": ("del.txt", b"del", "")},
    )
    file_id = r.json()["id"]
    client.delete(f"/files/library/{file_id}")
    response = client.get(f"/files/library/{file_id}/download")
    assert response.status_code == 404


def test_download_nonexistent_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.get("/files/library/nonexistent-id/download")
    assert response.status_code == 404


def test_upload_and_list_are_isolated_between_users(library_app: LibraryAppFactory) -> None:
    """Regression test: the FileLibraryStore singleton used to be keyed by a
    constant ("default") instead of the resolved per-user root, so the
    second authenticated user to hit any endpoint transparently shared the
    first user's library (list/get/download all leaked across accounts).
    """
    tokens = {
        "alice-token": TokenPayload(username="alice", role="user", user_id="u_alice"),
        "bob-token": TokenPayload(username="bob", role="user", user_id="u_bob"),
    }
    client, _ = library_app(auth_enabled=True, tokens=tokens)

    with client:
        client.cookies.set("dt_token", "alice-token")
        upload = client.post(
            "/files/library/",
            data={"filename": "alice-only.txt", "mime_type": "text/plain"},
            files={"file": ("alice-only.txt", b"alice's secret file", "text/plain")},
        )
        assert upload.status_code == 200
        alice_file_id = upload.json()["id"]

        client.cookies.set("dt_token", "bob-token")
        bob_list = client.get("/files/library/")
        bob_get = client.get(f"/files/library/{alice_file_id}")
        bob_download = client.get(f"/files/library/{alice_file_id}/download")

    assert bob_list.json() == []
    assert bob_get.status_code == 404
    assert bob_download.status_code == 404
