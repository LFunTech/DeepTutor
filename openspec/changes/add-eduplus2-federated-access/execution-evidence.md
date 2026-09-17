# Execution Evidence — add-eduplus2-federated-access

Date: 2026-09-16
Executor: Codex

## Implemented local slice

This execution delivered the first local, test-backed slice for EduPlus2 federated access while preserving upstream mergeability:

- Added an extension-owned `eduplus2` PostgreSQL schema with its own `schema_history` and migration runner integration.
  - Tables: `provider_clients`, `external_client_registrations`, `identity_bindings`, `resolve_cache`, `audit_events`.
  - Tenant RLS is enabled and forced on extension tables.
  - `provider_clients` stores `secret_ref` and fingerprint only; no plaintext client secret columns are introduced.
- Added `EduPlus2AccessService` in `extensions/enterprise/src/deeptutor_enterprise/eduplus2/`.
  - TMS client registration uses a resolver result as the authority and rejects mismatched external tenants.
  - Active `client_id` and active `(provider, external_tenant_id, external_app_id)` duplicates are rejected.
  - EduPlus2 user JWT exchange validates `iss/exp/iat/tid/eui/sub/azp`, uses `azp` as the client id, checks active registration and resolve status, creates an internal identity binding, and issues a short DeepTutor `dt_token`.
  - Audit events record request/client/app/tenant/user/session/result/reason and token hash/kid summaries without raw JWT, `dt_token`, signing key, client secret, or request body.
- Added `/api/v1/auth/eduplus2/exchange` to the enterprise ASGI app as an explicit anonymous exchange endpoint protected by existing Origin handling and sanitized errors.
- Added a small generic core seam: `IdentityService._issue_session(..., extra_claims=..., token_seconds=...)`, enabling provider-specific short-lived session claims without hard-coding EduPlus2 into core runtime paths.
- Preserved existing enterprise local identity tests and migration failure semantics by keeping the enterprise `MigrationRunner` as a `CoreMigrationRunner` subclass and adding extension migrations separately.

## Verification run

```bash
./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 4 passed

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_identity.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 18 passed

./.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/eduplus2 \
  extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py \
  extensions/enterprise/src/deeptutor_enterprise/api/application.py \
  extensions/enterprise/src/deeptutor_enterprise/bootstrap.py \
  deeptutor/persistence/postgres/identity/service.py \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_persistence.py
# All checks passed

openspec validate add-eduplus2-federated-access --strict
# Change 'add-eduplus2-federated-access' is valid
```

## Still not production-complete

The following proposal gates remain intentionally incomplete and must not be claimed as delivered:

- Real EduPlus2 test tenant/user/app parameters, Handoff/OIDC callback, JWKS discovery/cache, profile API, permission API, and real `POST /api/v1/open/oauth-clients/resolve` confirmation are not available in this repository execution.
- The resolver used by local tests is `StaticEduPlus2Resolver`; it is a deterministic contract test double only and is not a production fallback.
- OMS platform roles/capabilities (`platform_admin`, `platform_operator`, `platform_auditor`) are not yet represented in the existing core role model; OMS write/read APIs therefore still fail closed.
- Multi-tenant third-party exchange across more than the current fixed enterprise tenant requires the planned dynamic tenant auth/session/provider seam. The local slice verifies tenant isolation rules within the fixed-tenant enterprise runtime only.
- WebSocket `auth_expiring` / `auth_refresh`, reconnect resume with refreshed token, revocation propagation across live WS commands, rate limiting, replay/nonce protection, and real long-dialogue tests are not yet implemented.
- TMS/OMS frontend entries, management pages, audit export UI, and real EduPlus2 smoke are not implemented.
- OpenSpec task checkboxes remain unchecked because each task describes a full production-grade requirement; this evidence records a verified partial slice only.

## Scope resync — 2026-09-17

The OpenSpec proposal/design/tasks/spec were resynchronized to B1-lite after confirming that TMS and OMS are not yet implemented and should not block the third-party exchange path.

New B1-lite scope:

- API-only `POST /api/v1/auth/eduplus2/exchange`.
- Real OIDC/JWKS user JWT verification.
- Real M2M resolve client for `POST /api/v1/open/oauth-clients/resolve`.
- Controlled allowlist/pre-registration or allowlist-gated auto-upsert.
- Short `dt_token` without DeepTutor refresh token.
- Existing owner/resource guard integration and minimal redacted audit.

