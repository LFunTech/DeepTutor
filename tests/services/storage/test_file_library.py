"""Tests for the Persistent File Library feature (issue #1437)."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

pytest_plugins = ("tests.fixtures.postgres",)

from deeptutor.services.storage.file_library import (
    FileLibraryStore,
    get_file_library_store,
    reset_file_library_store,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pg_file_library_runtime(pg_dsn: str, tmp_path: Path):
    from uuid import uuid4

    import psycopg

    from deeptutor.persistence.postgres.connection import SyncDatabase
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
    from deeptutor.persistence.postgres.scope import TenantScope
    from tests.fixtures.postgres import single_database_user_dsn

    asyncio.run(MigrationRunner(pg_dsn).apply())
    runtime_dsn = single_database_user_dsn(pg_dsn)
    tenant_id = str(uuid4())
    owner_id = "file-library-owner"
    with psycopg.connect(pg_dsn) as connection:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO enterprise.tenants(
                    id, external_eligibility, local_enabled, provisioning_status,
                    auth_epoch, bootstrap_completed
                ) VALUES (%s,'not_required',true,'ready','file-library-test',true)
                """,
                (tenant_id,),
            )
            connection.execute(
                """
                INSERT INTO enterprise.users(tenant_id,id,username,role)
                VALUES (%s,%s,%s,'tenant_admin')
                """,
                (tenant_id, owner_id, owner_id),
            )
    with SyncDatabase(
        runtime_dsn,
        resource=f"file-library-{uuid4().hex[:8]}",
        max_size=4,
        max_waiting=8,
    ) as db:
        yield db, TenantScope(tenant_id, owner_id), tmp_path / "library-files"


@pytest.fixture
def store(pg_file_library_runtime) -> FileLibraryStore:
    db, scope, root = pg_file_library_runtime
    reset_file_library_store()
    return FileLibraryStore(db, scope, root=root)


class _SingletonResources:
    def __init__(self, root: Path) -> None:
        self.root = root

    def owner_root(self, tenant_id: str, owner_id: str, kind: str) -> Path:
        path = self.root / tenant_id / owner_id / kind
        path.mkdir(parents=True, exist_ok=True)
        return path


class _SingletonRuntime:
    def __init__(self, db, scope, root: Path) -> None:
        self.sync_db = db
        self._scope = scope
        self.resources = _SingletonResources(root)

    def scope_for_current_user(self):
        return self._scope


class _SingletonContainer:
    def __init__(self, runtime: _SingletonRuntime) -> None:
        self.postgres_runtime = runtime
        self.resources_provider = runtime.resources


