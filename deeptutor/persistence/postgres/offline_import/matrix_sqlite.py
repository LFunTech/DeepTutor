"""Matrix nio 0.26 SQLite store 离线导入到 PG Matrix store。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from urllib.request import pathname2url

from nio.crypto import InboundGroupSession, OlmAccount, OutgoingKeyRequest, Session, TrustState
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.matrix import MatrixStoreEncryptionError, _Envelope

from .planner import source_check_manifest
from .stage import MigrationStageRepository

_MATRIX_VERSION = "matrix_nio_sqlite/v0.26"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def _sqlite_uri(path: Path) -> str:
    return f"file:{pathname2url(str(path))}?mode=ro&immutable=1"


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _owner_mappings(manifest: dict[str, Any]) -> dict[str, str]:
    raw = manifest.get("owner_mappings")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    mapping: dict[str, str] = {}
    for item in raw or []:
        if isinstance(item, dict) and item.get("source_owner_id") and item.get("target_owner_id"):
            mapping[str(item["source_owner_id"])] = str(item["target_owner_id"])
    return mapping


def _read_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    orders = {
        "accounts": "ORDER BY id",
        "olmsessions": "ORDER BY sender_key, last_usage_date DESC, session_id",
        "megolminboundsessions": "ORDER BY room_id, sender_key, session_id",
        "forwardedchains": "ORDER BY session_id, id",
        "devicekeys": "ORDER BY user_id, device_id, id",
        "keys": "ORDER BY device_id, key_type",
        "devicetruststate": "ORDER BY device_id",
        "encryptedrooms": "ORDER BY room_id",
        "synctokens": "ORDER BY id",
        "outgoingkeyrequests": "ORDER BY request_id",
        "storeversion": "ORDER BY id",
    }
    with sqlite3.connect(_sqlite_uri(snapshot), uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        rows: dict[str, list[dict[str, Any]]] = {}
        for table, order in orders.items():
            if table not in tables:
                rows[table] = []
                continue
            rows[table] = [
                dict(row)
                for row in connection.execute(
                    f'SELECT * FROM "{table}" {order}'  # nosec B608 - table/order 来自常量
                ).fetchall()
            ]
        return rows


def _count(rows: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(value) for value in rows.values())


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.strptime(str(value), _DATE_FORMAT)


def _as_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray | memoryview):
        return bytes(value)
    raise TypeError("expected Matrix SQLite blob bytes")


def _trust_name(value: object) -> str:
    return TrustState(int(value)).name


async def _verify_target_owner(connection, tenant_id: str, owner_id: str) -> None:
    row = await (
        await connection.execute(
            """
            SELECT disabled
              FROM enterprise.users
             WHERE tenant_id=%s AND id=%s
            """,
            (tenant_id, owner_id),
        )
    ).fetchone()
    if row is None:
        raise PermissionError("target owner mapping does not exist")
    if row["disabled"]:
        raise PermissionError("target owner is disabled")


async def _record_source(
    connection,
    batch_id: str,
    *,
    source: dict[str, Any],
    target_owner: str,
    rows_total: int,
    rows_done: int = 0,
    status: str = "importing",
) -> None:
    await connection.execute(
        """
        INSERT INTO migration_stage.sources(
            batch_id, source_id, source_type, source_version,
            source_owner_id, target_owner_id, fingerprint, manifest,
            rows_total, rows_done, status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
        ON CONFLICT (batch_id, source_id) DO UPDATE SET
            source_type=EXCLUDED.source_type,
            source_version=EXCLUDED.source_version,
            source_owner_id=EXCLUDED.source_owner_id,
            target_owner_id=EXCLUDED.target_owner_id,
            fingerprint=EXCLUDED.fingerprint,
            manifest=EXCLUDED.manifest,
            rows_total=EXCLUDED.rows_total,
            rows_done=EXCLUDED.rows_done,
            status=EXCLUDED.status
        """,
        (
            batch_id,
            str(source["source_id"]),
            str(source.get("source_type") or "sqlite"),
            str(source["source_version"]),
            str(source["source_owner_id"]),
            target_owner,
            str(source["snapshot"]["sha256"]),
            Jsonb(source),
            int(rows_total),
            int(rows_done),
            status,
        ),
    )


class SQLiteMatrixStoreImporter:
    """导入 matrix-nio 0.26 `SqliteStore` 快照并用目标 Secret 重新加密。"""

    def __init__(
        self,
        dsn: str,
        *,
        secret_resolver: Mapping[str, str] | Callable[[str], str],
    ) -> None:
        self._dsn = dsn
        self._secret_resolver = secret_resolver

    def _secret(self, secret_id: str) -> str:
        if callable(self._secret_resolver):
            return str(self._secret_resolver(secret_id))
        return str(self._secret_resolver[secret_id])

    async def import_manifest(self, manifest_path: str | Path, *, operator: str) -> dict[str, Any]:
        manifest_path = Path(manifest_path)
        report = source_check_manifest(manifest_path)
        if not report.ok:
            raise ValueError(f"manifest source-check failed: {report.issues}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tenant_id = str(manifest.get("target", {}).get("tenant_id") or "")
        owners = _owner_mappings(manifest)
        repo = MigrationStageRepository(self._dsn)
        batch_id = await repo.create_batch(
            target_tenant_id=tenant_id,
            manifest_sha256=_manifest_hash(manifest_path),
            manifest=manifest,
            operator=operator,
        )
        batch = str(batch_id)
        await repo.enter_maintenance(batch_id, tenant_id=tenant_id, reason="sqlite-matrix-import")
        imported = self._empty_counts()
        deduped_sources = 0
        try:
            async with await psycopg.AsyncConnection.connect(
                self._dsn, row_factory=dict_row
            ) as connection:
                async with connection.transaction():
                    sources = [source for source in manifest.get("sources") or []]
                    for source in sources:
                        if source.get("source_version") != _MATRIX_VERSION:
                            continue
                        target_owner = owners.get(str(source.get("source_owner_id") or ""))
                        if not target_owner:
                            raise PermissionError("source owner has no target owner mapping")
                        await _verify_target_owner(connection, tenant_id, target_owner)
                    for source in sources:
                        if source.get("source_version") != _MATRIX_VERSION:
                            continue
                        target_owner = owners[str(source["source_owner_id"])]
                        rows = _read_rows(Path(source["snapshot"]["path"]))
                        row_total = _count(rows)
                        await _record_source(
                            connection,
                            batch,
                            source=source,
                            target_owner=target_owner,
                            rows_total=row_total,
                        )
                        if await self._source_already_verified(connection, batch, source, target_owner):
                            deduped_sources += 1
                            await _record_source(
                                connection,
                                batch,
                                source=source,
                                target_owner=target_owner,
                                rows_total=row_total,
                                rows_done=row_total,
                                status="verified",
                            )
                            continue
                        counts = await self._import_source(
                            connection,
                            tenant_id=tenant_id,
                            owner_id=target_owner,
                            source=source,
                            rows=rows,
                        )
                        for key, value in counts.items():
                            imported[key] += value
                        await _record_source(
                            connection,
                            batch,
                            source=source,
                            target_owner=target_owner,
                            rows_total=row_total,
                            rows_done=row_total,
                            status="verified",
                        )
                    await connection.execute(
                        """
                        UPDATE migration_stage.batches
                           SET status='published', updated_at=now()
                         WHERE batch_id=%s
                        """,
                        (batch,),
                    )
        except BaseException as exc:
            await self._mark_failed(batch, exc)
            raise
        return {"batch_id": batch, "imported": imported, "deduped_sources": deduped_sources}

    @staticmethod
    def _empty_counts() -> dict[str, int]:
        return {
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

    async def _mark_failed(self, batch_id: str, exc: BaseException) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn) as connection:
            await connection.execute(
                """
                UPDATE migration_stage.batches
                   SET status='failed', error=%s, updated_at=now()
                 WHERE batch_id=%s AND status <> 'published'
                """,
                (str(exc)[:4000], batch_id),
            )

    async def _source_already_verified(
        self, connection, batch_id: str, source: dict[str, Any], target_owner: str
    ) -> bool:
        row = await (
            await connection.execute(
                """
                SELECT 1
                  FROM migration_stage.sources
                 WHERE source_version=%s
                   AND source_owner_id=%s
                   AND target_owner_id=%s
                   AND fingerprint=%s
                   AND status='verified'
                   AND NOT (batch_id=%s AND source_id=%s)
                 LIMIT 1
                """,
                (
                    str(source["source_version"]),
                    str(source["source_owner_id"]),
                    target_owner,
                    str(source["snapshot"]["sha256"]),
                    batch_id,
                    str(source["source_id"]),
                ),
            )
        ).fetchone()
        return row is not None

    async def _import_source(
        self,
        connection,
        *,
        tenant_id: str,
        owner_id: str,
        source: dict[str, Any],
        rows: dict[str, list[dict[str, Any]]],
    ) -> dict[str, int]:
        cfg = self._matrix_config(source)
        partner_id = cfg["partner_id"]
        user_id = cfg["user_id"]
        device_id = cfg["device_id"]
        secret_id = cfg["secret_id"]
        secret_version = int(cfg["secret_version"])
        legacy_pickle = self._secret(cfg["legacy_pickle_secret_id"])
        target_pickle = self._secret(cfg["target_pickle_secret_id"])
        envelope = _Envelope(
            self._secret(cfg["envelope_secret_id"]),
            secret_id=secret_id,
            secret_version=secret_version,
        )
        account = self._source_account(rows, user_id=user_id, device_id=device_id)
        await self._reject_target_conflict(connection, tenant_id, owner_id, partner_id, user_id, device_id)
        values = (tenant_id, owner_id, partner_id, user_id, device_id)

        counts = self._empty_counts()
        now_ms = 0
        try:
            olm_account = OlmAccount.from_pickle(
                _as_bytes(account["account"]), legacy_pickle, bool(account["shared"])
            )
        except Exception as exc:  # noqa: BLE001 - native crypto errors differ by platform
            raise MatrixStoreEncryptionError(
                "legacy Matrix pickle key could not unpickle account record"
            ) from exc
        account_ciphertext, account_nonce = self._encrypt(
            envelope,
            secret_id,
            secret_version,
            values,
            "account",
            olm_account.pickle(target_pickle),
        )
        await connection.execute(
            """
            INSERT INTO enterprise.matrix_accounts(
                tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                secret_id, secret_version, shared, account_ciphertext,
                account_nonce, created_at_ms, updated_at_ms
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (*values, secret_id, secret_version, bool(account["shared"]), account_ciphertext, account_nonce, now_ms, now_ms),
        )
        counts["matrix_accounts"] = 1

        for row in self._account_rows(rows["olmsessions"], account["id"]):
            try:
                session = Session.from_pickle(
                    _as_bytes(row["session"]),
                    _parse_datetime(row["creation_time"]),
                    legacy_pickle,
                    use_time=_parse_datetime(row["last_usage_date"]),
                )
            except Exception as exc:  # noqa: BLE001
                raise MatrixStoreEncryptionError(
                    "legacy Matrix pickle key could not unpickle Olm session record"
                ) from exc
            ciphertext, nonce = self._encrypt(
                envelope,
                secret_id,
                secret_version,
                values,
                "olm-session",
                session.pickle(target_pickle),
                row["sender_key"],
                row["session_id"],
            )
            await connection.execute(
                """
                INSERT INTO enterprise.matrix_olm_sessions(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    sender_key, session_id, secret_id, secret_version,
                    creation_time, last_usage_date, session_ciphertext,
                    session_nonce, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    *values,
                    str(row["sender_key"]),
                    str(row["session_id"]),
                    secret_id,
                    secret_version,
                    _parse_datetime(row["creation_time"]),
                    _parse_datetime(row["last_usage_date"]),
                    ciphertext,
                    nonce,
                    now_ms,
                ),
            )
            counts["matrix_olm_sessions"] += 1

        chains_by_session: dict[str, list[str]] = {}
        for chain in rows["forwardedchains"]:
            chains_by_session.setdefault(str(chain["session_id"]), []).append(str(chain["sender_key"]))
        for row in self._account_rows(rows["megolminboundsessions"], account["id"]):
            chain = chains_by_session.get(str(row["session_id"]), [])
            try:
                session = InboundGroupSession.from_pickle(
                    _as_bytes(row["session"]),
                    str(row["fp_key"]),
                    str(row["sender_key"]),
                    str(row["room_id"]),
                    legacy_pickle,
                    chain,
                )
            except Exception as exc:  # noqa: BLE001
                raise MatrixStoreEncryptionError(
                    "legacy Matrix pickle key could not unpickle Megolm session record"
                ) from exc
            ciphertext, nonce = self._encrypt(
                envelope,
                secret_id,
                secret_version,
                values,
                "megolm-session",
                session.pickle(target_pickle),
                row["room_id"],
                row["sender_key"],
                row["session_id"],
            )
            await connection.execute(
                """
                INSERT INTO enterprise.matrix_megolm_inbound_sessions(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    room_id, sender_key, session_id, fp_key, secret_id,
                    secret_version, session_ciphertext, session_nonce, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    *values,
                    str(row["room_id"]),
                    str(row["sender_key"]),
                    str(row["session_id"]),
                    str(row["fp_key"]),
                    secret_id,
                    secret_version,
                    ciphertext,
                    nonce,
                    now_ms,
                ),
            )
            counts["matrix_megolm_sessions"] += 1
            for index, sender_key in enumerate(chain):
                await connection.execute(
                    """
                    INSERT INTO enterprise.matrix_forwarded_chains(
                        tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                        room_id, sender_key, session_id, position, chain_sender_key
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (*values, row["room_id"], row["sender_key"], row["session_id"], index, sender_key),
                )
                counts["matrix_forwarded_chains"] += 1

        device_identity: dict[int, tuple[str, str]] = {}
        keys_by_device: dict[int, dict[str, str]] = {}
        for key in rows["keys"]:
            keys_by_device.setdefault(int(key["device_id"]), {})[str(key["key_type"])] = str(key["key"])
        for row in self._account_rows(rows["devicekeys"], account["id"]):
            source_device_pk = int(row["id"])
            key_device_id = str(row["device_id"])
            key_user_id = str(row["user_id"])
            device_identity[source_device_pk] = (key_user_id, key_device_id)
            await connection.execute(
                """
                INSERT INTO enterprise.matrix_device_keys(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    user_id, key_device_id, display_name, deleted, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    *values,
                    key_user_id,
                    key_device_id,
                    str(row.get("display_name") or ""),
                    bool(row.get("deleted")),
                    now_ms,
                ),
            )
            counts["matrix_device_keys"] += 1
            for key_type, key_value in keys_by_device.get(source_device_pk, {}).items():
                await connection.execute(
                    """
                    INSERT INTO enterprise.matrix_device_key_values(
                        tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                        user_id, key_device_id, key_type, key_value
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (*values, key_user_id, key_device_id, key_type, key_value),
                )
                counts["matrix_device_key_values"] += 1

        for row in rows["devicetruststate"]:
            identity = device_identity.get(int(row["device_id"]))
            if identity is None:
                continue
            key_user_id, key_device_id = identity
            await connection.execute(
                """
                INSERT INTO enterprise.matrix_device_trust_state(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    user_id, key_device_id, state, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (*values, key_user_id, key_device_id, _trust_name(row["state"]), now_ms),
            )
            counts["matrix_device_trust_state"] += 1

        for row in self._account_rows(rows["encryptedrooms"], account["id"]):
            await connection.execute(
                """
                INSERT INTO enterprise.matrix_encrypted_rooms(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id, room_id
                ) VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (*values, str(row["room_id"])),
            )
            counts["matrix_encrypted_rooms"] += 1

        token_rows = self._account_rows(rows["synctokens"], account["id"])
        for row in token_rows[:1]:
            await connection.execute(
                """
                INSERT INTO enterprise.matrix_sync_tokens(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id, token, updated_at_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (*values, str(row["token"]), now_ms),
            )
            counts["matrix_sync_tokens"] += 1

        for row in self._account_rows(rows["outgoingkeyrequests"], account["id"]):
            request = OutgoingKeyRequest(
                str(row["request_id"]),
                str(row["session_id"]),
                str(row["room_id"]),
                str(row["algorithm"]),
            )
            await connection.execute(
                """
                INSERT INTO enterprise.matrix_outgoing_key_requests(
                    tenant_id, owner_id, partner_id, matrix_user_id, device_id,
                    request_id, session_id, room_id, algorithm
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (*values, request.request_id, request.session_id, request.room_id, request.algorithm),
            )
            counts["matrix_outgoing_key_requests"] += 1
        return counts

    @staticmethod
    def _matrix_config(source: dict[str, Any]) -> dict[str, Any]:
        config = source.get("matrix")
        if not isinstance(config, dict):
            raise ValueError("matrix source requires source.matrix metadata")
        required = (
            "partner_id",
            "user_id",
            "device_id",
            "legacy_pickle_secret_id",
            "target_pickle_secret_id",
            "envelope_secret_id",
            "secret_id",
            "secret_version",
        )
        missing = [key for key in required if not str(config.get(key) or "").strip()]
        if missing:
            raise ValueError(f"matrix source metadata missing: {', '.join(missing)}")
        return {key: config[key] for key in required}

    @staticmethod
    def _source_account(
        rows: dict[str, list[dict[str, Any]]], *, user_id: str, device_id: str
    ) -> dict[str, Any]:
        matches = [
            row
            for row in rows["accounts"]
            if str(row.get("user_id")) == user_id and str(row.get("device_id")) == device_id
        ]
        if len(matches) != 1:
            raise ValueError("matrix source must contain exactly one configured account")
        return matches[0]

    @staticmethod
    def _account_rows(rows: Iterable[dict[str, Any]], account_id: Any) -> list[dict[str, Any]]:
        return [row for row in rows if str(row.get("account_id")) == str(account_id)]

    @staticmethod
    def _encrypt(
        envelope: _Envelope,
        secret_id: str,
        secret_version: int,
        values: tuple[str, str, str, str, str],
        domain: str,
        payload: bytes,
        *parts: object,
    ) -> tuple[bytes, bytes]:
        aad = "|".join(
            [
                "deeptutor",
                "matrix-store",
                secret_id,
                str(secret_version),
                *values,
                domain,
                *(str(part) for part in parts),
            ]
        ).encode("utf-8")
        return envelope.encrypt(payload, aad)

    @staticmethod
    async def _reject_target_conflict(
        connection,
        tenant_id: str,
        owner_id: str,
        partner_id: str,
        user_id: str,
        device_id: str,
    ) -> None:
        row = await (
            await connection.execute(
                """
                SELECT 1
                  FROM enterprise.matrix_accounts
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                 LIMIT 1
                """,
                (tenant_id, owner_id, partner_id, user_id, device_id),
            )
        ).fetchone()
        if row is not None:
            raise ValueError("target Matrix account already exists")


__all__ = ["SQLiteMatrixStoreImporter"]