Deferred out of this change:

- `/tms` and `/oms` pages/routes/API, Handoff/OIDC callback, profile/permission API integration, platform roles, online client management, audit export UI, WS `auth_expiring/auth_refresh`, and full real-time revocation propagation.

## B1-lite implementation slice — 2026-09-17

Scope implemented in this slice:

- Added `deeptutor_enterprise.eduplus2.client`:
  - `EduPlus2OidcJwtVerifier` loads OIDC discovery/JWKS, validates issuer, `kid`, algorithm, signature, `exp/iat/nbf`, and required `tid/eui/sub/azp` claims.
  - `EduPlus2ResolveClient` obtains M2M `client_credentials` tokens, caches them until a safe refresh window, calls `POST /api/v1/open/oauth-clients/resolve`, and normalizes nested EduPlus2 responses without logging tokens or secrets.
  - `parse_allowed_clients` supports JSON or compact env allowlist entries.
- Wired Enterprise runtime env configuration:
  - `DT_EDUPLUS2_DISCOVERY_URL`, `DT_EDUPLUS2_OIDC_ISSUER`, `DT_EDUPLUS2_JWKS_URI`, `DT_EDUPLUS2_TOKEN_ENDPOINT`, `DT_EDUPLUS2_RESOLVE_URL`, `DT_EDUPLUS2_CLIENT_ID`, `DT_EDUPLUS2_CLIENT_SECRET_REF`, `DT_EDUPLUS2_ALLOWED_CLIENTS`, `DT_EDUPLUS2_DT_TOKEN_TTL_SECONDS`.
  - Missing EduPlus2 provider config still fails closed.
- Added B1-lite allowlist-gated auto-upsert:
  - A client can be auto-registered only when allowlist expected tenant/app matches the real resolve result.
  - Active `client_id` and active `(provider, external_tenant_id, external_app_id)` uniqueness remain enforced.
  - Resolve results are cached with a short TTL; negative/inactive paths fail closed.
- Tightened exchange response and API errors:
  - Exchange responses no longer include `eduplus2_token`, raw claims, refresh tokens, or secrets.
  - API maps missing/invalid JWT to 401, unregistered/inactive client to 403, and tenant mismatch to 409.
- Added an EduPlus2 `dt_token` owner-guard integration test: two users in the same EduPlus2 tenant cannot read each other's private session solely by tenant membership.
- Added gated real smoke test `extensions/enterprise/tests/test_eduplus2_real_smoke.py`:
  - Default: skipped unless `DT_EDUPLUS2_REAL_SMOKE=1`.
  - Real environment verified: discovery/JWKS, M2M token, resolve success, unknown client negative, wrong-tenant negative.
  - Real user-JWT exchange smoke remains conditional on receiving an unexpired EduPlus2 user JWT.

Secret-handling note:

- During the first real smoke failure, pytest traceback exposed the Basic auth tuple from an intermediate helper frame. The client was immediately refactored so subsequent token/resolve failures redact request payload/token-bearing locals. The test client secret used for that smoke should be rotated before any shared or production use.

Verification run after this slice:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 16 passed, 1 skipped

# With .secrets sourced and DT_EDUPLUS2_REAL_SMOKE=1:
./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_real_smoke.py -q
# 1 passed

./.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/eduplus2 \
  extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py \
  extensions/enterprise/src/deeptutor_enterprise/api/application.py \
  extensions/enterprise/src/deeptutor_enterprise/bootstrap.py \
  deeptutor/persistence/postgres/identity/service.py \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_persistence.py \
  extensions/enterprise/tests/test_application.py
# All checks passed

openspec validate add-eduplus2-federated-access --strict
# Change 'add-eduplus2-federated-access' is valid
```

Remaining B1-lite blockers / intentionally unchecked tasks:

- No unexpired EduPlus2 user JWT has been provided for a real JWT exchange smoke; current real smoke stops at discovery/JWKS/token/resolve.
- Concurrent first-exchange upsert has not been stress-tested.
- Rate limiting and replay protection are not yet implemented.
- Full authz-denied audit integration and broad log leakage scan are not yet complete.
- Real-time revocation propagation, WS transparent refresh, TMS/OMS pages/APIs, Handoff callback, profile/permission API, and audit export remain deferred by proposal scope.

Additional verification:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_concurrent_first_exchange_upserts_registration_and_binding_once \
  -q
# 1 passed
```