def _singleton_provider_context(pg_file_library_runtime):
    from deeptutor.core.providers import ApplicationProviders, provider_context

    db, scope, root = pg_file_library_runtime
    runtime = _SingletonRuntime(db, scope, root / "singleton-resources")
    return provider_context(ApplicationProviders(container=_SingletonContainer(runtime)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content(data: bytes) -> tuple[str, str]:
    """Return (sha256, base_name) for the data."""
    return _sha256(data), "file.pdf"


# ---------------------------------------------------------------------------
# add_file
# ---------------------------------------------------------------------------


def test_add_file_returns_entry(store: FileLibraryStore) -> None:
    """add_file must return a complete library entry."""
    data = b"Hello, World!"
    entry = asyncio.run(store.add_file(data=data, filename="hello.txt", mime_type="text/plain"))
    assert entry["id"] is not None
    assert entry["sha256"] == _sha256(data)
    assert entry["filename"] == "hello.txt"
    assert entry["mime_type"] == "text/plain"
    assert entry["size_bytes"] == len(data)
    assert entry["is_deleted"] is False


def test_add_file_persists_to_disk(store: FileLibraryStore) -> None:
    """The file bytes must be stored on disk under the library root."""
    data = b"Test content"
    entry = asyncio.run(store.add_file(data=data, filename="test.txt", mime_type="text/plain"))
    resolved = store.resolve_path(entry["id"])
    assert resolved is not None
    assert resolved.read_bytes() == data


def test_add_file_deduplicates_by_hash(store: FileLibraryStore) -> None:
    """Uploading identical content must return the existing entry, not create a duplicate."""
    data = b"Duplicate content"
    e1 = asyncio.run(
        store.add_file(data=data, filename="original.pdf", mime_type="application/pdf")
    )
    e2 = asyncio.run(store.add_file(data=data, filename="copy.pdf", mime_type="application/pdf"))
    assert e1["id"] == e2["id"]
    assert e1["sha256"] == e2["sha256"]


def test_add_file_different_content_gives_different_hash(store: FileLibraryStore) -> None:
    """Different byte content must produce different hashes."""
    e1 = asyncio.run(store.add_file(data=b"Content A", filename="a.txt", mime_type="text/plain"))
    e2 = asyncio.run(store.add_file(data=b"Content B", filename="b.txt", mime_type="text/plain"))
    assert e1["sha256"] != e2["sha256"]
    assert e1["id"] != e2["id"]


def test_add_file_concurrent_uploads_of_same_content_do_not_duplicate(
    store: FileLibraryStore,
) -> None:
    """Regression test: concurrent uploads of identical content used to all
    miss the dedup SELECT before any of them committed its INSERT (a TOCTOU
    race across the OS threads ``asyncio.to_thread`` dispatches to), each
    creating its own duplicate row and file on disk instead of deduplicating.
    """
    import threading

    data = b"same content uploaded from multiple tabs at once"
    n_threads = 8
    barrier = threading.Barrier(n_threads)
    results: list[dict] = [None] * n_threads  # type: ignore[list-item]

    def upload(i: int) -> None:
        barrier.wait()
        results[i] = store._add_file_sync(data, f"upload-{i}.txt", "text/plain")

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = {r["id"] for r in results}
    assert len(ids) == 1, f"expected a single deduplicated entry, got {len(ids)}: {ids}"

    entries = asyncio.run(store.list_files())
    assert len(entries) == 1


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------


def test_list_files_returns_all_active(store: FileLibraryStore) -> None:
    """list_files must return every non-deleted entry, newest first."""
    # Track IDs and creation times of files we create to verify relative ordering.
    own_ids = []
    own_created_ats = []
    for i in range(5):
        e = asyncio.run(
            store.add_file(
                data=f"Content {i}".encode(), filename=f"file{i}.txt", mime_type="text/plain"
            )
        )
        own_ids.append(e["id"])
        own_created_ats.append(e["created_at"])
    entries = asyncio.run(store.list_files())
    # Among the entries we created, verify newest-first ordering using timestamps.
    own_results = [e for e in entries if e["id"] in own_ids]
    assert len(own_results) == 5
    result_created_ats = [e["created_at"] for e in own_results]
    # Sort by created_at DESC to get the expected order.
    expected_order = [eid for _, eid in sorted(zip(own_created_ats, own_ids), reverse=True)]
    assert [e["id"] for e in own_results] == expected_order


def test_list_files_respects_limit_offset(store: FileLibraryStore) -> None:
    """limit and offset must paginate the result list."""
    for i in range(5):
        asyncio.run(
            store.add_file(data=f"Data {i}".encode(), filename=f"f{i}.txt", mime_type="text/plain")
        )
    page1 = asyncio.run(store.list_files(limit=2, offset=0))
    page2 = asyncio.run(store.list_files(limit=2, offset=2))
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["id"] != page2[0]["id"]


def test_list_files_excludes_deleted(store: FileLibraryStore) -> None:
    """Soft-deleted entries must not appear in list_files."""
    e1 = asyncio.run(store.add_file(data=b"Keep me", filename="keep.txt", mime_type="text/plain"))
    e2 = asyncio.run(
        store.add_file(data=b"Delete me", filename="delete.txt", mime_type="text/plain")
    )
    asyncio.run(store.delete_file(e2["id"]))
    entries = asyncio.run(store.list_files())
    ids = [e["id"] for e in entries]
    assert e1["id"] in ids
    assert e2["id"] not in ids


# ---------------------------------------------------------------------------
# search_files
# ---------------------------------------------------------------------------


def test_search_files_by_filename(store: FileLibraryStore) -> None:
    """search_files must match on filename."""
    asyncio.run(
        store.add_file(
            data=b"Content", filename="project_proposal.pdf", mime_type="application/pdf"
        )
    )
    asyncio.run(store.add_file(data=b"Content", filename="notes.txt", mime_type="text/plain"))
    results = asyncio.run(store.search_files("project"))
    assert len(results) == 1
    assert results[0]["filename"] == "project_proposal.pdf"


def test_search_files_no_match_returns_empty(store: FileLibraryStore) -> None:
    """A query that matches nothing must return an empty list."""
    asyncio.run(store.add_file(data=b"Content", filename="other.txt", mime_type="text/plain"))
    results = asyncio.run(store.search_files("nonexistent_term_xyz"))
    assert results == []


def test_search_files_excludes_deleted(store: FileLibraryStore) -> None:
    """Deleted entries must not appear in search results."""
    e = asyncio.run(
        store.add_file(data=b"Important document", filename="doc.pdf", mime_type="application/pdf")
    )
    asyncio.run(store.delete_file(e["id"]))
    results = asyncio.run(store.search_files("Important"))
    assert results == []


# ---------------------------------------------------------------------------
# delete_file (soft delete)
# ---------------------------------------------------------------------------


def test_delete_file_soft_deletes(store: FileLibraryStore) -> None:
    """delete_file must set is_deleted=True without removing the row."""
    e = asyncio.run(
        store.add_file(data=b"Content", filename="todelete.txt", mime_type="text/plain")
    )
    result = asyncio.run(store.delete_file(e["id"]))
    assert result is True
    entry = asyncio.run(store.get_file(e["id"]))
    assert entry is not None
    assert entry["is_deleted"] is True


def test_delete_file_idempotent(store: FileLibraryStore) -> None:
    """Deleting an already-deleted entry must return True without error."""
    e = asyncio.run(store.add_file(data=b"Content", filename="file.txt", mime_type="text/plain"))
    asyncio.run(store.delete_file(e["id"]))
    result = asyncio.run(store.delete_file(e["id"]))
    assert result is True


def test_delete_file_nonexistent_returns_false(store: FileLibraryStore) -> None:
    """Deleting a non-existent ID must return False."""
    result = asyncio.run(store.delete_file("nonexistent_id"))
    assert result is False


# ---------------------------------------------------------------------------
# hard_delete_file
# ---------------------------------------------------------------------------


def test_hard_delete_file_removes_row(store: FileLibraryStore) -> None:
    """hard_delete_file must physically remove the row from the database."""
    e = asyncio.run(
        store.add_file(data=b"Content", filename="permanent.txt", mime_type="text/plain")
    )
    asyncio.run(store.delete_file(e["id"]))  # must be soft-deleted first
    result = asyncio.run(store.hard_delete_file(e["id"]))
    assert result is True
    entry = asyncio.run(store.get_file(e["id"]))
    assert entry is None


def test_hard_delete_file_without_soft_delete_fails(store: FileLibraryStore) -> None:
    """hard_delete_file must refuse to delete a non-deleted entry."""
    e = asyncio.run(store.add_file(data=b"Content", filename="file.txt", mime_type="text/plain"))
    result = asyncio.run(store.hard_delete_file(e["id"]))
    assert result is False


# ---------------------------------------------------------------------------
# restore_file
# ---------------------------------------------------------------------------


def test_restore_file_clears_deleted_flag(store: FileLibraryStore) -> None:
    """restore_file must set is_deleted=False."""
    e = asyncio.run(
        store.add_file(data=b"Content", filename="restorable.txt", mime_type="text/plain")
    )
    asyncio.run(store.delete_file(e["id"]))
    result = asyncio.run(store.restore_file(e["id"]))
    assert result is True
    entry = asyncio.run(store.get_file(e["id"]))
    assert entry is not None
    assert entry["is_deleted"] is False


def test_restore_file_idempotent(store: FileLibraryStore) -> None:
    """Restoring an active entry must return True without error."""
    e = asyncio.run(store.add_file(data=b"Content", filename="active.txt", mime_type="text/plain"))
    result = asyncio.run(store.restore_file(e["id"]))
    assert result is True


# ---------------------------------------------------------------------------
# get_file
# ---------------------------------------------------------------------------


def test_get_file_returns_entry(store: FileLibraryStore) -> None:
    """get_file must return the full entry dict for an existing ID."""
    e = asyncio.run(store.add_file(data=b"Content", filename="getme.txt", mime_type="text/plain"))
    fetched = asyncio.run(store.get_file(e["id"]))
    assert fetched is not None
    assert fetched["id"] == e["id"]
    assert fetched["filename"] == "getme.txt"


def test_get_file_deleted_returns_entry_with_flag(store: FileLibraryStore) -> None:
    """get_file must still return the entry (with is_deleted=True) for soft-deleted files."""
    e = asyncio.run(store.add_file(data=b"Content", filename="deleted.txt", mime_type="text/plain"))
    asyncio.run(store.delete_file(e["id"]))
    fetched = asyncio.run(store.get_file(e["id"]))
    assert fetched is not None
    assert fetched["is_deleted"] is True


def test_get_file_nonexistent_returns_none(store: FileLibraryStore) -> None:
    """get_file must return None for a non-existent ID."""
    result = asyncio.run(store.get_file("does_not_exist"))
    assert result is None


# ---------------------------------------------------------------------------
# resolve_path
# ---------------------------------------------------------------------------


def test_resolve_path_returns_existing_file(store: FileLibraryStore) -> None:
    """resolve_path must return the Path to the stored file for a valid ID."""
    e = asyncio.run(
        store.add_file(data=b"PDF content here", filename="doc.pdf", mime_type="application/pdf")
    )
    path = store.resolve_path(e["id"])
    assert path is not None
    assert path.exists()
    assert path.read_bytes() == b"PDF content here"


def test_resolve_path_deleted_returns_none(store: FileLibraryStore) -> None:
    """resolve_path must return None for a soft-deleted entry."""
    e = asyncio.run(
        store.add_file(data=b"Content", filename="deleted_file.txt", mime_type="text/plain")
    )
    asyncio.run(store.delete_file(e["id"]))
    path = store.resolve_path(e["id"])
    assert path is None


def test_resolve_path_nonexistent_returns_none(store: FileLibraryStore) -> None:
    """resolve_path must return None for a non-existent ID."""
    path = store.resolve_path("no_such_id")
    assert path is None


# ---------------------------------------------------------------------------
# Singleton / reset
# ---------------------------------------------------------------------------


def test_get_file_library_store_returns_singleton(pg_file_library_runtime) -> None:
    """get_file_library_store must return the process-wide singleton."""
    reset_file_library_store()
    with _singleton_provider_context(pg_file_library_runtime):
        s1 = get_file_library_store()
        s2 = get_file_library_store()
    assert s1 is s2


def test_reset_clears_singleton(pg_file_library_runtime) -> None:
    """reset_file_library_store must clear the singleton so a new instance is created."""
    reset_file_library_store()
    with _singleton_provider_context(pg_file_library_runtime):
        s1 = get_file_library_store()
        reset_file_library_store()
        s2 = get_file_library_store()
    assert s1 is not s2
