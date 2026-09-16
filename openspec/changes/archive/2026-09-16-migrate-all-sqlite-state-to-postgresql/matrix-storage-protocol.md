# Matrix nio 0.26.0 storage protocol probe（task 1.23）

## Locked versions and native boundary

Probe environment: repository `.venv` on Python 3.14, after installing `matrix-nio[e2e]==0.26.0`.

| Component | Observed / locked value | Notes |
| --- | --- | --- |
| `matrix-nio` | `0.26.0` | `pyproject.toml`, `requirements/matrix.txt`, `requirements/matrix-e2e.txt` now pin this exact version. |
| E2EE crypto binding | `vodozemac==0.10.0` | `matrix-nio` 0.26.0 uses vodozemac for E2EE; this is explicitly pinned for repeatable adapter work. |
| `python-olm` / `olm` | not installed / not imported | This locked stack does **not** use python-olm/libolm. Older libolm notes are replaced by the vodozemac boundary for 1.24+. |
| Default store class | `nio.store.DefaultStore` | SQLite-backed when used with `store_path`; PG adapter must replace this class. |
| Store protocol version | `MatrixStore.store_version == 2` | Schema freeze for 1.24 must target this protocol only. |

## MatrixStore protocol surface to implement

A PG adapter for 1.24 must provide the `MatrixStore` constructor shape:

```text
(user_id, device_id, store_path, pickle_key='', database_name='')
```

and preserve these methods exactly enough for `AsyncClient.load_store()` and sync/E2EE callbacks:

- account: `load_account`, `save_account`
- Olm one-to-one sessions: `load_sessions`, `save_session`
- Megolm inbound group sessions: `load_inbound_group_sessions`, `save_inbound_group_session`
- device keys/trust: `load_device_keys`, `save_device_keys`, `verify_device`, `unverify_device`, `blacklist_device`, `unblacklist_device`, `ignore_device`, `unignore_device`, `ignore_devices`, `is_device_verified`, `is_device_blacklisted`, `is_device_ignored`
- encrypted rooms: `load_encrypted_rooms`, `save_encrypted_rooms`, `delete_encrypted_room`
- sync cursor: `load_sync_token`, `save_sync_token`
- outgoing room-key requests: `add_outgoing_key_request`, `load_outgoing_key_requests`, `remove_outgoing_key_request`

## Fields observed from nio 0.26.0 SQLite models

These are the fields that must be represented in PG, with tenant / partner / Matrix user / device ownership added by DeepTutor rather than inferred from paths.

| Domain | nio model | Fields |
| --- | --- | --- |
| Account | `Accounts` | `id`, `account`, `user_id`, `device_id`, `shared` |
| Olm session | `OlmSessions` | `session_id`, `creation_time`, `last_usage_date`, `sender_key`, `account`, `session` |
| Megolm inbound session | `MegolmInboundSessions` | `session_id`, `sender_key`, `account`, `fp_key`, `room_id`, `session` |
| Forwarding chain | `ForwardedChains` | `id`, `sender_key`, `session` |
| Device | `DeviceKeys` | `id`, `device_id`, `user_id`, `display_name`, `deleted`, `account` |
| Device key material | `Keys` | `id`, `key_type`, `key`, `device` |
| Trust state | `DeviceTrustState` | `device`, `state` |
| Encrypted rooms | `EncryptedRooms` | `id`, `room_id`, `account` |
| Sync token | `SyncTokens` | `id`, `token`, `account` |
| Outgoing key request | `OutgoingKeyRequests` | `id`, `request_id`, `session_id`, `room_id`, `algorithm`, `account` |

## Encryption and Secret boundaries

- `account`, Olm `session`, and Megolm `session` are serialized encrypted blobs produced through nio/vodozemac pickling with the configured `pickle_key`.
- `AsyncClientConfig.pickle_key` defaults to `DEFAULT_KEY`; DeepTutor PG adapter must reject or override this with a Secret-managed key and key version.
- PG records must not log serialized account/session blobs, access tokens, pickle keys, device keys, or room keys.
- Matrix encrypted media payloads are separate from store records; `decrypt_attachment()` handles per-event file encryption metadata, while attachment bytes remain file/resource payloads, not Matrix store rows.

## Thread and event-loop model measured for 0.26.0

- `AsyncClient.sync_forever()` is async and must be owned by one Matrix client event loop at a time.
- `MatrixStore` methods are synchronous. The current channel calls `client.load_store()` before starting `sync_forever()` and then nio uses the store from sync callbacks; a PG adapter that blocks must therefore run inside a dedicated Matrix worker/loop or bounded synchronous bridge, not on the shared app event loop.
- Sync-token advancement is a store write (`save_sync_token`). For 1.25, DeepTutor must enqueue inbound Matrix events to the runtime and only advance the durable handled cursor after business persistence succeeds; PG failures must stop sync rather than swallowing the error and replaying/losing messages.
- Current `MatrixChannel` still passes `store_path` and catches `load_store()` failure with a warning; this remains a known gap for 1.24–1.26 and is **not** accepted as the final PG-only Matrix implementation.