This covers concurrent first exchange for the same allowlisted client and same external user: one active registration, one identity binding, same internal user id, and shared client registration id.

Additional JWT negative verification:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_exchange_rejects_invalid_jwt_and_inactive_registration \
  -q
# 1 passed
```

Covered tampered JWT, wrong issuer, expired JWT, future `iat`, and suspended local registration.

Final verification for this continuation:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 19 passed, 1 skipped

# With .secrets sourced and DT_EDUPLUS2_REAL_SMOKE=1:
./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_real_smoke.py -q
# 1 passed

./.venv/bin/python -m ruff check <touched eduplus2/enterprise files and tests>
# All checks passed

openspec validate add-eduplus2-federated-access --strict
# Change 'add-eduplus2-federated-access' is valid
```

Additional replay/rate-limit verification:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_exchange_rejects_token_replay_and_rate_limit \
  -q
# 1 passed
```

This covers duplicate EduPlus2 user JWT replay rejection within the `dt_token` TTL window and per-client/user exchange rate limiting. API mapping now returns 429 for rate-limited exchange, 409 for tenant mismatch, 403 for unregistered/inactive clients, and 401 for missing/invalid JWT.

Additional authz-denied audit verification:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_eduplus2_dt_token_uses_existing_owner_guard \
  -q
# 1 passed
```

This verifies that an EduPlus2-issued `dt_token` still uses existing owner/resource guard and that an owner-guard denial writes a redacted `authz.denied` audit event containing client/app/tenant/user/session/status/path metadata without raw tokens or private content.

Additional leakage-scan verification:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_resolve_client_error_messages_redact_m2m_secret_and_token \
  -q
# 1 passed

# Local touched-file scan with .secrets sourced, without printing secret values:
# No .secrets token/secret values found in touched source/docs.
```

This supplements existing assertions that exchange audit/API responses do not contain raw EduPlus2 JWTs, `dt_token`, signing keys, Bearer values, M2M access tokens, or client secrets.

Final verification after replay/rate-limit/authz-audit/leakage-scan additions:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 21 passed, 1 skipped

# With .secrets sourced and DT_EDUPLUS2_REAL_SMOKE=1:
./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_real_smoke.py -q
# 1 passed

./.venv/bin/python -m ruff check <touched eduplus2/enterprise files and tests>
# All checks passed

openspec validate add-eduplus2-federated-access --strict
# Change 'add-eduplus2-federated-access' is valid
```

Current OpenSpec task progress: 27/28 complete. The only remaining unchecked task is 0.1 because an unexpired EduPlus2 test user JWT / test user source has not been provided, so real user-JWT exchange smoke cannot be honestly claimed.

## Scope resync — include profile/permission, WS refresh, revocation, audit export UI

Date: 2026-09-17

The proposal was resynchronized after user clarification: TMS and OMS remain deferred, but the following capabilities are now in-scope for this change:

- EduPlus2 profile API integration and profile snapshot validation.
- EduPlus2 permission API integration and ordinary capability boundary calculation.
- WS token refresh / re-auth protocol for long-running conversations.
- Real-time revocation propagation via webhook/event or short-TTL polling fallback.
- Minimal audit query/export UI that does not depend on `/tms` or `/oms`.

This rescope changes OpenSpec task progress from near-complete exchange-only B1-lite to a broader no-TMS/OMS federated access closure. Existing exchange implementation evidence remains valid, but new tasks are intentionally unchecked until implemented and verified.

## Profile/permission client and snapshot slice — 2026-09-17

Scope implemented in this slice:

- Added EduPlus2 profile and permission M2M clients in `deeptutor_enterprise.eduplus2.client`.
  - Clients use server-side `client_credentials` tokens, timeout-bounded HTTP calls, normalized error messages, and no secret/token echo in responses or persisted snapshots.
  - Profile normalization keeps only `external_tenant_id`, `external_user_id`, `external_subject`, `external_identity_type`, `display_name`, `status`, and `version`; raw profile fields such as phone/email are not persisted by the snapshot path.
  - Permission normalization records `allowed`, `reason`, `allowed_usages`, `scopes`, `version`, and `expires_at` for the resolved tenant/user/client/app tuple.
- Added extension migration `0002_profile_permission_snapshots.sql`.
  - New tables: `eduplus2.profile_snapshots`, `eduplus2.permission_snapshots`.
  - Both tables are tenant-scoped with forced RLS and app-role grants; migration verification now includes them in the extension schema drift check.
