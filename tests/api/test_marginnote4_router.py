"""Auth boundary of the MarginNote 4 device bridge.

``/sync`` and ``/heartbeat`` are the only endpoints in the app reachable
without a DeepTutor session — a paired device presents
``Authorization: MarginNote <device_id>:<token>`` instead. Two properties of
that boundary are pinned here because both were wrong when the bridge landed:

* an unauthenticated request must not write anything to disk, and
* a token must not be issued into a workspace the sync path cannot read.

Mounted on a bare FastAPI app so the suite does not boot every other router.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import marginnote4
from deeptutor.api.routers.auth import require_auth
from deeptutor.app.container import set_application_container


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    set_application_container(None)
    yield tmp_path
    set_application_container(None)


@pytest.fixture
def client(home: Path):
    app = FastAPI()
    app.include_router(marginnote4.router, prefix="/api/marginnote4")
    # Session auth is the subject of its own tests; here it only needs to be
    # out of the way so the device boundary is what gets exercised.
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def _sqlite_artifacts(home: Path) -> list[Path]:
    return [
        path
        for path in home.rglob("*")
        if path.suffix in {".db", ".sqlite", ".sqlite3"} or path.name.endswith(("-wal", "-shm"))
    ]


def test_unauthenticated_sync_writes_nothing_to_disk(client, home: Path) -> None:
    """Device auth must fail before any runtime storage can be created.

    The PG router parses the owner from the device id and verifies the token
    before touching a store; invalid credentials must not resurrect the old
    per-KB SQLite creation primitive.
    """
    for n in range(5):
        response = client.post(
            "/api/marginnote4/sync",
            json={"cursor": "", "objects": [], "deleted_ids": []},
            headers={
                "Authorization": "MarginNote fake-device:fake-token",
                "X-MN4-KB": f"invented-{n}",
            },
        )
        assert response.status_code == 403

    assert _sqlite_artifacts(home) == []


def test_unauthenticated_heartbeat_writes_nothing_to_disk(client, home: Path) -> None:
    response = client.post(
        "/api/marginnote4/heartbeat",
        headers={
            "Authorization": "MarginNote fake-device:fake-token",
            "X-MN4-KB": "invented",
        },
    )
    assert response.status_code == 403
    assert _sqlite_artifacts(home) == []


@pytest.mark.parametrize(
    "header",
    [None, "Bearer abc", "MarginNote no-colon-here"],
)
def test_malformed_device_credentials_are_rejected(client, home: Path, header) -> None:
    headers = {} if header is None else {"Authorization": header}
    response = client.post("/api/marginnote4/heartbeat", headers=headers)
    assert response.status_code == 401
    assert _sqlite_artifacts(home) == []


def test_pair_requires_postgres_runtime_and_creates_no_sqlite(client, home: Path) -> None:
    response = client.post("/api/marginnote4/pair", json={"device_name": "iPad"})
    assert response.status_code == 503
    assert "PostgreSQL MarginNote runtime" in response.json()["detail"]
    assert _sqlite_artifacts(home) == []


def test_revoke_requires_postgres_runtime_and_creates_no_sqlite(client, home: Path) -> None:
    response = client.delete("/api/marginnote4/devices/dtmn4.dXNlcg.abc")
    assert response.status_code == 503
    assert _sqlite_artifacts(home) == []


def test_sync_batch_is_bounded(client) -> None:
    """An oversized batch is refused by validation, before any work starts."""
    oversized = [
        {"object_id": f"o{i}", "object_type": "note"} for i in range(marginnote4.MAX_SYNC_BATCH + 1)
    ]

    response = client.post(
        "/api/marginnote4/sync",
        json={"cursor": "", "objects": oversized, "deleted_ids": []},
        headers={"Authorization": "MarginNote fake-device:fake-token"},
    )
    assert response.status_code == 422
