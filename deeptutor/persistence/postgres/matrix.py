"""PostgreSQL-backed Matrix nio 0.26 store.

The nio store protocol is synchronous even when the Matrix client is async.
This adapter therefore targets a dedicated Matrix worker (wired in task 1.25)
and uses the existing ``SyncDatabase.transaction(scope)`` boundary for every
store operation.  It intentionally does not create a ``database_path`` or a
peewee/SQLite database.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
import time
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from nio.crypto import (
    DeviceStore,
    GroupSessionStore,
    InboundGroupSession,
    OlmAccount,
    OlmDevice,
    OutgoingKeyRequest,
    Session,
    SessionStore,
    TrustState,
)
from nio.store import MatrixStore

from deeptutor.persistence.postgres.connection import SyncDatabase
from deeptutor.persistence.postgres.scope import TenantScope

_DEFAULT_PICKLE_KEYS = frozenset({"", "DEFAULT_KEY"})
_VALID_TRUST_STATES = frozenset(state.name for state in TrustState)


class MatrixStoreEncryptionError(RuntimeError):
    """Raised when a Matrix encrypted store row cannot be decrypted/unpickled."""


@dataclass(frozen=True, slots=True)
class MatrixPostgresStoreConfig:
    """Trusted config captured by a nio ``AsyncClientConfig.store`` factory."""

    database: SyncDatabase
    scope: TenantScope
    partner_id: str
    encryption_secret: str
    secret_id: str = "matrix-store"
    secret_version: int = 1
    clock: Callable[[], float] = time.time


def postgres_matrix_store_factory(config: MatrixPostgresStoreConfig):
    """Return a callable with nio's MatrixStore constructor shape.

    ``AsyncClient.load_store()`` calls ``config.store(user, device, path,
    pickle_key, store_name)``.  Passing this factory keeps database handles and
    trusted owner scope out of the serializable Matrix channel config.
    """

    def _build(
        user_id: str,
        device_id: str,
        store_path: str,
        pickle_key: str = "",
        database_name: str = "",
    ) -> "PostgresMatrixStore":
        return PostgresMatrixStore(
            user_id,
            device_id,
            store_path,
            pickle_key,
            database_name,
            database=config.database,
            scope=config.scope,
            partner_id=config.partner_id,
            encryption_secret=config.encryption_secret,
            secret_id=config.secret_id,
            secret_version=config.secret_version,
            clock=config.clock,
        )

    return _build


class PostgresMatrixStore(MatrixStore):
    """nio MatrixStore protocol persisted in owner-scoped PostgreSQL tables."""

    store_version = 2

    def __init__(
        self,
        user_id: str,
        device_id: str,
        store_path: str,
        pickle_key: str = "",
        database_name: str = "",
        *,
        database: SyncDatabase,
        scope: TenantScope,
        partner_id: str,
        encryption_secret: str,
        secret_id: str = "matrix-store",
        secret_version: int = 1,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(database, SyncDatabase):
            raise TypeError("SyncDatabase is required")
        if not isinstance(scope, TenantScope):
            raise TypeError("trusted TenantScope is required")
        self.user_id = _require_text(user_id, "Matrix user_id")
        self.device_id = _require_text(device_id, "Matrix device_id")
        self.store_path = store_path
        self.database_name = database_name
        self.pickle_key = str(pickle_key or "")
        if self.pickle_key in _DEFAULT_PICKLE_KEYS:
            raise ValueError("Secret-managed Matrix pickle_key is required")
        self.db = database
        self.scope = scope
        self.tenant_id = scope.tenant_id
        self.owner_id = scope.user_id
        self.partner_id = _require_text(partner_id, "partner_id")
        self.secret_id = _require_text(secret_id, "secret_id")
        if type(secret_version) is not int or secret_version < 1:
            raise ValueError("secret_version must be a positive integer")
        self.secret_version = secret_version
        self._envelope = _Envelope(
            _require_secret(encryption_secret, "encryption_secret"),
            secret_id=self.secret_id,
            secret_version=self.secret_version,
        )
        self._clock = clock

    # ── low-level helpers ──────────────────────────────────────────────

    def _now_ms(self) -> int:
        return int(round(float(self._clock()) * 1000))

    def _account_values(self) -> tuple[str, str, str, str, str]:
        return (self.tenant_id, self.owner_id, self.partner_id, self.user_id, self.device_id)

    def _run(self, operation):
        with self.db.transaction(self.scope) as connection:
            return operation(connection)

    def _aad(self, domain: str, *parts: object, row: dict[str, Any] | None = None) -> bytes:
        secret_id = str(row["secret_id"]) if row and "secret_id" in row else self.secret_id
        secret_version = (
            int(row["secret_version"]) if row and "secret_version" in row else self.secret_version
        )
        return "|".join(
            [
                "deeptutor",
                "matrix-store",
                str(secret_id),
                str(secret_version),
                self.tenant_id,
                self.owner_id,
                self.partner_id,
                self.user_id,
                self.device_id,
                domain,
                *(str(part) for part in parts),
            ]
        ).encode("utf-8")

    def _encrypt(self, domain: str, payload: bytes, *parts: object) -> tuple[bytes, bytes]:
        return self._envelope.encrypt(payload, self._aad(domain, *parts))

    def _decrypt(
        self,
        domain: str,
        row: dict[str, Any],
        ciphertext_column: str,
        nonce_column: str,
        *parts: object,
    ) -> bytes:
        try:
            return self._envelope.decrypt(
                _as_bytes(row[ciphertext_column]),
                _as_bytes(row[nonce_column]),
                self._aad(domain, *parts, row=row),
                secret_id=str(row["secret_id"]),
                secret_version=int(row["secret_version"]),
            )
        except InvalidTag as exc:
            raise MatrixStoreEncryptionError(
                "Matrix store secret could not decrypt record"
            ) from exc

    def _account_row(self, connection) -> dict[str, Any] | None:
        return connection.execute(
            """
            SELECT shared, account_ciphertext, account_nonce, secret_id, secret_version
              FROM enterprise.matrix_accounts
             WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
               AND matrix_user_id=%s AND device_id=%s
            """,
            self._account_values(),
        ).fetchone()

    def _require_account(self, connection) -> None:
        if self._account_row(connection) is None:
            raise AssertionError("Matrix account must be saved before dependent records")

    # ── account and sessions ───────────────────────────────────────────

    def load_account(self) -> OlmAccount | None:
        def read(connection):
            row = self._account_row(connection)
            if row is None:
                return None
            try:
                account = OlmAccount.from_pickle(
                    self._decrypt("account", row, "account_ciphertext", "account_nonce"),
                    self.pickle_key,
                    bool(row["shared"]),
                )
            except MatrixStoreEncryptionError:
                raise
            except Exception as exc:  # noqa: BLE001 - vodozemac exposes native exceptions
                raise MatrixStoreEncryptionError(
                    "Matrix pickle key could not unpickle account record"
                ) from exc
            if account.upgrade_pickle:
                account.upgrade_pickle = False
                self.save_account(account)
            return account

        return self._run(read)

    def save_account(self, account: OlmAccount) -> None:
        ciphertext, nonce = self._encrypt("account", account.pickle(self.pickle_key))
        now_ms = self._now_ms()

        def write(connection):
            connection.execute(
                """
                INSERT INTO enterprise.matrix_accounts(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    secret_id, secret_version, shared, account_ciphertext,
                    account_nonce, created_at_ms, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, owner_id, partner_id, matrix_user_id, device_id)
                DO UPDATE SET
                    secret_id=excluded.secret_id,
                    secret_version=excluded.secret_version,
                    shared=excluded.shared,
                    account_ciphertext=excluded.account_ciphertext,
                    account_nonce=excluded.account_nonce,
                    updated_at_ms=excluded.updated_at_ms
                """,
                (
                    *self._account_values(),
                    self.secret_id,
                    self.secret_version,
                    bool(account.shared),
                    ciphertext,
                    nonce,
                    now_ms,
                    now_ms,
                ),
            )

        self._run(write)

    def load_sessions(self) -> SessionStore:
        def read(connection):
            store = SessionStore()
            if self._account_row(connection) is None:
                return store
            rows = connection.execute(
                """
                SELECT sender_key, session_id, creation_time, last_usage_date,
                       session_ciphertext, session_nonce, secret_id, secret_version
                  FROM enterprise.matrix_olm_sessions
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                 ORDER BY sender_key, last_usage_date DESC, session_id
                """,
                self._account_values(),
            ).fetchall()
            for row in rows:
                try:
                    session = Session.from_pickle(
                        self._decrypt(
                            "olm-session",
                            row,
                            "session_ciphertext",
                            "session_nonce",
                            row["sender_key"],
                            row["session_id"],
                        ),
                        row["creation_time"],
                        self.pickle_key,
                        use_time=row["last_usage_date"],
                    )
                except MatrixStoreEncryptionError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise MatrixStoreEncryptionError(
                        "Matrix pickle key could not unpickle Olm session record"
                    ) from exc
                store.add(row["sender_key"], session)
                if session.upgrade_pickle:
                    session.upgrade_pickle = False
                    self.save_session(row["sender_key"], session)
            return store

        return self._run(read)

    def save_session(self, curve_key: str, session: Session) -> None:
        curve_key = _require_text(curve_key, "curve_key")
        session_id = _require_text(session.id, "session_id")
        ciphertext, nonce = self._encrypt(
            "olm-session", session.pickle(self.pickle_key), curve_key, session_id
        )
        now_ms = self._now_ms()

        def write(connection):
            self._require_account(connection)
            connection.execute(
                """
                INSERT INTO enterprise.matrix_olm_sessions(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    sender_key, session_id, secret_id, secret_version,
                    creation_time, last_usage_date, session_ciphertext,
                    session_nonce, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    sender_key, session_id
                ) DO UPDATE SET
                    secret_id=excluded.secret_id,
                    secret_version=excluded.secret_version,
                    creation_time=excluded.creation_time,
                    last_usage_date=excluded.last_usage_date,
                    session_ciphertext=excluded.session_ciphertext,
                    session_nonce=excluded.session_nonce,
                    updated_at_ms=excluded.updated_at_ms
                """,
                (
                    *self._account_values(),
                    curve_key,
                    session_id,
                    self.secret_id,
                    self.secret_version,
                    _ensure_datetime(session.creation_time),
                    _ensure_datetime(session.use_time),
                    ciphertext,
                    nonce,
                    now_ms,
                ),
            )

        self._run(write)

    def load_inbound_group_sessions(self) -> GroupSessionStore:
        def read(connection):
            store = GroupSessionStore()
            if self._account_row(connection) is None:
                return store
            rows = connection.execute(
                """
                SELECT room_id, sender_key, session_id, fp_key, session_ciphertext,
                       session_nonce, secret_id, secret_version
                  FROM enterprise.matrix_megolm_inbound_sessions
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                 ORDER BY room_id, sender_key, session_id
                """,
                self._account_values(),
            ).fetchall()
            chain_rows = connection.execute(
                """
                SELECT room_id, sender_key, session_id, chain_sender_key
                  FROM enterprise.matrix_forwarded_chains
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                 ORDER BY room_id, sender_key, session_id, position
                """,
                self._account_values(),
            ).fetchall()
            chains: dict[tuple[str, str, str], list[str]] = {}
            for chain in chain_rows:
                key = (chain["room_id"], chain["sender_key"], chain["session_id"])
                chains.setdefault(key, []).append(chain["chain_sender_key"])
            for row in rows:
                key = (row["room_id"], row["sender_key"], row["session_id"])
                try:
                    session = InboundGroupSession.from_pickle(
                        self._decrypt(
                            "megolm-session",
                            row,
                            "session_ciphertext",
                            "session_nonce",
                            row["room_id"],
                            row["sender_key"],
                            row["session_id"],
                        ),
                        row["fp_key"],
                        row["sender_key"],
                        row["room_id"],
                        self.pickle_key,
                        chains.get(key, []),
                    )
                except MatrixStoreEncryptionError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise MatrixStoreEncryptionError(
                        "Matrix pickle key could not unpickle Megolm session record"
                    ) from exc
                store.add(session)
                if session.upgrade_pickle:
                    session.upgrade_pickle = False
                    self.save_inbound_group_session(session)
            return store

        return self._run(read)

    def save_inbound_group_session(self, session: InboundGroupSession) -> None:
        ciphertext, nonce = self._encrypt(
            "megolm-session",
            session.pickle(self.pickle_key),
            session.room_id,
            session.sender_key,
            session.id,
        )
        now_ms = self._now_ms()

        def write(connection):
            self._require_account(connection)
            connection.execute(
                """
                INSERT INTO enterprise.matrix_megolm_inbound_sessions(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    room_id, sender_key, session_id, fp_key, secret_id,
                    secret_version, session_ciphertext, session_nonce, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    room_id, sender_key, session_id
                ) DO UPDATE SET
                    fp_key=excluded.fp_key,
                    secret_id=excluded.secret_id,
                    secret_version=excluded.secret_version,
                    session_ciphertext=excluded.session_ciphertext,
                    session_nonce=excluded.session_nonce,
                    updated_at_ms=excluded.updated_at_ms
                """,
                (
                    *self._account_values(),
                    _require_text(session.room_id, "room_id"),
                    _require_text(session.sender_key, "sender_key"),
                    _require_text(session.id, "session_id"),
                    _require_text(session.ed25519, "fp_key"),
                    self.secret_id,
                    self.secret_version,
                    ciphertext,
                    nonce,
                    now_ms,
                ),
            )
            connection.execute(
                """
                DELETE FROM enterprise.matrix_forwarded_chains
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                   AND room_id=%s AND sender_key=%s AND session_id=%s
                """,
                (*self._account_values(), session.room_id, session.sender_key, session.id),
            )
            for index, sender_key in enumerate(session.forwarding_chain):
                connection.execute(
                    """
                    INSERT INTO enterprise.matrix_forwarded_chains(
                        tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                        room_id, sender_key, session_id, position, chain_sender_key
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        *self._account_values(),
                        session.room_id,
                        session.sender_key,
                        session.id,
                        index,
                        _require_text(sender_key, "forwarding chain sender_key"),
                    ),
                )

        self._run(write)

    # ── devices and trust ───────────────────────────────────────────────

    def load_device_keys(self) -> DeviceStore:
        def read(connection):
            store = DeviceStore()
            if self._account_row(connection) is None:
                return store
            rows = connection.execute(
                """
                SELECT d.user_id, d.key_device_id, d.display_name, d.deleted,
                       COALESCE(t.state, 'unset') AS trust_state
                  FROM enterprise.matrix_device_keys d
                  LEFT JOIN enterprise.matrix_device_trust_state t
                    ON t.tenant_id=d.tenant_id AND t.owner_id=d.owner_id
                   AND t.partner_id=d.partner_id AND t.matrix_user_id=d.matrix_user_id
                   AND t.device_id=d.device_id AND t.user_id=d.user_id
                   AND t.key_device_id=d.key_device_id
                 WHERE d.tenant_id=%s AND d.owner_id=%s AND d.partner_id=%s
                   AND d.matrix_user_id=%s AND d.device_id=%s
                 ORDER BY d.user_id, d.key_device_id
                """,
                self._account_values(),
            ).fetchall()
            key_rows = connection.execute(
                """
                SELECT user_id, key_device_id, key_type, key_value
                  FROM enterprise.matrix_device_key_values
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                 ORDER BY user_id, key_device_id, key_type
                """,
                self._account_values(),
            ).fetchall()
            key_map: dict[tuple[str, str], dict[str, str]] = {}
            for key_row in key_rows:
                key = (key_row["user_id"], key_row["key_device_id"])
                key_map.setdefault(key, {})[key_row["key_type"]] = key_row["key_value"]
            for row in rows:
                state = _trust_state(str(row["trust_state"]))
                store.add(
                    OlmDevice(
                        row["user_id"],
                        row["key_device_id"],
                        key_map.get((row["user_id"], row["key_device_id"]), {}),
                        display_name=row["display_name"],
                        deleted=bool(row["deleted"]),
                        trust_state=state,
                    )
                )
            return store

        return self._run(read)

    def save_device_keys(self, device_keys) -> None:
        now_ms = self._now_ms()

        def write(connection):
            self._require_account(connection)
            for user_id, devices_dict in device_keys.items():
                for device_id, device in devices_dict.items():
                    self._save_device(connection, user_id, device_id, device, now_ms=now_ms)

        self._run(write)

    def _save_device(self, connection, user_id, device_id, device: OlmDevice, *, now_ms: int):
        user_id = _require_text(user_id, "device user_id")
        device_id = _require_text(device_id, "device_id")
        connection.execute(
            """
            INSERT INTO enterprise.matrix_device_keys(
                tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                user_id, key_device_id, display_name, deleted, updated_at_ms
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (
                tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                user_id, key_device_id
            ) DO UPDATE SET
                display_name=excluded.display_name,
                deleted=excluded.deleted,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                *self._account_values(),
                user_id,
                device_id,
                str(device.display_name or ""),
                bool(device.deleted),
                now_ms,
            ),
        )
        connection.execute(
            """
            DELETE FROM enterprise.matrix_device_key_values
             WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
               AND matrix_user_id=%s AND device_id=%s
               AND user_id=%s AND key_device_id=%s
            """,
            (*self._account_values(), user_id, device_id),
        )
        for key_type, key_value in device.keys.items():
            connection.execute(
                """
                INSERT INTO enterprise.matrix_device_key_values(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    user_id, key_device_id, key_type, key_value
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    *self._account_values(),
                    user_id,
                    device_id,
                    _require_text(key_type, "key_type"),
                    _require_text(key_value, "key_value"),
                ),
            )

    def _device_exists(self, connection, device: OlmDevice) -> bool:
        return (
            connection.execute(
                """
                SELECT 1 FROM enterprise.matrix_device_keys
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                   AND user_id=%s AND key_device_id=%s
                """,
                (*self._account_values(), device.user_id, device.id),
            ).fetchone()
            is not None
        )

    def _set_trust(self, device: OlmDevice, state: TrustState) -> bool:
        now_ms = self._now_ms()

        def write(connection):
            if not self._device_exists(connection, device):
                raise AssertionError("Matrix device keys must be saved before trust state")
            current = connection.execute(
                """
                SELECT state FROM enterprise.matrix_device_trust_state
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                   AND user_id=%s AND key_device_id=%s
                """,
                (*self._account_values(), device.user_id, device.id),
            ).fetchone()
            if current is not None and current["state"] == state.name:
                device.trust_state = state
                return False
            connection.execute(
                """
                INSERT INTO enterprise.matrix_device_trust_state(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    user_id, key_device_id, state, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    user_id, key_device_id
                ) DO UPDATE SET state=excluded.state, updated_at_ms=excluded.updated_at_ms
                """,
                (*self._account_values(), device.user_id, device.id, state.name, now_ms),
            )
            device.trust_state = state
            return True

        return self._run(write)

    def _is_trust(self, device: OlmDevice, state: TrustState) -> bool:
        def read(connection):
            row = connection.execute(
                """
                SELECT state FROM enterprise.matrix_device_trust_state
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                   AND user_id=%s AND key_device_id=%s
                """,
                (*self._account_values(), device.user_id, device.id),
            ).fetchone()
            return row is not None and row["state"] == state.name

        return self._run(read)

    def verify_device(self, device: OlmDevice) -> bool:
        return self._set_trust(device, TrustState.verified)

    def unverify_device(self, device: OlmDevice) -> bool:
        if not self.is_device_verified(device):
            return False
        return self._set_trust(device, TrustState.unset)

    def is_device_verified(self, device: OlmDevice) -> bool:
        return self._is_trust(device, TrustState.verified)

    def blacklist_device(self, device: OlmDevice) -> bool:
        return self._set_trust(device, TrustState.blacklisted)

    def unblacklist_device(self, device: OlmDevice) -> bool:
        if not self.is_device_blacklisted(device):
            return False
        return self._set_trust(device, TrustState.unset)

    def is_device_blacklisted(self, device: OlmDevice) -> bool:
        return self._is_trust(device, TrustState.blacklisted)

    def ignore_device(self, device: OlmDevice) -> bool:
        return self._set_trust(device, TrustState.ignored)

    def unignore_device(self, device: OlmDevice) -> bool:
        if not self.is_device_ignored(device):
            return False
        return self._set_trust(device, TrustState.unset)

    def ignore_devices(self, devices: list[OlmDevice]) -> None:
        for device in devices:
            self._set_trust(device, TrustState.ignored)

    def is_device_ignored(self, device: OlmDevice) -> bool:
        return self._is_trust(device, TrustState.ignored)

    # ── rooms, tokens and outgoing requests ─────────────────────────────

    def load_encrypted_rooms(self):
        def read(connection):
            if self._account_row(connection) is None:
                return set()
            return {
                row["room_id"]
                for row in connection.execute(
                    """
                    SELECT room_id FROM enterprise.matrix_encrypted_rooms
                     WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                       AND matrix_user_id=%s AND device_id=%s
                    """,
                    self._account_values(),
                ).fetchall()
            }

        return self._run(read)

    def save_encrypted_rooms(self, rooms) -> None:
        def write(connection):
            self._require_account(connection)
            for room_id in rooms:
                connection.execute(
                    """
                    INSERT INTO enterprise.matrix_encrypted_rooms(
                        tenant_id, owner_id, partner_id, matrix_user_id, device_id, room_id
                    ) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                    """,
                    (*self._account_values(), _require_text(room_id, "room_id")),
                )

        self._run(write)

    def delete_encrypted_room(self, room: str) -> None:
        def write(connection):
            connection.execute(
                """
                DELETE FROM enterprise.matrix_encrypted_rooms
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s AND room_id=%s
                """,
                (*self._account_values(), room),
            )

        self._run(write)

    def save_sync_token(self, token: str) -> None:
        token = _require_text(token, "sync token")
        now_ms = self._now_ms()

        def write(connection):
            self._require_account(connection)
            connection.execute(
                """
                INSERT INTO enterprise.matrix_sync_tokens(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    token, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, owner_id, partner_id, matrix_user_id, device_id)
                DO UPDATE SET token=excluded.token, updated_at_ms=excluded.updated_at_ms
                """,
                (*self._account_values(), token, now_ms),
            )

        self._run(write)

    def load_sync_token(self) -> str | None:
        def read(connection):
            row = connection.execute(
                """
                SELECT token FROM enterprise.matrix_sync_tokens
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                """,
                self._account_values(),
            ).fetchone()
            return row["token"] if row else None

        return self._run(read)

    def load_outgoing_key_requests(self):
        def read(connection):
            if self._account_row(connection) is None:
                return {}
            rows = connection.execute(
                """
                SELECT request_id, session_id, room_id, algorithm
                  FROM enterprise.matrix_outgoing_key_requests
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                 ORDER BY request_id
                """,
                self._account_values(),
            ).fetchall()
            return {
                row["request_id"]: OutgoingKeyRequest(
                    row["request_id"], row["session_id"], row["room_id"], row["algorithm"]
                )
                for row in rows
            }

        return self._run(read)

    def add_outgoing_key_request(self, key_request: OutgoingKeyRequest) -> None:
        def write(connection):
            self._require_account(connection)
            connection.execute(
                """
                INSERT INTO enterprise.matrix_outgoing_key_requests(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    request_id, session_id, room_id, algorithm
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (
                    *self._account_values(),
                    _require_text(key_request.request_id, "request_id"),
                    _require_text(key_request.session_id, "session_id"),
                    _require_text(key_request.room_id, "room_id"),
                    _require_text(key_request.algorithm, "algorithm"),
                ),
            )

        self._run(write)

    def remove_outgoing_key_request(self, key_request: OutgoingKeyRequest) -> None:
        def write(connection):
            connection.execute(
                """
                DELETE FROM enterprise.matrix_outgoing_key_requests
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s AND request_id=%s
                """,
                (*self._account_values(), key_request.request_id),
            )

        self._run(write)


class _Envelope:
    def __init__(self, secret: str, *, secret_id: str, secret_version: int) -> None:
        self._secret_id = secret_id
        self._secret_version = secret_version
        self._aes = AESGCM(hashlib.sha256(secret.encode("utf-8")).digest())

    def encrypt(self, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        return self._aes.encrypt(nonce, plaintext, aad), nonce

    def decrypt(
        self,
        ciphertext: bytes,
        nonce: bytes,
        aad: bytes,
        *,
        secret_id: str,
        secret_version: int,
    ) -> bytes:
        if secret_id != self._secret_id or secret_version != self._secret_version:
            raise InvalidTag
        return self._aes.decrypt(nonce, ciphertext, aad)


def _require_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text:
        raise ValueError(f"{label} is required")
    return text


def _require_secret(value: object, label: str) -> str:
    text = str(value or "")
    if len(text) < 32 or "\x00" in text:
        raise ValueError(f"{label} must be provided by Secret and be at least 32 characters")
    return text


def _as_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray | memoryview):
        return bytes(value)
    raise TypeError("expected encrypted Matrix store bytes")


def _ensure_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Matrix session timestamp must be a datetime")
    return value


def _trust_state(value: str) -> TrustState:
    if value not in _VALID_TRUST_STATES:
        raise RuntimeError("invalid Matrix device trust state in PostgreSQL")
    return TrustState[value]


__all__ = [
    "MatrixPostgresStoreConfig",
    "MatrixStoreEncryptionError",
    "PostgresMatrixStore",
    "postgres_matrix_store_factory",
]