- Wired optional runtime env configuration for `DT_EDUPLUS2_PROFILE_URL` and `DT_EDUPLUS2_PERMISSION_URL`.
- Extended `EduPlus2AccessService.exchange_user_jwt` for configured profile/permission clients.
  - Exchange fail-closes on profile mismatch/inactive/unavailable and permission denied/unavailable.
  - Success persists profile/permission snapshots and writes `profile.fetch` / `permission.check` audit events.
  - The issued `dt_token` only carries ordinary DeepTutor usages; TMS/OMS/ops/platform usages returned by EduPlus2 are not granted in token claims.

Verification run:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_profile_client_uses_m2m_token_and_normalizes_minimal_snapshot \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_permission_client_uses_m2m_token_and_normalizes_allowed_usages \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_exchange_checks_profile_permission_and_persists_snapshots \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_exchange_denies_permission_api_denied_result \
  -q
# 4 passed

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  -q
# 18 passed

./.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/eduplus2 \
  extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py \
  extensions/enterprise/src/deeptutor_enterprise/bootstrap.py \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_persistence.py
# All checks passed
```

Still incomplete after this slice:

- Profile/permission checks are implemented for exchange when clients are configured; WS refresh is not implemented yet, so tasks that explicitly require exchange **and refresh** remain unchecked.
- Permission unavailable/version-expired and refresh negative paths still need dedicated tests.
- Real EduPlus2 profile/permission endpoint URLs/contracts/test user are still unconfirmed, so real smoke has not been extended beyond discovery/JWKS/token/resolve.
- Revocation propagation, WS refresh, audit query/export API, and audit export UI remain pending.

Supplemental regression after profile/permission slice:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 25 passed, 1 skipped
```

## WS refresh protocol slice — 2026-09-17

Scope implemented in this slice:

- Added generic WebSocket auth protocol models in core:
  - client command: `auth_refresh` with `dt_token` or `eduplus2_jwt` proof;
  - server events: `auth_expiring`, `auth_ack`, `auth_revoked`.
- Updated the core unified WebSocket router with an upstream-neutral auth-provider refresh seam.
  - `auth_refresh` is handled before revalidating an expired old token, allowing clients to refresh a long-lived WS connection.
  - Refresh success emits `auth_ack`; refresh rejection emits `auth_revoked` and closes the socket with policy violation.
  - Non-refresh commands still revalidate before execution/send.
- Updated enterprise `SocketAuthentication`.
  - Stores the current WS token/identity on the connection state.
  - Accepts a new `dt_token` only when tenant/user/role and EduPlus2 client/app/tenant/user claims match the existing connection.
  - Accepts a fresh `eduplus2_jwt` by routing through `enterprise.eduplus2.exchange_user_jwt`, thereby rechecking JWT, registration, resolve, and configured profile/permission clients before updating the connection token.
  - Rejects user-switch or scope-expanding refresh attempts.

Verification run:

```bash
./.venv/bin/python -m pytest tests/api/test_unified_ws_protocol.py -q
# 4 passed, 1 warning

./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 18 passed

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 8 passed, 1 skipped

./.venv/bin/python -m ruff check <WS/core/enterprise EduPlus2 touched files and tests>
# All checks passed
```

Still incomplete after this slice:

- `auth_expiring` is defined as a wire event but proactive server scheduling before expiry still needs a timer/deadline policy if required by clients.
- Reconnect with a new `dt_token` plus `resume_from turn_id + after_seq` still needs an end-to-end enterprise test.
- Refresh audit event `token.refresh` and revocation-driven `auth_revoked` are not yet implemented.

## Profile/permission fail-closed negative expansion — 2026-09-17

Scope implemented in this slice:

- Added exchange negative coverage for profile unavailable, permission unavailable, and expired permission versions.
- Tightened permission normalization so `expires_at` in the past fails closed with `PermissionError("permission expired")`.
- Existing profile mismatch/disabled and permission denied/revoked tests remain covered in the expanded EduPlus2 test matrix.

Verification run:

```bash
./.venv/bin/python -m pytest tests/api/test_unified_ws_protocol.py -q
# 4 passed, 1 warning

./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 19 passed

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 8 passed, 1 skipped

./.venv/bin/python -m ruff check <WS/core/enterprise EduPlus2 touched files and tests>
# All checks passed
```

