from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

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


def _store(database, actor, *, tmp_path: Path, **overrides):
    from deeptutor.persistence.postgres.matrix import PostgresMatrixStore

    user_id = overrides.pop("user_id", "@bot:example.org")
    device_id = overrides.pop("device_id", "DEVICE-A")
    pickle_key = overrides.pop("pickle_key", "matrix-pickle-secret-000000000000000001")
    database_name = overrides.pop("database_name", "ignored-by-pg")
    options = {
        "database": database,
        "scope": actor.scope,
        "partner_id": "ada",
        "encryption_secret": "matrix-store-envelope-secret-000000000001",
        "secret_id": "matrix-store:test",
        "secret_version": 7,
    }
    options.update(overrides)
    return PostgresMatrixStore(
        user_id,
        device_id,
        str(tmp_path),
        pickle_key,
        database_name,
        **options,
    )


async def test_matrix_pg_store_round_trips_full_nio_protocol_without_sqlite(
    business_sync_database, business_actors, migrated_pg, tmp_path
):
    from deeptutor.persistence.postgres.matrix import PostgresMatrixStore

    owner = business_actors.tenants[0].owners[0]
    store = _store(business_sync_database, owner, tmp_path=tmp_path)
    assert isinstance(store, PostgresMatrixStore)
    assert not hasattr(store, "database_path")

    account = OlmAccount()
    account.shared = True
    store.save_account(account)

    loaded_account = store.load_account()
    assert loaded_account is not None
    assert loaded_account.shared is True
    assert loaded_account.identity_keys == account.identity_keys

    peer = OlmAccount()
    peer.generate_one_time_keys(1)
    peer_one_time_key = next(iter(peer.one_time_keys["curve25519"].values()))
    olm_session = Session(
        account.create_outbound_session(peer.identity_keys["curve25519"], peer_one_time_key)
    )
    store.save_session(peer.identity_keys["curve25519"], olm_session)
    assert store.load_sessions().get(peer.identity_keys["curve25519"]).id == olm_session.id

    outbound_group = OutboundGroupSession()
    inbound_group = InboundGroupSession(
        outbound_group.session_key,
        signing_key=account.identity_keys["ed25519"],
        sender_key=account.identity_keys["curve25519"],
        room_id="!room:example.org",
        forwarding_chain=["chain-a", "chain-b"],
    )
    store.save_inbound_group_session(inbound_group)
    loaded_group = store.load_inbound_group_sessions().get(
        "!room:example.org", account.identity_keys["curve25519"], inbound_group.id
    )
    assert loaded_group is not None
    assert loaded_group.forwarding_chain == ["chain-a", "chain-b"]

    alice = OlmDevice(
        "@alice:example.org",
        "ALICEDEVICE",
        {"ed25519": "ed-key", "curve25519": "curve-key"},
        display_name="Alice",
    )
    store.save_device_keys({alice.user_id: {alice.id: alice}})
    assert store.load_device_keys()[alice.user_id][alice.id].curve25519 == "curve-key"
    assert store.verify_device(alice) is True
    assert store.verify_device(alice) is False
    assert store.load_device_keys()[alice.user_id][alice.id].verified is True
    assert store.unverify_device(alice) is True
    assert store.blacklist_device(alice) is True
    assert store.is_device_blacklisted(alice) is True
    assert store.unblacklist_device(alice) is True
    store.ignore_devices([alice])
    assert store.is_device_ignored(alice) is True
    assert store.load_device_keys()[alice.user_id][alice.id].ignored is True

    store.save_encrypted_rooms({"!room:example.org"})
    assert store.load_encrypted_rooms() == {"!room:example.org"}
    store.delete_encrypted_room("!room:example.org")
    assert store.load_encrypted_rooms() == set()

    store.save_sync_token("s12345")
    assert store.load_sync_token() == "s12345"

    request = OutgoingKeyRequest(
        request_id="request-1",
        session_id="session-1",
        room_id="!room:example.org",
        algorithm="m.megolm.v1.aes-sha2",
    )
    store.add_outgoing_key_request(request)
    assert store.load_outgoing_key_requests()["request-1"].room_id == "!room:example.org"
    store.remove_outgoing_key_request(request)
    assert store.load_outgoing_key_requests() == {}

    with psycopg.connect(migrated_pg.admin_dsn) as connection:
        row = connection.execute(
            """
            SELECT secret_id, secret_version, account_ciphertext, account_nonce
              FROM enterprise.matrix_accounts
             WHERE tenant_id=%s AND owner_id=%s AND partner_id='ada'
            """,
            (owner.tenant_id, owner.user_id),
        ).fetchone()
    assert row[0] == "matrix-store:test"
    assert row[1] == 7
    assert len(row[3]) == 12
    assert bytes(row[2]) != account.pickle("matrix-pickle-secret-000000000000000001")


async def test_matrix_pg_store_rejects_default_and_bad_secrets(
    business_sync_database, business_actors, tmp_path
):
    from deeptutor.persistence.postgres.matrix import (
        MatrixStoreEncryptionError,
        PostgresMatrixStore,
    )

    owner = business_actors.tenants[0].owners[0]
    with pytest.raises(ValueError, match="Secret-managed Matrix pickle_key"):
        PostgresMatrixStore(
            "@bot:example.org",
            "DEVICE-A",
            str(tmp_path),
            "DEFAULT_KEY",
            "",
            database=business_sync_database,
            scope=owner.scope,
            partner_id="ada",
            encryption_secret="matrix-store-envelope-secret-000000000001",
        )
    with pytest.raises(ValueError, match="encryption_secret"):
        _store(business_sync_database, owner, tmp_path=tmp_path, encryption_secret="")

    good = _store(business_sync_database, owner, tmp_path=tmp_path)
    good.save_account(OlmAccount())

    wrong_envelope = _store(
        business_sync_database,
        owner,
        tmp_path=tmp_path,
        encryption_secret="matrix-store-envelope-secret-000000000099",
    )
    with pytest.raises(MatrixStoreEncryptionError, match="decrypt"):
        wrong_envelope.load_account()

    wrong_pickle = PostgresMatrixStore(
        "@bot:example.org",
        "DEVICE-A",
        str(tmp_path),
        "matrix-pickle-secret-000000000000000099",
        "",
        database=business_sync_database,
        scope=owner.scope,
        partner_id="ada",
        encryption_secret="matrix-store-envelope-secret-000000000001",
        secret_id="matrix-store:test",
        secret_version=7,
    )
    with pytest.raises(MatrixStoreEncryptionError, match="pickle"):
        wrong_pickle.load_account()


async def test_matrix_pg_store_is_owner_and_device_scoped(
    business_sync_database, business_actors, tmp_path
):
    owner = business_actors.tenants[0].owners[0]
    other_owner = business_actors.tenants[0].owners[1]

    owner_store = _store(business_sync_database, owner, tmp_path=tmp_path)
    owner_store.save_account(OlmAccount())

    other_owner_store = _store(business_sync_database, other_owner, tmp_path=tmp_path)
    assert other_owner_store.load_account() is None

    other_device_store = _store(
        business_sync_database,
        owner,
        tmp_path=tmp_path,
        device_id="DEVICE-B",
    )
    assert other_device_store.load_account() is None
