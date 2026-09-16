from __future__ import annotations

import importlib.metadata as metadata
import inspect

import pytest

nio = pytest.importorskip("nio", reason="Matrix protocol contract requires deeptutor[matrix-e2e]")
store_database = pytest.importorskip("nio.store.database")
pytest.importorskip("vodozemac")


def test_matrix_versions_are_locked_to_the_protocol_probe() -> None:
    assert metadata.version("matrix-nio") == "0.26.0"
    assert metadata.version("vodozemac") == "0.10.0"
    with pytest.raises(metadata.PackageNotFoundError):
        metadata.version("python-olm")


def test_matrix_store_protocol_surface_for_pg_adapter() -> None:
    from nio.store import MatrixStore

    expected_methods = {
        "load_account",
        "save_account",
        "load_sessions",
        "save_session",
        "load_inbound_group_sessions",
        "save_inbound_group_session",
        "load_device_keys",
        "save_device_keys",
        "verify_device",
        "unverify_device",
        "blacklist_device",
        "unblacklist_device",
        "ignore_device",
        "unignore_device",
        "ignore_devices",
        "is_device_verified",
        "is_device_blacklisted",
        "is_device_ignored",
        "load_encrypted_rooms",
        "save_encrypted_rooms",
        "delete_encrypted_room",
        "load_sync_token",
        "save_sync_token",
        "add_outgoing_key_request",
        "load_outgoing_key_requests",
        "remove_outgoing_key_request",
    }

    assert expected_methods.issubset(set(dir(MatrixStore)))
    assert inspect.signature(MatrixStore).parameters.keys() >= {
        "user_id",
        "device_id",
        "store_path",
        "pickle_key",
        "database_name",
    }
    assert MatrixStore.store_version == 2


def test_matrix_sqlite_model_fields_are_fully_accounted_for_before_pg_schema_freeze() -> None:
    expected = {
        "Accounts": ["id", "account", "user_id", "device_id", "shared"],
        "OlmSessions": [
            "session_id",
            "creation_time",
            "last_usage_date",
            "sender_key",
            "account",
            "session",
        ],
        "MegolmInboundSessions": [
            "session_id",
            "sender_key",
            "account",
            "fp_key",
            "room_id",
            "session",
        ],
        "ForwardedChains": ["id", "sender_key", "session"],
        "DeviceKeys": ["id", "device_id", "user_id", "display_name", "deleted", "account"],
        "Keys": ["id", "key_type", "key", "device"],
        "DeviceTrustState": ["device", "state"],
        "EncryptedRooms": ["id", "room_id", "account"],
        "SyncTokens": ["id", "token", "account"],
        "OutgoingKeyRequests": ["id", "request_id", "session_id", "room_id", "algorithm", "account"],
    }

    actual = {
        name: list(getattr(store_database, name)._meta.fields)
        for name in expected
    }
    assert actual == expected


def test_matrix_client_thread_model_requires_single_owner_loop_and_explicit_store_class(tmp_path) -> None:
    from nio import AsyncClient, AsyncClientConfig
    from nio.store import DefaultStore, SqliteMemoryStore

    config = AsyncClientConfig(
        store=DefaultStore,
        encryption_enabled=True,
        store_sync_tokens=True,
        pickle_key="probe-key",
    )
    client = AsyncClient(
        "https://matrix.invalid",
        store_path=str(tmp_path),
        config=config,
    )
    # MatrixChannel assigns these immediately after construction; nio 0.26.0
    # still requires the owning loop to finish that binding before load_store().
    client.user_id = "@bot:matrix.invalid"
    client.device_id = "DEVICEID"

    assert client.config.store is DefaultStore
    assert client.config.store is not SqliteMemoryStore
    assert client.store is None
    client.load_store()
    assert type(client.store).__name__ == "DefaultStore"
    assert client.loaded_sync_token is None
    assert inspect.iscoroutinefunction(client.sync_forever)