## Revocation propagation slice — 2026-09-17

Scope implemented in this slice:

- Added extension migration `0003_revocation_state.sql`.
  - New tables: `eduplus2.revocation_events`, `eduplus2.revocation_state`.
  - Both are tenant-scoped with forced RLS and app-role grants; migration verification now includes them in extension schema drift checks.
- Added `EduPlus2AccessService.apply_revocation_event`.
  - Supports user/client/app/tenant/subscription/permission event families.
  - Uses `event_id` as the replay/idempotency key; duplicate events return `duplicate` without creating a second event row.
  - Updates active revocation state, invalidates matching resolve cache, marks matching permission snapshots denied, and writes `revocation.apply` audit.
- Added `ensure_token_allowed` checks for issued EduPlus2 `dt_token`s.
  - New exchange fails closed when matching revocation state exists.
  - Existing token checks fail closed after revocation.
  - Permission snapshots with `permission_version` are rechecked for allowed/expiry/usage.
- Added signed webhook endpoint `POST /api/v1/auth/eduplus2/revocations`.
  - Requires `X-EduPlus2-Timestamp` within a 5-minute window and `X-EduPlus2-Signature: sha256=<hmac>` over `timestamp.body`.
  - Missing/bad/stale signatures are rejected without applying state.
- Wired EduPlus2 token checks into HTTP middleware, WS revalidate/refresh, and SDK context entry while avoiding EduPlus2 provider instantiation for ordinary local tokens.

Verification run:

```bash
./.venv/bin/python -m pytest tests/api/test_unified_ws_protocol.py -q
# 4 passed, 1 warning

./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 21 passed

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 8 passed, 1 skipped

./.venv/bin/python -m ruff check <WS/core/enterprise EduPlus2 touched files and tests>
# All checks passed
```

Still incomplete after this slice:

- Active WS `auth_revoked` end-to-end notification/close after an external revocation still needs a dedicated socket test and, if clients require proactive notification rather than next-command close, a connection registry/broadcast hook.
- Short-TTL polling fallback and recovery/reconciliation tests for out-of-order or partially failed revocation events remain pending.
- Audit export UI/API/jobs are still not implemented.

## Audit query/export API and minimal UI slice — 2026-09-17

Scope implemented in this slice:

- Added extension migration `0004_audit_export_jobs.sql`.
  - New table: `eduplus2.audit_export_jobs` with format/status/filter snapshot/row count/file ref/content preview metadata/retention expiry.
  - Forced tenant RLS and app-role grants are included in extension schema verification.
- Added audit query and synchronous export support in `EduPlus2AccessService`.
  - Query supports tenant-scoped filters for event kind, client/app/user ids, result, request id and bounded limit.
  - Export supports JSONL/CSV generated only from already-redacted `audit_events` rows.
  - Export creates a completed job with `db://eduplus2/audit-export/<job>.<format>` file ref and writes `audit.export` audit.
- Added tenant-admin guarded APIs:
  - `GET /api/v1/enterprise/audit/eduplus2/events`
  - `POST /api/v1/enterprise/audit/eduplus2/exports`
  - ordinary EduPlus2 user tokens receive 403.
- Added minimal independent UI at `/enterprise/audit/eduplus2`.
  - Supports filter input, query, JSONL/CSV export, status/file-ref display, preview, and error display.
  - Does not use `/tms` or `/oms`, and does not show raw token/client secret/full profile.
- Added `token.refresh` persistent audit on WS refresh success so profile/permission/refresh/revocation/audit-export audit families are represented.

Verification run:

```bash
./.venv/bin/python -m pytest tests/api/test_unified_ws_protocol.py -q
# 4 passed, 1 warning

./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 22 passed

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 8 passed, 1 skipped

./.venv/bin/python -m ruff check <WS/core/enterprise EduPlus2 touched files and tests>
# All checks passed

cd web && npm run typecheck
# passed

cd web && npm exec -- eslint app/enterprise/audit/eduplus2/page.tsx
# 0 errors, 14 i18n literal-text warnings
```

Still incomplete after this slice:

- UI i18n extraction is not done; the page currently follows the repository lint policy as warnings-only for literal UI text.
- Export storage uses a bounded DB-backed `db://` file ref in the extension table, not an external S3/ObjectStore artifact; production may still choose to wire this to enterprise ObjectStore before rollout.
- Dedicated audit export E2E browser test is not added.

