# ruff: noqa: F811
"""Matrix nio SQLite store 离线导入到 PG Matrix store。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import psycopg
import pytest

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401
from tests.persistence.postgres.business.conftest import (  # noqa: F401
    business_actors,
    business_database,
    business_sync_database,
    migrated_pg,
)

pytestmark = pytest.mark.asyncio

nio = pytest.importorskip("nio")
pytest.importorskip("vodozemac")

from nio.crypto import (  # noqa: E402
    InboundGroupSession,
    OlmAccount,
    OlmDevice,
    OutboundGroupSession,
    OutgoingKeyRequest,
    Session,
)

LEGACY_PICKLE = "matrix-legacy-pickle-secret-000000000001"
TARGET_PICKLE = "matrix-target-pickle-secret-000000000001"
ENVELOPE = "matrix-import-envelope-secret-000000000001"
USER_ID = "@bot:example.org"
DEVICE_ID = "DEVICE-A"
PARTNER_ID = "ada"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _snapshot(
    source: Path,
    out: Path,
    *,
    tenant_id: str,
    source_owner: str,
    target_owner: str,
    source_id: str = "legacy-matrix",
) -> Path:
    from deeptutor.persistence.postgres.offline_import import create_sqlite_source_snapshot

    result = create_sqlite_source_snapshot(
        source_db=source,
        output_dir=out,
        source_id=source_id,
        source_version="matrix_nio_sqlite/v0.26",
        source_owner_id=source_owner,
        target_tenant_id=tenant_id,
        owner_mappings={source_owner: target_owner},
        freeze_id=f"freeze-{source_id}",
        stopped_writers=["matrix", "partners"],
        operator="unit-test",
    )
    payload = _read_json(result.manifest_path)
    payload["sources"][0].update(
        {
            "matrix": {
                "partner_id": PARTNER_ID,
                "user_id": USER_ID,
                "device_id": DEVICE_ID,
                "legacy_pickle_secret_id": "legacy-pickle",
                "target_pickle_secret_id": "target-pickle",
                "envelope_secret_id": "matrix-envelope",
                "secret_id": "matrix-import:test",
                "secret_version": 9,
            }
        }
    )
    stable_manifest = out / f"{source_id}.manifest.json"
    return _write_json(stable_manifest, payload)


def _secrets(**overrides: str):
    values = {
        "legacy-pickle": LEGACY_PICKLE,
        "target-pickle": TARGET_PICKLE,
        "matrix-envelope": ENVELOPE,
    }
    values.update(overrides)

    def resolve(secret_id: str) -> str:
        return values[secret_id]

    return resolve


def _make_matrix_sqlite_store(root: Path) -> dict[str, object]:
    from nio.store import SqliteStore

    root.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(USER_ID, DEVICE_ID, str(root), LEGACY_PICKLE, "matrix.sqlite3")
    account = OlmAccount()
    account.shared = True
    store.save_account(account)

    peer = OlmAccount()
    peer.generate_one_time_keys(1)
    peer_curve = peer.identity_keys["curve25519"]
    peer_one_time_key = next(iter(peer.one_time_keys["curve25519"].values()))
    olm_session = Session(account.create_outbound_session(peer_curve, peer_one_time_key))
    store.save_session(peer_curve, olm_session)

    outbound_group = OutboundGroupSession()
    inbound_group = InboundGroupSession(
        outbound_group.session_key,
        signing_key=account.identity_keys["ed25519"],
        sender_key=account.identity_keys["curve25519"],
        room_id="!room:example.org",
        forwarding_chain=["chain-a", "chain-b"],
    )
    store.save_inbound_group_session(inbound_group)

    alice = OlmDevice(
        "@alice:example.org",
        "ALICEDEVICE",
        {"ed25519": "ed-key", "curve25519": "curve-key"},
        display_name="Alice",
    )
    store.save_device_keys({alice.user_id: {alice.id: alice}})
    assert store.verify_device(alice) is True

    store.save_encrypted_rooms({"!room:example.org"})
    store.save_sync_token("sync-token-123")
    request = OutgoingKeyRequest(
        request_id="request-1",
        session_id="session-1",
        room_id="!room:example.org",
        algorithm="m.megolm.v1.aes-sha2",
    )
    store.add_outgoing_key_request(request)
    store.database.close()

    db_path = root / "matrix.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.commit()
    return {
        "db_path": db_path,
        "account_identity_keys": account.identity_keys,
        "peer_curve": peer_curve,
        "olm_session_id": olm_session.id,
        "megolm_session_id": inbound_group.id,
        "megolm_sender_key": inbound_group.sender_key,
    }


async def test_matrix_sqlite_import_reencrypts_full_store_and_preserves_trust_and_cursor(
    tmp_path: Path,
    migrated_pg,
    business_actors,
    business_sync_database,
) -> None:
    """生产导入若不保留 Matrix 加密状态、设备信任或 sync token 应失败。"""

    from deeptutor.persistence.postgres.matrix import PostgresMatrixStore
    from deeptutor.persistence.postgres.offline_import.matrix_sqlite import (
        SQLiteMatrixStoreImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    source = _make_matrix_sqlite_store(tmp_path / "legacy")
    manifest = _snapshot(
        source["db_path"],
        tmp_path / "artifact",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
    )
    manifest_text = manifest.read_text(encoding="utf-8")
    assert LEGACY_PICKLE not in manifest_text
    assert TARGET_PICKLE not in manifest_text
    assert ENVELOPE not in manifest_text

    report = await SQLiteMatrixStoreImporter(
        migrated_pg.admin_dsn,
        secret_resolver=_secrets(),
    ).import_manifest(manifest, operator="unit-test")

    assert report["imported"] == {
        "matrix_accounts": 1,
        "matrix_olm_sessions": 1,
        "matrix_megolm_sessions": 1,
        "matrix_forwarded_chains": 2,
        "matrix_device_keys": 1,
        "matrix_device_key_values": 2,
        "matrix_device_trust_state": 1,
        "matrix_encrypted_rooms": 1,
        "matrix_sync_tokens": 1,
        "matrix_outgoing_key_requests": 1,
    }

    store = PostgresMatrixStore(
        USER_ID,
        DEVICE_ID,
        str(tmp_path / "ignored"),
        TARGET_PICKLE,
        "",
        database=business_sync_database,
        scope=actor.scope,
        partner_id=PARTNER_ID,
        encryption_secret=ENVELOPE,
        secret_id="matrix-import:test",
        secret_version=9,
    )
    loaded_account = store.load_account()
    assert loaded_account is not None
    assert loaded_account.shared is True
    assert loaded_account.identity_keys == source["account_identity_keys"]
    assert store.load_sessions().get(source["peer_curve"]).id == source["olm_session_id"]
    loaded_group = store.load_inbound_group_sessions().get(
        "!room:example.org", source["megolm_sender_key"], source["megolm_session_id"]
    )
    assert loaded_group is not None
    assert loaded_group.forwarding_chain == ["chain-a", "chain-b"]
    devices = store.load_device_keys()
    assert devices["@alice:example.org"]["ALICEDEVICE"].verified is True
    assert store.load_encrypted_rooms() == {"!room:example.org"}
    assert store.load_sync_token() == "sync-token-123"
    assert store.load_outgoing_key_requests()["request-1"].room_id == "!room:example.org"

    async with await psycopg.AsyncConnection.connect(
        migrated_pg.admin_dsn, row_factory=psycopg.rows.dict_row
    ) as connection:
        row = await (
            await connection.execute(
                """
                SELECT secret_id, secret_version, account_ciphertext
                  FROM enterprise.matrix_accounts
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                """,
                (actor.tenant_id, actor.user_id, PARTNER_ID, USER_ID, DEVICE_ID),
            )
        ).fetchone()
    assert row["secret_id"] == "matrix-import:test"
    assert row["secret_version"] == 9
    assert bytes(row["account_ciphertext"]) != loaded_account.pickle(TARGET_PICKLE)


async def test_matrix_sqlite_import_does_not_revive_revoked_device_when_old_snapshot_is_replayed(
    tmp_path: Path,
    migrated_pg,
    business_actors,
    business_sync_database,
) -> None:
    """重复提交旧快照若会覆盖切换后的设备撤销状态应失败。"""

    from deeptutor.persistence.postgres.matrix import PostgresMatrixStore
    from deeptutor.persistence.postgres.offline_import.matrix_sqlite import (
        SQLiteMatrixStoreImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    source = _make_matrix_sqlite_store(tmp_path / "legacy-replay")
    manifest = _snapshot(
        source["db_path"],
        tmp_path / "artifact-replay",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
        source_id="legacy-matrix-replay",
    )
    importer = SQLiteMatrixStoreImporter(
        migrated_pg.admin_dsn,
        secret_resolver=_secrets(),
    )
    await importer.import_manifest(manifest, operator="unit-test")

    store = PostgresMatrixStore(
        USER_ID,
        DEVICE_ID,
        str(tmp_path / "ignored"),
        TARGET_PICKLE,
        "",
        database=business_sync_database,
        scope=actor.scope,
        partner_id=PARTNER_ID,
        encryption_secret=ENVELOPE,
        secret_id="matrix-import:test",
        secret_version=9,
    )
    alice = store.load_device_keys()["@alice:example.org"]["ALICEDEVICE"]
    assert store.blacklist_device(alice) is True
    assert store.is_device_blacklisted(alice) is True

    replay = await importer.import_manifest(manifest, operator="unit-test-replay")

    assert replay["deduped_sources"] == 1
    assert replay["imported"] == {
        "matrix_accounts": 0,
        "matrix_olm_sessions": 0,
        "matrix_megolm_sessions": 0,
        "matrix_forwarded_chains": 0,
        "matrix_device_keys": 0,
        "matrix_device_key_values": 0,
        "matrix_device_trust_state": 0,
        "matrix_encrypted_rooms": 0,
        "matrix_sync_tokens": 0,
        "matrix_outgoing_key_requests": 0,
    }
    restored_alice = store.load_device_keys()["@alice:example.org"]["ALICEDEVICE"]
    assert store.is_device_blacklisted(restored_alice) is True


async def test_matrix_sqlite_import_rejects_wrong_legacy_pickle_key(
    tmp_path: Path,
    migrated_pg,
    business_actors,
) -> None:
    from deeptutor.persistence.postgres.matrix import MatrixStoreEncryptionError
    from deeptutor.persistence.postgres.offline_import.matrix_sqlite import (
        SQLiteMatrixStoreImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    source = _make_matrix_sqlite_store(tmp_path / "legacy-wrong-key")
    manifest = _snapshot(
        source["db_path"],
        tmp_path / "artifact-wrong-key",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
        source_id="legacy-matrix-wrong-key",
    )

    with pytest.raises(MatrixStoreEncryptionError, match="pickle"):
        await SQLiteMatrixStoreImporter(
            migrated_pg.admin_dsn,
            secret_resolver=_secrets(**{"legacy-pickle": "wrong-legacy-pickle-secret-000000000001"}),
        ).import_manifest(manifest, operator="unit-test")


async def test_matrix_sqlite_import_rejects_changed_snapshot_and_target_device_conflict(
    tmp_path: Path,
    migrated_pg,
    business_actors,
    business_sync_database,
) -> None:
    from deeptutor.persistence.postgres.matrix import PostgresMatrixStore
    from deeptutor.persistence.postgres.offline_import.matrix_sqlite import (
        SQLiteMatrixStoreImporter,
    )

    actor = business_actors.tenants[0].owners[0]
    source = _make_matrix_sqlite_store(tmp_path / "legacy-conflict")
    changed_manifest = _snapshot(
        source["db_path"],
        tmp_path / "artifact-changed",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
        source_id="legacy-matrix-changed",
    )
    changed = _read_json(changed_manifest)
    snapshot_path = Path(changed["sources"][0]["snapshot"]["path"])
    with sqlite3.connect(snapshot_path) as connection:
        connection.execute("CREATE TABLE tampered(id INTEGER)")
        connection.commit()
    with pytest.raises(ValueError, match="source-check failed"):
        await SQLiteMatrixStoreImporter(
            migrated_pg.admin_dsn, secret_resolver=_secrets()
        ).import_manifest(changed_manifest, operator="unit-test")

    conflict_manifest = _snapshot(
        source["db_path"],
        tmp_path / "artifact-conflict",
        tenant_id=actor.tenant_id,
        source_owner="legacy-user",
        target_owner=actor.user_id,
        source_id="legacy-matrix-conflict",
    )
    existing = PostgresMatrixStore(
        USER_ID,
        DEVICE_ID,
        str(tmp_path / "ignored"),
        TARGET_PICKLE,
        "",
        database=business_sync_database,
        scope=actor.scope,
        partner_id=PARTNER_ID,
        encryption_secret=ENVELOPE,
        secret_id="matrix-import:test",
        secret_version=9,
    )
    existing.save_account(OlmAccount())

    with pytest.raises(ValueError, match="target Matrix account already exists"):
        await SQLiteMatrixStoreImporter(
            migrated_pg.admin_dsn, secret_resolver=_secrets()
        ).import_manifest(conflict_manifest, operator="unit-test")