## Scope for subsequent tasks

This artifact unlocks schema design for 1.24 by fixing the protocol and field set. It does not claim a PG adapter, ordinary Matrix send/receive acceptance, E2EE restart/decryption acceptance, or zero-SQLite runtime acceptance; those remain in tasks 1.24–1.26 and 1.43.

## 2026-09-15 task 1.24 PG adapter freeze

- Added PostgreSQL schema `0010_matrix_store` for nio 0.26 store protocol v2: accounts, Olm sessions, Megolm inbound sessions, forwarded chains, device keys, key values, trust state, encrypted rooms, sync tokens, and outgoing key requests.
- Every Matrix row is keyed by `tenant_id`, `owner_id`, `partner_id`, `matrix_user_id`, and `device_id`; RLS applies tenant + owner policies, while device ownership is represented in the composite primary/foreign keys rather than derived from filesystem paths.
- Added `PostgresMatrixStore` and `postgres_matrix_store_factory()` in `deeptutor.persistence.postgres.matrix`. The adapter implements nio's synchronous store methods but does not create peewee/SQLite state (`database_path` is absent).
- Serialized account/session blobs are first produced with nio/vodozemac `pickle(pickle_key)` and then encrypted with a DeepTutor Secret envelope (`secret_id`, `secret_version`, AES-GCM nonce/ciphertext stored in PG). Empty/default `pickle_key` and missing envelope secrets are rejected.
- Bad envelope secret/version fails before unpickle with a sanitized decrypt error; wrong pickle key with the right envelope secret fails as a sanitized pickle error. Access tokens and raw pickle/envelope secrets are not persisted in these rows.
- Runtime MatrixChannel still requires task 1.25 to instantiate this adapter from a dedicated Matrix worker and to stop swallowing store failures; task 1.24 only freezes the schema and adapter contract.

## 2026-09-15 task 1.25 runtime worker wiring

- `MatrixChannel.start()` now creates a dedicated daemon thread with its own asyncio event loop and initializes `AsyncClient` inside that loop; outbound sends are proxied to the worker loop.
- The nio client is configured with the 1.24 PG store factory, `store_sync_tokens=True`, and `encryption_enabled=True` so `AsyncClient.load_store()` constructs the PG store instead of `DefaultStore`/`SqliteMemoryStore`. The `store_path` value is a non-empty sentinel required by nio and is ignored by the PG store.
- `ChannelManager` now passes trusted `owner_id` from `PartnerConfig` to channel instances; the Matrix PG store scope is derived from the application PG runtime tenant plus that owner, not from filesystem state.
- Matrix callbacks run on the worker loop. Inbound event handoff uses `run_coroutine_threadsafe()` to publish to the runtime loop and awaits that future before returning to nio; nio's sync token write therefore happens only after the runtime handoff commit.
- Sync failures are fail-closed: `_sync_loop()` no longer sleeps and retries all exceptions. The done callback records `setup_state=status:error`, clears `_running`, and leaves restart/reload to the Partner runtime instead of swallowing PG store failures.

## 2026-09-15 task 1.26 controlled homeserver validation

- Added an opt-in controlled-service test using Docker Synapse `ghcr.io/element-hq/synapse:v1.160.0` and synthetic bot/alice users. The test exercises real Matrix HTTP sync/send/login/key APIs; it does not use user homeservers or user data.
- Plain Matrix acceptance now covers Alice → MatrixChannel inbound delivery, durable sync-token restart without replaying `plain-one`, post-restart receipt of `plain-two`, and MatrixChannel → Alice outbound delivery of `bot-plain-reply`.
- E2EE acceptance now covers PG-backed nio/vodozemac clients on both users, encrypted room creation, device-key synchronization, persisted `TrustState.verified` for Alice's `ALICEE2E` device, bot → Alice encrypted text decryption, and Alice → bot encrypted text decryption with `ignore_unverified_devices=False`.
- Restart acceptance reloads Alice's same Matrix device from the same PG store and Secret material, then decrypts historical `encrypted-one` via `room_messages()`. The test does not pass by creating a fresh device identity, disabling E2EE, or relying only on `next_batch`.
- Every DeepTutor/nio client store used by the test asserts absence of `database_path`, confirming the app-side Matrix state is `PostgresMatrixStore`; Synapse's own internal database remains an external controlled service implementation detail.