## Permission snapshot recheck slice — 2026-09-17

Scope implemented/verified in this slice:

- Verified that EduPlus2 `dt_token`s carrying a `permission_version` are rechecked against the latest permission snapshot on subsequent HTTP, WS revalidation, and SDK entry.
- A permission snapshot changed to `allowed=false` causes HTTP requests to fail before route handling, `SocketAuthentication.revalidate` to raise `PermissionError`, and `Enterprise.sdk(token)` to fail closed.
- Existing owner/resource guard tests continue to verify tenant membership alone does not grant personal resource access.

Verification run:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_permission_snapshot_rechecked_for_http_ws_and_sdk \
  -q
# 1 passed
```

## Extension migration drift coverage — 2026-09-17

Scope verified in this slice:

- Added a catalog drift regression test that mutates EduPlus2 extension RLS state (`audit_export_jobs DISABLE ROW LEVEL SECURITY`) after migrations are applied.
- `MigrationRunner.verify()` and `MigrationRunner.apply()` both reject the drift with `eduplus2 schema drift`, proving extension tables including profile/permission/revocation/audit export remain covered by startup verification.

Verification run:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_persistence.py::test_eduplus2_extension_catalog_drift_blocks_verify \
  -q
# 1 passed
```

## Consolidated verification after continuation — 2026-09-17

Final verification run in this continuation:

```bash
./.venv/bin/python -m pytest tests/api/test_unified_ws_protocol.py -q
# 4 passed, 1 warning

./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 23 passed

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_eduplus2_extension_catalog_drift_blocks_verify \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 9 passed, 1 skipped

./.venv/bin/python -m ruff check <WS/core/enterprise EduPlus2 touched files and tests>
# All checks passed

cd web && npm run typecheck
# passed

cd web && npm exec -- eslint app/enterprise/audit/eduplus2/page.tsx
# 0 errors, 14 i18n literal-text warnings

openspec validate add-eduplus2-federated-access --strict
# Change 'add-eduplus2-federated-access' is valid

git diff --check -- <touched files>
# passed
```

Current OpenSpec task progress after this continuation: 39/50 complete.

Remaining blockers / intentionally unchecked tasks:

- Real EduPlus2 profile endpoint, permission endpoint, revocation webhook/event contract, unexpired test user JWT, and non-sensitive test tenant/user/client identifiers still need confirmation before real full-chain smoke can be claimed.
- Runtime config still needs final production values for refresh deadline/TTL, revocation cache/fallback window, and production audit export storage/ref policy.
- WS reconnect/resume and long-dialogue refresh behavior still need end-to-end socket tests.
- Active WS revocation notification/close and background task safety checkpoint need dedicated E2E coverage; current checks fail closed on next HTTP/WS/SDK revalidation.
- No-webhook short-TTL polling fallback and out-of-order/partial-failure revocation reconciliation are not implemented.
- Upstream seam risk review and final rollout conclusion remain pending until the above items are complete.

## WS/fallback/upstream seam closure slice — 2026-09-17

Scope implemented/verified in this slice:

- Replaced the core WS refresh proof field from EduPlus2-specific `eduplus2_jwt` to generic `external_token`; EduPlus2 interpretation now lives only in the enterprise provider.
- Verified the core seam diff remains provider-generic: protocol has generic `auth_refresh` / `auth_ack` / `auth_revoked`; router delegates refresh to `auth_provider.refresh`; identity core only exposes generic short-lived token / extra-claim issuance.
- Completed runtime config wiring for profile URL, permission URL, webhook secret/ref, refresh deadline leeway, revocation cache TTL, and audit export storage ref.
- Completed WS coverage for new `dt_token` reconnect/resume, refresh-before-expiry command continuation, expired-command rejection, duplicate refresh idempotency, and revoked-connection close-on-next-command behavior.
- Completed active revocation safety coverage: HTTP middleware, WS revalidate/refresh, SDK context, and `Enterprise.authorize()` now fail closed for revoked EduPlus2 permission snapshots.
- Implemented no-webhook short-TTL fallback: `ensure_token_allowed()` revalidates stale permission snapshots against EduPlus2 profile/permission clients, then fails closed if the external permission has been revoked. The local revocation window is bounded by `DT_EDUPLUS2_REVOCATION_CACHE_TTL_SECONDS` plus the configured resolve/profile/permission cache windows and the short `dt_token` TTL.
- Expanded security negative coverage for profile mismatch, permission denied/unavailable/expired, revoked old token over HTTP/WS/SDK/background checks, and audit export 403.

TDD evidence for fallback:

```bash
./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_token_check_revalidates_stale_permission_snapshot_without_webhook \
  -q
# RED before implementation: Failed: DID NOT RAISE PermissionError

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_federated_access.py::test_token_check_revalidates_stale_permission_snapshot_without_webhook \
  -q
# GREEN after implementation: 1 passed
```

Targeted verification run immediately after this slice:

```bash
./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 24 passed

./.venv/bin/python -m pytest tests/api/test_unified_ws_protocol.py -q
# 8 passed, 1 warning

# Core seam grep:
grep -RIn --exclude-dir='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
  'EduPlus2\|eduplus2' \
  deeptutor/api deeptutor/services deeptutor/runtime \
  deeptutor/persistence/postgres/identity/service.py
# no output
```

Current OpenSpec task progress after this slice: 46/50 complete.

Remaining blockers / intentionally unchecked tasks:

- 0.1: Real EduPlus2 profile endpoint, permission endpoint, revocation webhook/event contract, unexpired test user JWT, and non-sensitive test tenant/user/client identifiers still need external confirmation before real full-chain smoke can be claimed.
- 5.6: Replay/signature/duplicate cases are covered, but out-of-order event ordering, partial failure recovery, and reconciliation/backfill tests remain pending.
- 8.4: Full release gate remains open because real EduPlus2 full-chain smoke cannot be claimed yet; targeted local tests still need one final consolidated rerun after all edits.
- 8.5: Final rollout conclusion and production risk acceptance remain pending until the above blockers are resolved or explicitly accepted.

## Consolidated verification after WS/fallback seam closure — 2026-09-17

Fresh verification run after the `external_token` core seam refactor and no-webhook fallback implementation:

```bash
./.venv/bin/python -m pytest tests/api/test_unified_ws_protocol.py -q
# 8 passed, 1 warning

./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 24 passed

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_eduplus2_extension_catalog_drift_blocks_verify \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 9 passed, 1 skipped

./.venv/bin/python -m ruff check \
  deeptutor/api/contracts/turn_protocol.py \
  deeptutor/api/routers/unified_ws.py \
  deeptutor/persistence/postgres/identity/service.py \
  extensions/enterprise/src/deeptutor_enterprise/api/application.py \
  extensions/enterprise/src/deeptutor_enterprise/bootstrap.py \
  extensions/enterprise/src/deeptutor_enterprise/eduplus2 \
  extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py \
  extensions/enterprise/tests/test_eduplus2_federated_access.py \
  extensions/enterprise/tests/test_eduplus2_real_smoke.py \
  extensions/enterprise/tests/test_persistence.py \
  tests/api/test_unified_ws_protocol.py
# All checks passed

cd web && npm run typecheck
# passed

cd web && npm exec -- eslint app/enterprise/audit/eduplus2/page.tsx
# 0 errors, 14 i18n literal-text warnings

openspec validate add-eduplus2-federated-access --strict
# Change 'add-eduplus2-federated-access' is valid

git diff --check -- <EduPlus2/core/OpenSpec touched paths>
# passed
```

Note: `extensions/enterprise/tests/test_eduplus2_real_smoke.py` still skipped one real-environment smoke because task 0.1 external contracts/test inputs are not fully confirmed; therefore task 8.4 remains unchecked.

## Scope adjustment: no realtime revocation gate — 2026-09-17

User decision captured in this slice:

- TMS/OMS login remains out of scope.
- Realtime revocation propagation is no longer a gate for this proposal.
- Required behavior is now: validate current user/client/app/tenant/profile/permission on each open/exchange/refresh/new sensitive HTTP/WS/SDK operation and at periodic background safety checkpoints.
- Webhook/revocation event support remains as an optional enhancement already present in code, but webhook contract, out-of-order event handling, partial-failure recovery, and reconciliation/backfill are deferred to a future realtime-revocation proposal if a realtime SLA is required.

OpenSpec artifacts updated:

- `proposal.md`: replaced realtime revocation propagation with open/refresh/periodic legality revalidation.
- `design.md`: decision 5 now defines periodic legality checks and webhook as optional enhancement.
- `specs/enterprise-eduplus2-federated-access/spec.md`: requirement now says open/refresh/periodic revalidation must cover new operations, WS and caches; realtime webhook is not a production gate.
- `tasks.md`: section 5 renamed; task 5.6 now records realtime revocation ordering/reconciliation as deferred while keeping currently covered webhook replay/signature/duplicate and periodic fail-closed tests.

Task progress after this scope adjustment: expected 47/50 complete. Remaining gates are external EduPlus2 non-secret test contracts, final full verification including real smoke, and rollout conclusion.

## Scope adjustment: legality checks owned by frontend/upstream app — 2026-09-17

User decision captured in this slice:

- Opening DeepTutor, refresh-time user legality checks, and periodic user/client/app/tenant/permission validity checks are responsibilities of the frontend/upstream application, not this repository.
- Current repo keeps only its own trust boundary: JWT exchange/resolve, short-lived `dt_token`, WS token refresh mechanics, owner/resource guard, audit query/export, and optional profile/permission/webhook enhancement code when configured.
- Webhook and realtime revocation remain optional and are not a gate for this proposal.

## Final real user-JWT exchange and rollout gate — 2026-09-17

Scope/config evidence:

- `.secrets/token-test.secrets` was refreshed by the user with an unexpired EduPlus2 user JWT.
- `DT_EDUPLUS2_CLIENT_ID` / `DT_EDUPLUS2_CLIENT_SECRET` in local/test EduPlus2 env files were aligned to `token-test.secrets`.
- `DT_EDUPLUS2_ALLOWED_CLIENTS` was generated from the token-test client plus the real resolve response tenant/app identifiers, with `source=env_allowlist` so the extension can auto-upsert the registration.
- No token, client secret, or user-private values were written to OpenSpec evidence.

Real smoke evidence:

```bash
# Token structure check against token-test.secrets
# token_valid_now=True
# token_azp_matches_client=True

# Real user JWT -> DeepTutor dt_token exchange smoke against local PG + real EduPlus2 OIDC/JWKS/token/resolve
# token_valid_now True
# token_azp_matches_client True
# exchange_status ok
# dt_token_valid_now True
# dt_token_has_eduplus2_claim True
# dt_token_azp_matches_client True

set -a
. .secrets/deeptutor-local-eduplus2.env
set +a
export DT_EDUPLUS2_REAL_SMOKE=1
PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_real_smoke.py -q
# 1 passed
```

Final targeted verification:

```bash
./.venv/bin/python -m pytest tests/api/test_unified_ws_protocol.py -q
# 8 passed, 1 warning

./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 24 passed

./.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_persistence.py::test_migrations_repeat_concurrent_and_runtime_ddl \
  extensions/enterprise/tests/test_persistence.py::test_eduplus2_extension_catalog_drift_blocks_verify \
  extensions/enterprise/tests/test_persistence.py::test_migration_sql_failure_rolls_back_ddl_data_and_history \
  extensions/enterprise/tests/test_persistence.py::test_forged_success_history_without_real_schema_is_not_verified \
  -q
# 9 passed

./.venv/bin/python -m ruff check <EduPlus2/core touched Python paths>
# All checks passed

cd web && npm run typecheck
# passed

cd web && npm exec -- eslint app/enterprise/audit/eduplus2/page.tsx
# 0 errors, 14 i18n literal-text warnings

openspec validate add-eduplus2-federated-access --strict
# Change 'add-eduplus2-federated-access' is valid

git diff --check -- <EduPlus2/core/OpenSpec/UI touched paths>
# passed
```

Rollout conclusion:

- Current proposal gates for this repo are satisfied: API-only EduPlus2 exchange, resolve/allowlist, short `dt_token`, WS token refresh seam, owner/resource guard, audit query/export UI/API, migrations/RLS/drift checks, upstream seam review, and real discovery/M2M/resolve/user-JWT exchange smoke all have evidence.
- TMS/OMS login, handoff/OIDC callback, online client governance, realtime revocation SLA, complex event ordering/reconciliation, and frontend/upstream-app periodic legality checks are outside this proposal and must be handled by future work or the upstream application.
- Optional profile/permission/webhook clients remain implemented/configurable as enhancements, but they are not required gates for this scoped rollout.
- Production rollout still requires operational handling outside this repo: keep `token-test.secrets` out of version control, generate fresh user JWTs from the fronting application, preserve short `dt_token` TTL, and monitor audit/export access.
