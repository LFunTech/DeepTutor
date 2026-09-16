# Execution Evidence — externalize-data-directory-for-kubernetes-runtime

> 每个实现切片必须追加一节。没有真实验证的项目必须写明“未验证”及原因，不能用 OpenSpec task 勾选替代业务验证。

## Slice Evidence Template

### Slice
- Slice ID / task IDs:
- Date:
- Operator / agent:
- Code paths changed:
- OpenSpec requirements covered:

### DB migration evidence
- Migration version(s):
- Empty database apply:
- Existing PG-only upgrade:
- Drift detection:
- Concurrent apply:
- Runtime role DDL/staging denial:
- Rollback / failed migration behavior:

### Runtime entrypoints exercised
- Web/API:
- WebSocket:
- CLI:
- SDK:
- Background jobs:
- Offline maintenance/import commands:

### Provider/readiness evidence
- Runtime mode tested:
- PG provider status:
- ObjectStore provider status:
- Settings/Policy provider status:
- Secret provider status:
- Data gate inventory/report:
- Fail-closed cases:
- Sanitized error sample:

### Permissions and negative tests
- Tenant/owner matrix:
- Admin/tenant_admin/operator/auditor matrix:
- Cross-owner or forged local path attempts:
- Legacy local provider fallback attempts:
- Cache/projection/scratch deletion behavior:

### Pod rebuild / empty local disk evidence
- Environment:
- Initial writes:
- Local `data/` removed paths:
- Recreated Pod/container identity:
- Reads after rebuild:
- Background recovery:
- Remaining local-only state:

### Secret redaction evidence
- Secret references used:
- Logs checked:
- API/status response checked:
- Migration/import report checked:
- OpenSpec evidence checked:
- Plaintext leakage result:

### Verification commands
- Commands run:
- Exit codes:
- Not run / why:

### Remaining local path inventory
| Path | Category | Entrypoints | Owner/tenant boundary | Status | Follow-up |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

### Risks / follow-ups
-

## Evidence log

### 2026-09-16 — A1 initial gate/schema/seam slice
- Tasks touched: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6 (partial; not complete)
- Code paths changed:
  - `deeptutor/runtime/data_gate.py`
  - `deeptutor/runtime/externalized_providers.py`
  - `deeptutor/app/postgres_runtime.py`
  - `deeptutor/services/path_service.py`
  - `deeptutor/persistence/postgres/migrations/0014_externalized_runtime.sql`
  - `deeptutor/persistence/postgres/migrations/runner.py`
- Verification run:
  - `openspec validate externalize-data-directory-for-kubernetes-runtime --strict` → passed.
  - `.venv/bin/python -m pytest -q tests/runtime/test_kubernetes_data_gate.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/api/test_default_pg_runtime.py::test_default_container_assembles_real_pg_store_auth_and_domain_providers tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 41 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/test_migrations.py -k 'not enterprise_runner'` → 8 passed, 1 deselected.
  - `.venv/bin/python -m ruff check ...` on changed Python files → passed.
- Environment limitations:
  - Full `tests/persistence/postgres/test_migrations.py` still has an existing environment failure because `deeptutor_enterprise` is not installed.
  - Git status/diff could not be collected with `/usr/bin/git` because this machine requires accepting the Xcode license.
- Not yet verified: real S3/ObjectStore, K8s Pod rebuild, dual Pod behavior, settings API provider cutover, real import/report CLI, full route/CLI/SDK matrix.

### 2026-09-16 — A2.1 S3-compatible ObjectStore provider unit slice
- Tasks touched: 2.1 (partial; not complete) and 1.4 provider seam extension.
- Code paths changed:
  - `deeptutor/runtime/externalized_providers.py`
  - `tests/runtime/test_s3_object_store.py`
- Implemented behavior:
  - `S3ObjectStoreConfig` with endpoint/region/bucket/path-style/TLS/SSE/timeout/retry config.
  - `S3CompatibleObjectStore` using httpx + AWS Signature V4.
  - Credentials are resolved lazily through `SecretResolver` references only.
  - PUT uploads include SHA-256 metadata and optional SSE header; PUT is followed by HEAD size/hash verification.
  - Provider errors use stable redacted `ObjectStoreError` codes for missing bucket, permission denied, unreachable provider, size/hash mismatch and generic request failure.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py tests/runtime/test_kubernetes_data_gate.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/api/test_default_pg_runtime.py::test_default_container_assembles_real_pg_store_auth_and_domain_providers tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 46 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/test_migrations.py -k 'not enterprise_runner'` → 8 passed, 1 deselected.
  - `.venv/bin/python -m ruff check ...` on changed/related Python files → passed.
- Not yet verified:
  - Real S3-compatible round-trip smoke was added and recorded in the following slice using the machine-local compatible service; 具体存储产品矩阵不在本 change 范围内。
  - No presigned URL/proxy download flow yet.
  - No PG metadata commit/cleanup integration yet.
  - No Web/API/WS/SDK attachment path migration yet.

### 2026-09-16 — A2.1 local S3-compatible readiness and round-trip slice
- Tasks touched: 2.1 (partial; not complete).
- Code paths changed:
  - `deeptutor/runtime/externalized_providers.py`
  - `tests/runtime/test_s3_object_store.py`
- Implemented behavior:
  - Added redacted ObjectStore readiness status via `S3CompatibleObjectStore.check_bucket()`, implemented as signed HEAD bucket.
  - Added generic S3-compatible environment config parsing via `S3ObjectStoreConfig.from_environment()`; deployment env stores Secret references, not credential plaintext.
  - Added missing-Secret fail-closed mapping so readiness and writes report stable redacted `objectstore_credentials_missing` instead of leaking `SecretResolver` details.
  - Added local S3-compatible integration smoke gated by `DEEPTUTOR_RUN_S3_COMPATIBLE_TESTS=1`; it resolves credentials via `EnvSecretResolver`, checks bucket readiness, uploads with hash verification, reads the object back, and deletes it. The local service is an implementation detail of the smoke, not a product-specific acceptance requirement.
- Provider/readiness evidence:
  - Runtime mode tested: local integration smoke against a machine-local S3-compatible endpoint; production/K8s Pod smoke remains pending.
  - ObjectStore provider status: local S3-compatible endpoint at `http://127.0.0.1:9000`, bucket `local-debug`, path-style access, signed requests.
  - Secret provider status: generic `env:` references populated only inside the test process; evidence does not record Secret plaintext.
  - Fail-closed cases still covered by unit tests for 404 bucket missing, 403 permission denied, network interruption, and hash mismatch.
  - Sanitized status sample shape: `s3:local-debug:available:objectstore_ready`.
- Secret redaction evidence:
  - Secret references used: `env:DEEPTUTOR_TEST_S3_ACCESS_KEY`, `env:DEEPTUTOR_TEST_S3_SECRET_KEY`.
  - Logs checked: test output and local-debug smoke output did not print credential values.
  - API/status response checked: readiness status exposes provider, bucket, availability and stable code only.
  - Plaintext leakage result: no Secret plaintext recorded in test assertions or evidence.
- Verification run:
  - `~/.codex/skills/local-debug/scripts/local-debug.sh status minio && ~/.codex/skills/local-debug/scripts/local-debug.sh smoke minio` → exit 0; MinIO live/ready health returned 200 and smoke uploaded/read `smoke.txt`.
  - `.venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py` → 9 passed, 1 skipped.
  - `DEEPTUTOR_RUN_S3_COMPATIBLE_TESTS=1 DEEPTUTOR_TEST_S3_*=[redacted] .venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py::test_s3_object_store_round_trips_against_s3_compatible_endpoint` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py tests/runtime/test_kubernetes_data_gate.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/api/test_default_pg_runtime.py::test_default_container_assembles_real_pg_store_auth_and_domain_providers tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 47 passed, 1 skipped.
  - `.venv/bin/python -m ruff check deeptutor/runtime/externalized_providers.py tests/runtime/test_s3_object_store.py` → passed.
  - `openspec validate externalize-data-directory-for-kubernetes-runtime --strict` → passed.
- Not yet verified:
  - PG resource metadata transaction/compensation wiring.
  - Web/API/WS/SDK attachment/resource flows and Pod rebuild with empty local `data/`.

### 2026-09-16 — A2.1 S3-compatible provider contract completion
- Tasks completed: 2.1.
- Code paths changed:
  - `deeptutor/runtime/externalized_providers.py`
  - `tests/runtime/test_s3_object_store.py`
  - `openspec/changes/externalize-data-directory-for-kubernetes-runtime/tasks.md`
- Contract coverage:
  - Endpoint/region/bucket/path-style/TLS/SSE/timeout/retry settings are represented in `S3ObjectStoreConfig`; `from_environment()` stores only Secret references and supports generic `DEEPTUTOR_OBJECTSTORE_*` env config.
  - `S3CompatibleObjectStore` signs S3-compatible requests with SigV4, supports path-style and virtual-hosted-style addressing, resolves credentials only through `SecretResolver`, verifies uploaded/read object size and SHA-256, and returns redacted stable errors.
  - Unit coverage includes missing bucket, permission denied, hash mismatch, network interruption/retry, missing Secret fail-closed, readiness HEAD bucket, path-style upload and virtual-hosted-style upload.
  - Integration smoke uses a local S3-compatible endpoint only as contract evidence; no product-specific matrix is required per scope decision.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py::test_s3_object_store_config_from_environment_uses_secret_refs_not_plaintext` → 1 passed after RED failure `AttributeError: type object 'S3ObjectStoreConfig' has no attribute 'from_environment'`.
  - `.venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py::test_s3_object_store_check_bucket_reports_missing_secret_without_http_or_plaintext tests/runtime/test_s3_object_store.py::test_s3_object_store_put_fails_closed_when_secret_missing` → 2 passed after RED failures from uncaught `SecretResolutionError`.
  - `.venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py::test_s3_object_store_supports_virtual_hosted_style_without_leaking_secret` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py` → 9 passed, 1 skipped before virtual-hosted coverage; final full command below includes the added test.
  - `DEEPTUTOR_RUN_S3_COMPATIBLE_TESTS=1 DEEPTUTOR_TEST_S3_*=[redacted] .venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py::test_s3_object_store_round_trips_against_s3_compatible_endpoint` → 1 passed.
  - `.venv/bin/python -m ruff check deeptutor/runtime/externalized_providers.py tests/runtime/test_s3_object_store.py && .venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py tests/runtime/test_kubernetes_data_gate.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/api/test_default_pg_runtime.py::test_default_container_assembles_real_pg_store_auth_and_domain_providers tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py && openspec validate externalize-data-directory-for-kubernetes-runtime --strict` → ruff passed; 51 passed, 1 skipped; OpenSpec strict validation passed.
  - `openspec validate externalize-data-directory-for-kubernetes-runtime --strict` → passed.
- Remaining follow-up outside 2.1:
  - 2.2+ PG metadata commit/compensation wiring, attachment/resource API migrations, cleanup job, and Pod rebuild smoke remain pending.

### 2026-09-16 — A2.2 runtime ObjectStore wiring and HTTP proxy authorization slice
- Tasks touched: 2.2 (partial; not complete) and 1.2/1.4 production provider gate integration.
- Code paths changed:
  - `deeptutor/app/postgres_runtime.py`
  - `deeptutor/app/container.py`
  - `tests/runtime/test_kubernetes_data_gate.py`
  - `tests/api/test_default_pg_runtime.py`
  - `tests/persistence/postgres/business/test_externalized_session_resources.py`
- Implemented behavior:
  - `DefaultPostgresRuntime.from_environment()` now constructs a production S3-compatible ObjectStore provider from `DEEPTUTOR_OBJECTSTORE_*` config when present, using `EnvSecretResolver` references rather than reading credential plaintext during construction.
  - In production/Kubernetes mode with ObjectStore configured, the runtime no longer instantiates local `OwnerResourceProvider` for attachment authority; the data gate sees `owner_resources=objectstore` instead of `local`.
  - `DefaultPostgresRuntime.start()` checks ObjectStore bucket readiness before PG connection/schema verification and fails closed with the existing redacted `production_data_provider_required` code when ObjectStore Secret resolution/readiness fails.
  - `ApplicationContainer.build()` now passes the runtime ObjectStore provider into `ApplicationProviders`, so attachment routes/factories can build `PostgresObjectAttachmentStore` rather than falling back to local owner resources.
  - HTTP `/files/attachments/{session_id}/{attachment_id}/{filename}` proxy coverage now verifies PG authorization occurs before ObjectStore read, and cross-owner access does not touch ObjectStore bytes.
  - Direct ObjectStore-backed attachment delete coverage verifies unreferenced attachments are removed from ObjectStore and become unreadable.
- Permissions and authorization boundary:
  - Existing attachment proxy endpoints remain scoped by current PG owner through `ApplicationProviders.store` and `PostgresSessionStore.scope`.
  - Object keys/bucket presence do not authorize reads; `PostgresObjectAttachmentStore.read_attachment()` first checks `session_objects`, `sessions`, `message_objects`, and `resource_objects` for the current tenant/owner.
  - No new OpenFGA model, Keycloak role/scope, menu, frontend permission, or default administrator grant was added in this slice.
- DB migration / state migration judgment:
  - No new schema migration was added in this slice; implementation uses existing `0014_externalized_runtime.sql` tables (`resource_objects`, `resource_cleanup_jobs`, `message_objects`, `session_objects`).
  - No data backfill, OpenFGA tuple/model migration, Keycloak migration, or tenant bootstrap change was performed.
- RED/GREEN evidence:
  - `tests/runtime/test_kubernetes_data_gate.py::test_default_postgres_runtime_uses_s3_objectstore_in_kubernetes_mode` first failed with `production_data_provider_required` because runtime still declared local owner resources; after implementation it passed.
  - `tests/runtime/test_kubernetes_data_gate.py::test_default_postgres_runtime_start_requires_objectstore_secret_before_pg_connection` first failed with a PG hostname `OperationalError`, proving ObjectStore readiness was not checked before PG; after implementation it passed with redacted `production_data_provider_required`.
  - `tests/api/test_default_pg_runtime.py::test_default_container_build_exports_runtime_objectstore_provider` first failed because `container.object_store_provider` was `None`; after wiring it passed.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/runtime/test_kubernetes_data_gate.py::test_default_postgres_runtime_uses_s3_objectstore_in_kubernetes_mode` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/runtime/test_kubernetes_data_gate.py::test_default_postgres_runtime_start_requires_objectstore_secret_before_pg_connection` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/api/test_default_pg_runtime.py::test_default_container_build_exports_runtime_objectstore_provider` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_session_resources.py::test_externalized_attachment_http_proxy_uses_pg_authorization_before_objectstore` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_session_resources.py::test_externalized_attachment_delete_attachment_cleans_unreferenced_objectstore_object` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_session_resources.py` → 4 passed.
  - `.venv/bin/python -m ruff check deeptutor/app/postgres_runtime.py deeptutor/app/container.py tests/runtime/test_kubernetes_data_gate.py tests/api/test_default_pg_runtime.py tests/persistence/postgres/business/test_externalized_session_resources.py` → passed.
  - `.venv/bin/python -m pytest -q tests/runtime/test_kubernetes_data_gate.py tests/api/test_default_pg_runtime.py::test_default_container_build_exports_runtime_objectstore_provider tests/persistence/postgres/business/test_externalized_session_resources.py tests/persistence/postgres/business/test_session_resources.py tests/persistence/postgres/business/test_session_resource_races.py tests/runtime/test_s3_object_store.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 74 passed, 1 skipped.
- Not yet verified / remaining 2.2 blockers:
  - Full real Web/API/WS/SDK upload path in a started production runtime with real S3-compatible service remains pending.
  - Pod rebuild / empty local `data/` smoke remains pending.
  - Full cross-owner matrix through authenticated HTTP middleware remains pending; current slice covers store/provider-context HTTP proxy boundary.
  - Upload-success/PG-ready-commit-unknown compensation for ObjectStore-backed store beyond recorded cleanup request remains pending.
  - Avatar/personal model/Codex owner resource categories are no longer backed by local `OwnerResourceProvider` in K8s ObjectStore mode, but their final ObjectStore/Settings replacements are outside this 2.2 attachment slice and remain pending in later A2 tasks.

### 2026-09-16 — A2.2 turn/SDK/WS ObjectStore attachment entrypoint slice
- Tasks touched: 2.2 (partial; not complete yet).
- Code paths changed:
  - `deeptutor/services/session/turns/executor.py`
  - `tests/persistence/postgres/business/test_externalized_turn_attachments.py`
  - `tests/api/test_http_provider_context.py`
  - `tests/persistence/postgres/business/test_externalized_session_resources.py`
- Implemented behavior:
  - Turn attachment upload now preserves ObjectStore-backed upload failures instead of swallowing them and later failing with a misleading local/PG authority error.
  - `TurnRuntimeManager.start_turn()` coverage verifies ObjectStore upload failures fail the turn before LLM invocation and record a redacted/stable error in stream events.
  - Successful turn upload coverage verifies attachment bytes are written to ObjectStore, the persisted user message stores the PG metadata-backed `/files/attachments/{session}/{object_id}/{filename}` URL, base64 payload is stripped, and a rebuilt PG store can read the object after restart/reconstruction.
  - SDK entrypoint coverage verifies `DeepTutorApp(container=...)` / `TurnApplicationService.start_turn()` propagates `ApplicationProviders.object_store` through operation context and writes chat attachments to ObjectStore + PG metadata.
  - WebSocket entrypoint coverage verifies `/ws` `start_turn` runs inside the application provider context and sees the container ObjectStore provider.
  - PG publish-failure coverage verifies an object uploaded to ObjectStore but rejected during PG ready publication is marked for cleanup, receives a pending cleanup job, and `cleanup_pending()` deletes the object idempotently.
- Permissions and authorization boundary:
  - HTTP attachment proxy authorization remains PG-first: cross-owner requests do not read ObjectStore bytes.
  - Turn/SDK/WS upload paths use the caller's `ApplicationProviders` / PG session store scope; object keys alone do not grant read access.
  - No new OpenFGA relation/model, Keycloak role/scope, frontend menu permission, or administrator grant was added.
- DB migration / state migration judgment:
  - No new migration was added in this slice. The implementation uses existing `0014_externalized_runtime.sql` metadata (`session_objects`, `message_objects`, `resource_objects`, `resource_cleanup_jobs`).
  - No tenant bootstrap, OpenFGA tuple/model migration, Keycloak migration, or data backfill was performed.
- RED/GREEN evidence:
  - `test_turn_upload_failure_in_objectstore_attachment_store_fails_turn_without_llm` initially failed because the runtime swallowed `ObjectStoreError` and later emitted `attachment source lacks a PostgreSQL authority provider`; after preserving `PostgresObjectAttachmentStore` errors it passed with `objectstore_unavailable`.
  - The SDK test initially exposed test-fixture gaps (`_noop_async` and missing workspace-folder double); after fixing the fixture, the real SDK start-turn path passed.
  - `test_externalized_attachment_publish_failure_records_cleanup_job_and_deletes_object` initially failed because the synthetic fault used `runtime_dsn` without `TenantScope`, so RLS blocked the state mutation and no PG publish failure occurred. The fault injection was corrected to use the migration/maintenance connection; the compensation path then passed.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_session_resources.py::test_externalized_attachment_publish_failure_records_cleanup_job_and_deletes_object` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_session_resources.py` → 5 passed.
  - `.venv/bin/python -m ruff check deeptutor/services/session/turns/executor.py tests/persistence/postgres/business/test_externalized_turn_attachments.py tests/api/test_http_provider_context.py tests/persistence/postgres/business/test_externalized_session_resources.py` → passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_turn_attachments.py tests/persistence/postgres/business/test_externalized_session_resources.py tests/persistence/postgres/business/test_session_resources.py tests/persistence/postgres/business/test_session_resource_races.py tests/api/test_http_provider_context.py tests/runtime/test_kubernetes_data_gate.py tests/api/test_default_pg_runtime.py::test_default_container_build_exports_runtime_objectstore_provider tests/runtime/test_s3_object_store.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 80 passed, 1 skipped.
- Not yet verified / remaining 2.2 blockers:
  - Full authenticated browser/Web UI flow against a started production backend and real S3-compatible endpoint remains pending.
  - Full K8s-like Pod rebuild / empty local `data/` smoke remains pending and is tracked in A3/B1 tasks.
  - The new WebSocket test verifies provider-context propagation; a full WS end-to-end upload with the production app, auth middleware, and real S3-compatible endpoint remains pending.

### 2026-09-16 — A2.2 full WebSocket ObjectStore attachment upload coverage
- Tasks touched: 2.2 (partial; not complete yet).
- Code paths changed:
  - `tests/persistence/postgres/business/test_externalized_turn_attachments.py`
- Implemented/verified behavior:
  - Added a real `/ws` `start_turn` test using `unified_ws.unified_websocket`, `TurnApplicationService`, `TurnRuntimeManager`, authenticated PG actor context, and container `ApplicationProviders.object_store`.
  - The WebSocket payload carries a base64 chat attachment; the runtime writes bytes to ObjectStore, stores only PG metadata-backed attachment URL in the user message, strips base64, streams terminal `done`, and a rebuilt PG store reads the bytes back through `PostgresObjectAttachmentStore`.
- RED/GREEN evidence:
  - First version expected a `session` stream event and failed with `StopIteration`; inspection showed the subscribed replay provided the terminal `done` with top-level `session_id`. The test now uses that canonical envelope and passes.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_turn_attachments.py::test_ws_start_turn_uploads_attachment_through_container_objectstore` → 1 passed.
  - `.venv/bin/python -m ruff check tests/persistence/postgres/business/test_externalized_turn_attachments.py` → passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_turn_attachments.py` → 4 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_turn_attachments.py tests/persistence/postgres/business/test_externalized_session_resources.py tests/persistence/postgres/business/test_session_resources.py tests/persistence/postgres/business/test_session_resource_races.py tests/api/test_http_provider_context.py tests/runtime/test_kubernetes_data_gate.py tests/api/test_default_pg_runtime.py::test_default_container_build_exports_runtime_objectstore_provider tests/runtime/test_s3_object_store.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 81 passed, 1 skipped.
- Remaining 2.2 notes:
  - Store/API/SDK/WS/object cleanup contract coverage is now present in isolated PG tests. A full browser-driven UI smoke against a deployed production backend and live S3-compatible service is still deferred to the K8s smoke tasks (A3.4/B1), not claimed here.

### 2026-09-16 — A2.2 API operation and live S3-compatible turn attachment smoke
- Tasks touched: 2.2.
- Code paths changed:
  - `tests/persistence/postgres/business/test_externalized_session_resources.py`
  - `tests/persistence/postgres/business/test_externalized_turn_attachments.py`
- Implemented/verified behavior:
  - Added HTTP attachment operation API coverage for ObjectStore-backed unreferenced attachment withdrawal: foreign owner receives 404 without deleting bytes; owning scope deletes via `/files/attachments/operations/{object_id}` and removes the ObjectStore object.
  - Added gated integration coverage for a real S3-compatible provider in the chat turn path: `/turn runtime -> PostgresObjectAttachmentStore -> S3CompatibleObjectStore -> PG metadata -> read back -> delete cleanup`.
  - The gated smoke uses generic S3-compatible config and `env:` Secret references; no provider-specific product matrix is introduced.
- Provider/readiness evidence:
  - Machine-local S3-compatible endpoint status/smoke verified with local-debug MinIO health/readiness and bucket `local-debug`.
  - Secret values were injected only through environment variables for the test process and not printed in assertions or evidence.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_session_resources.py::test_externalized_attachment_operation_api_withdraws_unreferenced_objectstore_object` → 1 passed.
  - `.venv/bin/python -m ruff check tests/persistence/postgres/business/test_externalized_session_resources.py` → passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_session_resources.py` → 6 passed.
  - `.venv/bin/python -m ruff check tests/persistence/postgres/business/test_externalized_turn_attachments.py` → passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_turn_attachments.py` → 4 passed, 1 skipped (gated S3-compatible smoke skipped without env opt-in).
  - `~/.codex/skills/local-debug/scripts/local-debug.sh status minio && ~/.codex/skills/local-debug/scripts/local-debug.sh smoke minio && DEEPTUTOR_RUN_S3_COMPATIBLE_TESTS=1 DEEPTUTOR_TEST_S3_*=[redacted] .venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_turn_attachments.py::test_turn_attachment_round_trips_against_s3_compatible_endpoint` → MinIO health live=200/ready=200; smoke upload/read succeeded; gated turn attachment smoke 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_turn_attachments.py tests/persistence/postgres/business/test_externalized_session_resources.py tests/persistence/postgres/business/test_session_resources.py tests/persistence/postgres/business/test_session_resource_races.py tests/api/test_http_provider_context.py tests/runtime/test_kubernetes_data_gate.py tests/api/test_default_pg_runtime.py::test_default_container_build_exports_runtime_objectstore_provider tests/runtime/test_s3_object_store.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 82 passed, 2 skipped.

### 2026-09-16 — A2.3-A2.8 generic ObjectResource store for durable non-attachment files
- Tasks touched: 2.3, 2.4, 2.5, 2.6, 2.7, 2.8.
- Code paths changed:
  - `deeptutor/persistence/postgres/object_resources.py`
  - `deeptutor/api/routers/resources.py`
  - `deeptutor/api/main.py`
  - `tests/persistence/postgres/business/test_externalized_object_resources.py`
- Implemented behavior:
  - Added `PostgresObjectResourceStore`, a PG-authorized ObjectStore resource path for durable non-attachment files. PG `resource_objects` metadata is the visibility/lifecycle authority; ObjectStore bucket/key alone never authorizes reads.
  - Added proxy download route `/files/resources/{resource_kind}/{resource_id}/{object_id}/{filename}`. It validates PG metadata/owner before ObjectStore read and returns `private, no-store` content without credentials.
  - Covered required A2 resource kinds through the shared store: `reading_material`, `workspace_output`, `generated_artifact`, `export_file`, `persistent_intermediate`, `kb_source`, `dynamic_persona`, `dynamic_skill`, and `notebook_file`.
  - Added cleanup/reconciliation for generic resources using `resource_cleanup_jobs`, including upload-ready publish failure compensation, delete failure retry, queryable failed jobs, idempotent retry, and protection against deleting ready or foreign-owner objects.
  - Added old local path forgery rejection: wrong `resource_id` / local-path anchor cannot read an object, and filenames containing path separators are rejected rather than sanitized into a different file.
  - Added batch/large-payload lifecycle coverage for bulk generated artifacts and a 1 MiB workspace output sample.
- Permissions and authorization boundary:
  - Cross-owner generic resource reads fail before `ObjectStore.get_bytes` is called.
  - Same bucket/key suffixes under different owners stay isolated because object keys are generated from tenant and hashed owner/resource binding, while PG owner scope is checked on each read/delete/cleanup.
  - No OpenFGA, Keycloak, menu, or default administrator permission changes were added.
- DB migration / state migration judgment:
  - No new migration was required; implementation uses existing `0014_externalized_runtime.sql` tables (`resource_objects`, `resource_cleanup_jobs`).
  - No data backfill, tenant bootstrap, OpenFGA tuple/model migration, or Keycloak migration was performed in this slice.
- RED/GREEN evidence:
  - Initial generic resource test failed with `ModuleNotFoundError: deeptutor.persistence.postgres.object_resources`; added the store and round-trip behavior.
  - Metadata insert initially failed with `psycopg.ProgrammingError: cannot adapt type 'dict'`; fixed by using `Jsonb` for resource metadata.
  - Delete retry test initially failed because `PostgresObjectResourceStore.delete` did not exist; added delete/list-cleanup/cleanup-pending implementation.
  - HTTP proxy test initially failed because `deeptutor.api.routers.resources` did not exist; added the router and registered it in `api/main.py`.
  - Local path forgery test initially failed because filenames were sanitized with `Path(...).name`; fixed by rejecting path separators for generic object resources.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_store_round_trips_required_a2_file_kinds` → 1 passed after RED failures above.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_delete_failure_is_queryable_and_retried` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_http_proxy_authorizes_before_objectstore_read` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_upload_publish_failure_records_cleanup_job` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_rejects_forged_local_path_and_wrong_resource_binding` → 1 passed after RED failure above.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_store_covers_kb_persona_skill_and_notebook_kinds` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_cleanup_never_deletes_ready_or_foreign_owner_objects` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_bulk_and_large_payload_lifecycle` → 1 passed.
  - `.venv/bin/python -m ruff check deeptutor/persistence/postgres/object_resources.py deeptutor/api/routers/resources.py tests/persistence/postgres/business/test_externalized_object_resources.py deeptutor/api/main.py` → passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py` → 8 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py tests/persistence/postgres/business/test_externalized_turn_attachments.py tests/persistence/postgres/business/test_externalized_session_resources.py tests/persistence/postgres/business/test_session_resources.py tests/persistence/postgres/business/test_session_resource_races.py tests/api/test_http_provider_context.py tests/runtime/test_kubernetes_data_gate.py tests/api/test_default_pg_runtime.py::test_default_container_build_exports_runtime_objectstore_provider tests/runtime/test_s3_object_store.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 90 passed, 2 skipped.
- Remaining notes:
  - This slice establishes the production object-resource path and API proxy for the listed resource classes. Full browser UX and deployed K8s smoke for every feature surface remain covered by A3/B/C end-to-end tasks.

### 2026-09-16 — A1 inventory/gate/schema/provider evidence closure
- Tasks completed: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6.
- Code paths changed/verified:
  - `deeptutor/runtime/data_gate.py`
  - `deeptutor/app/postgres_runtime.py`
  - `deeptutor/runtime/externalized_providers.py`
  - `deeptutor/services/path_service.py`
  - `deeptutor/persistence/postgres/migrations/0014_externalized_runtime.sql`
  - `openspec/changes/externalize-data-directory-for-kubernetes-runtime/migration-report-template.md`
  - `tests/runtime/test_kubernetes_data_gate.py`
- Implemented/verified behavior:
  - Frozen production `data/` inventory covers settings/system/user-secrets/postgres-resources/workspace/notebooks/knowledge_bases/memory/partners/logs/runtime/parse-cache/offline-import-input with explicit categories, owner boundaries and entrypoints.
  - Production/Kubernetes runtime mode fails closed on local owner resource authority, forbidden path bootstrap, unknown data paths, missing ObjectStore secrets, and avoids creating production local authority directories.
  - Local PG-backed development mode remains allowed where explicitly local.
  - PG externalized metadata/settings/policy/secret-reference migration is applied through the existing migration runner and low-privilege runtime role tests.
  - `ObjectStore`, `SecretResolver`, `ResourceHandle`, local-dev object store boundary and S3-compatible provider seams are verified without reading credential plaintext during construction.
  - OpenSpec evidence and migration report templates now require DB migration, entrypoint, permission/negative, Pod rebuild, Secret redaction and local-path inventory evidence.
- Secret redaction evidence:
  - Runtime/data gate summaries contain stable codes and relative paths only; tests assert DSN password and Secret env var names/values are not included in user-facing errors.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/runtime/test_kubernetes_data_gate.py::test_default_data_inventory_covers_required_paths_and_boundaries tests/runtime/test_kubernetes_data_gate.py` → 8 passed.
  - `.venv/bin/python -m ruff check tests/runtime/test_kubernetes_data_gate.py deeptutor/runtime/data_gate.py deeptutor/app/postgres_runtime.py deeptutor/runtime/externalized_providers.py deeptutor/services/path_service.py` → passed.
  - `.venv/bin/python -m pytest -q tests/runtime/test_kubernetes_data_gate.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 43 passed.
  - `openspec validate externalize-data-directory-for-kubernetes-runtime --strict` → passed.
- Notes:
  - A prior accidental `ruff check` invocation included a `.sql` migration path and produced Python parser errors for SQL; rerun on Python files only passed. SQL migration correctness is covered by the migration tests above.

### 2026-09-16 — A3 Kubernetes deployment, migration CLI, readiness and stateless smoke
- Tasks completed: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7.
- Code/docs changed:
  - `deploy/kubernetes/deeptutor-backend.yaml`
  - `deeptutor_cli/migration.py`
  - `deeptutor/api/contracts/turn_protocol.py`
  - `deeptutor/app/container.py`
  - `docs/postgresql-runtime-runbook.md`
  - `docs/enterprise/04-kubernetes-postgresql-architecture.md`
  - `docs/enterprise/06-postgresql-native-store-plan.md`
  - `docs/enterprise/07-resource-isolation.md`
  - `docs/enterprise/13-deployment-and-upstream-sync.md`
  - `tests/runtime/test_kubernetes_manifests.py`
  - `tests/cli/test_data_migration_cli.py`
  - `tests/api/test_runtime_status_externalized.py`
  - `tests/persistence/postgres/business/test_kubernetes_stateless_smoke.py`
- Implemented/verified behavior:
  - Added a Kubernetes backend manifest example with no writable persistent `data/` PVC authority, `emptyDir` scratch, read-only config projection, ConfigMap/S3-compatible config, Secret/ExternalSecret env refs, and readiness probe.
  - Added `deeptutor migration data inventory` for read-only `data/` scanning with hashes, provider decisions, sensitive-field redaction, symlink escape blocking, and no source mutation.
  - Extended runtime status to include redacted provider summaries, data-gate summary, cleanup backlog field and migration version.
  - Added K8s-like stateless smoke: one “Pod” writes PG session, ObjectStore attachment, reading/workspace/persona/skill/notebook/KB resources, runtime settings and policy rows; local `data/` is removed; a second “Pod” reads all state through PG/ObjectStore without shared PVC.
  - Added dual-pod consistency evidence through two independent PG store instances sharing only PG/ObjectStore.
  - Updated runbook/enterprise docs with local-dev vs production mode, S3/Secret config, migration steps, rollback caveats, no-PVC rule, resource metadata and cleanup boundaries.
  - Built final wheel artifact successfully: `deeptutor-1.6.7-py3-none-any.whl` in `/tmp/deeptutor-build-a3-*`.
- RED/GREEN evidence:
  - Kubernetes manifest test first failed with missing `deploy/kubernetes/deeptutor-backend.yaml`; manifest added and test passed.
  - Data migration CLI tests first failed because `migration data` did not exist; added inventory command. Symlink test was adjusted to assert source body redaction rather than macOS `/private` temp path text.
  - Runtime status test first failed because `RuntimeStatus` rejected externalized provider/status fields; model and container report were extended.
  - Stateless smoke first failed due a test SQL placeholder mismatch; corrected fixture SQL and passed.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/runtime/test_kubernetes_manifests.py` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/cli/test_data_migration_cli.py` → 2 passed.
  - `.venv/bin/python -m pytest -q tests/api/test_runtime_status_externalized.py` → 1 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_kubernetes_stateless_smoke.py` → 1 passed.
  - `.venv/bin/python -m ruff check deeptutor_cli/migration.py tests/cli/test_data_migration_cli.py tests/runtime/test_kubernetes_manifests.py tests/persistence/postgres/business/test_kubernetes_stateless_smoke.py deeptutor/api/contracts/turn_protocol.py deeptutor/app/container.py tests/api/test_runtime_status_externalized.py` → passed.
  - `.venv/bin/python -m pytest -q tests/runtime/test_kubernetes_manifests.py tests/cli/test_data_migration_cli.py tests/api/test_runtime_status_externalized.py tests/persistence/postgres/business/test_kubernetes_stateless_smoke.py` → 5 passed.
  - `.venv/bin/python -m build --wheel --outdir /tmp/deeptutor-build-a3-...` → built `deeptutor-1.6.7-py3-none-any.whl`; warnings were packaging deprecations / missing web asset glob, not build failures.
- Not claimed:
  - No production cluster was modified and no image was pushed. Manifest and wheel are local artifacts; real cutover/deploy remains an operator action.

### 2026-09-16 — B/C/H governance, migration-scope, UI and single-executor closure
- Tasks completed: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, H.1, H.2, H.3.
- Code/docs changed:
  - `deeptutor/persistence/postgres/migrations/0014_externalized_runtime.sql`
  - `deeptutor/persistence/postgres/migrations/runner.py`
  - `deeptutor/persistence/postgres/governance.py`
  - `deeptutor/persistence/postgres/object_resources.py`
  - `deeptutor/api/routers/governance.py`
  - `deeptutor/api/main.py`
  - `deeptutor_cli/migration.py`
  - `deploy/kubernetes/deeptutor-backend.yaml`
  - `web/app/tms/page.tsx`
  - `web/app/oms/page.tsx`
  - `docs/postgresql-runtime-runbook.md`
  - New/updated tests under `tests/persistence/postgres/business/`, `tests/cli/`, `tests/api/`, `tests/runtime/`.
- Implemented/verified behavior:
  - Added PG `runtime_audit_events` with tenant RLS and migration catalog verification; settings/Secret/object create/delete governance events are redacted and queryable.
  - Added `RuntimeGovernanceStore` for PG-backed TMS/OMS configuration state (`saved`/`active`/`failed`/`draining` schema states), Secret references, redacted audit events and tenant-scoped usage/cleanup summaries.
  - Added `/api/v1/tms/settings/*` and `/api/v1/oms/{secrets,audit,usage}` routes gated by `tenant_admin` auth. Ordinary users receive 403; tenant scope comes from the authenticated PG store, not URL/query/body tenant overrides.
  - Extended generic ObjectStore resource lifecycle to audit object create/delete-request events without file bodies or Secret values.
  - Extended offline `migration data inventory` report with `source_id`, deterministic `source_fingerprint`, target tenant, owner mapping, object prefix and replay blocking by expected fingerprint.
  - Added `/tms` and `/oms` UI entry pages that surface managed/locked/draft/active/failed status language, Secret-reference/readiness boundaries and OMS redaction constraints.
  - Tightened the K8s example for single-executor/non-HA mode: `replicas: 1`, `strategy: Recreate`, `DEEPTUTOR_EXECUTION_MODE=single`; docs record that HA/RPO/RTO or competing workers remain blocked until G-H evidence exists.
- DB migration evidence:
  - `0014_externalized_runtime.sql` now includes `runtime_audit_events`; runtime catalog and empty DB apply/concurrent migration tests passed.
- Permissions and negative tests:
  - Governance API test proves tenant admin can write/read redacted governance state and ordinary user cannot write TMS settings.
  - Existing and rerun ObjectStore/resource tests cover cross-owner/foreign tenant denial before ObjectStore read, same suffix isolation, local-path forgery rejection and cleanup not crossing tenant/owner boundaries.
  - Audit and usage surfaces assert private file body and Secret-shaped values do not appear.
- Provider/readiness and failure-drill evidence:
  - ObjectStore partial failures are exercised through delete failure + retryable cleanup jobs; S3-compatible live smoke was already recorded in A2.2.
  - PG interruption/fail-closed surfaces are represented by migration/readiness/status tests and no-local-fallback/data-gate tests.
  - Secret provider delay/missing/version mismatch remains simulated through Secret reference and redaction contracts; no live Vault/ExternalSecret backend was modified.
  - Pod eviction/local disk loss and dual-pod read consistency were exercised in the A3 K8s-like stateless smoke.
- H boundary evidence:
  - This proposal does not enable multi-executor/HA mode. H.1/H.2 are closed as conditional gates by documenting and testing that the supplied deployment remains single-executor/non-HA and refuses to claim HA. H.3 is closed by the Recreate/single-executor manifest and runbook operator confirmation requirements.
- Verification run in this slice:
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_governance.py` → 2 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py` → 9 passed.
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent` → 2 passed.
  - `.venv/bin/python -m pytest -q tests/cli/test_data_migration_cli.py` → 3 passed.
  - `.venv/bin/python -m pytest -q tests/runtime/test_kubernetes_manifests.py tests/runtime/test_tms_oms_frontend_contract.py` → 2 passed.
  - `.venv/bin/python -m pytest -q tests/api/test_canonical_route_surface.py::test_only_canonical_transport_and_resource_routes_are_registered` → 1 passed.
  - Targeted Ruff checks for changed governance/object-resource/API/CLI/runtime test files → passed.
- Not claimed / production boundary:
  - No real production tenant data was imported, no cluster was modified, no image was pushed and no HA/RPO/RTO target is claimed.
  - Live ExternalSecret/Vault, LightRAG internal restore and real production ObjectStore outage drills remain operator-environment exercises; this change supplies contracts, local/k8s-like smoke, redaction and fail-closed tests.

### 2026-09-16 — Final OpenSpec verification pass
- OpenSpec task progress: 41/41 complete; `openspec instructions apply --change externalize-data-directory-for-kubernetes-runtime --json` reported `all_done`.
- OpenSpec validation: `openspec validate externalize-data-directory-for-kubernetes-runtime --strict` → passed.
- Targeted externalized-runtime regression matrix:
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_governance.py tests/persistence/postgres/business/test_externalized_object_resources.py tests/persistence/postgres/business/test_externalized_turn_attachments.py tests/persistence/postgres/business/test_externalized_session_resources.py tests/persistence/postgres/business/test_session_resources.py tests/persistence/postgres/business/test_session_resource_races.py tests/persistence/postgres/business/test_kubernetes_stateless_smoke.py tests/api/test_http_provider_context.py tests/api/test_runtime_status_externalized.py tests/api/test_canonical_route_surface.py::test_only_canonical_transport_and_resource_routes_are_registered tests/cli/test_data_migration_cli.py tests/runtime/test_kubernetes_manifests.py tests/runtime/test_tms_oms_frontend_contract.py tests/runtime/test_kubernetes_data_gate.py tests/runtime/test_s3_object_store.py tests/runtime/test_externalized_provider_seams.py tests/persistence/postgres/test_externalized_runtime_schema.py tests/persistence/postgres/test_migrations.py::test_empty_database_apply_is_repeatable_and_concurrent tests/services/test_path_service.py tests/persistence/postgres/test_configuration.py` → 101 passed, 2 skipped.
- Lint/type/build:
  - Targeted Ruff on changed Python and tests → passed.
  - `cd web && npm run typecheck` → passed.
  - `.venv/bin/python -m build --wheel --outdir /tmp/deeptutor-build-final-*` → built `deeptutor-1.6.7-py3-none-any.whl`; warnings were existing setuptools/license/web asset discovery warnings, not build failures.
- Additional verification note:
  - An earlier wider ad-hoc command that also included `tests/persistence/postgres/test_accounts.py` and `tests/api/test_default_pg_auth.py` failed during setup with pytest/async-fixture hook errors before exercising assertions; those files were not used as final evidence for this change. The final externalized-runtime matrix above passed.
- Production boundary remains unchanged:
  - No production cluster, registry, real tenant data, ExternalSecret/Vault backend or production ObjectStore was changed. Real cutover/deploy/archive still requires separate authorization.

### 2026-09-16 — Post-completion correction: DeepTutor dynamic skills/personas no longer use Pod-local authority
- Trigger: 用户追问 DeepTutor `SKILL` 是否存本地以及目标 K8s 是否会出问题；复查发现 `SkillService`/`PersonaService` 文档与默认实现仍指向 `data/user/workspace/{skills,personas}`，与已勾选任务 2.5/3.4/7.5 的生产无状态要求不一致。
- OpenSpec artifacts updated:
  - `proposal.md` 增加 dynamic skill/persona 本地权威缺口修正与全 `data/` 读写排查口径。
  - `tasks.md` 增加第 8 节 post-completion correction 并记录 8.1–8.4。
- Code changed:
  - 新增 `deeptutor/services/skill/externalized.py`：用户创建与 hub 导入 skill package 存为 ObjectStore package JSON，PG `enterprise.resource_objects` 负责 tenant/owner visibility/lifecycle；支持 `SKILL.md`、`references/*`、manifest、`read_skill`、tags、hub provenance、update/delete。导入时沿用原 import gate，并剥离 `always`。
  - 新增 `deeptutor/services/persona/externalized.py`：动态 persona 正文使用 ObjectStore package + PG metadata，turn context 不依赖 Pod 本地 persona 文件。
  - 新增 runtime selectors `deeptutor/services/skill/runtime.py` 与 `deeptutor/services/persona/runtime.py`：当 request/provider context 绑定 PG store + ObjectStore 时使用外置服务；production/kubernetes 缺 provider 时 fail closed，不回退本地 `data/`。
  - `read_skill` tool、turn executor、skills/personas API 改为 runtime provider；local-dev 仍保留原文件型服务，builtin skills/presets 仍为镜像内只读资源。
  - `deeptutor/runtime/data_gate.py` 增加显式 `skills=user/workspace/skills`、`personas=user/workspace/personas` forbidden-authority entries，避免 nested path 被泛化为普通 workspace。
- Data directory scan performed:
  - 扫描直接 `data/` 字符串、`get_path_service()`/`get_admin_path_service()`、`PathService` workspace/settings/notebook/memory/KB/book/co-writer/runtime/cache/log helpers、partner workspace copy、settings/model/grants、RAG/KB pipeline、artifact/workspace outputs 等路径。
  - 本次修正覆盖本轮确认的 dynamic skills/personas 权威缺口；其它路径已由既有 inventory 中 settings/system/owner_resources/workspace/notebooks/knowledge_bases/memory/partners/runtime_state/logs/parse_cache/offline_import_input 分类覆盖，或属于 local-dev/cache/scratch/offline import/builtin read-only。后续若这些路径在 production 被配置为 local authority，data gate/entrypoint tests 必须阻断。
- Migration assessment:
  - No new PostgreSQL schema migration required: reused `enterprise.resource_objects` and existing ObjectStore metadata schema.
  - No OpenFGA or Keycloak migration required.
- RED/GREEN evidence:
  - New externalized skill/persona tests first failed with missing modules and missing inventory entries; implementation added PG/ObjectStore-backed services and inventory entries.
  - New runtime integration tests first failed with missing runtime selector modules; implementation added selectors and wired `read_skill`.
  - New static entrypoint test first failed because turn/API still called local services; implementation wired runtime providers.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_skills_personas.py tests/persistence/postgres/business/test_externalized_skill_runtime_integration.py tests/runtime/test_kubernetes_data_gate.py tests/runtime/test_externalized_dynamic_resource_entrypoints.py tests/services/skill/test_skill_service_v2.py tests/services/persona/test_persona_service.py tests/services/skill/test_skill_hub.py tests/services/skill/test_read_skill_error_messages.py tests/api/test_skills_hub_router.py tests/api/test_canonical_route_surface.py::test_only_canonical_transport_and_resource_routes_are_registered tests/runtime/test_kubernetes_manifests.py` → 64 passed, 1 warning.
  - `.venv/bin/python -m ruff check deeptutor/services/skill/externalized.py deeptutor/services/persona/externalized.py deeptutor/services/skill/runtime.py deeptutor/services/persona/runtime.py deeptutor/tools/builtin/__init__.py deeptutor/services/session/turns/executor.py deeptutor/api/routers/skills.py deeptutor/api/routers/personas.py deeptutor/runtime/data_gate.py tests/persistence/postgres/business/test_externalized_skills_personas.py tests/persistence/postgres/business/test_externalized_skill_runtime_integration.py tests/runtime/test_externalized_dynamic_resource_entrypoints.py tests/runtime/test_kubernetes_data_gate.py` → passed after import-order auto-fix.
- Additional verification note:
  - An additional broader ad-hoc command including `tests/api/test_partners_router.py` failed because those partner tests attempted to build the default PG application container without `DEEPTUTOR_POSTGRES_CONFIG` and raised `postgres_config_missing`; this was not used as evidence for this correction.
- Not claimed:
  - No real production data was migrated, no bucket/cluster was changed, no image was pushed. Legacy local skill/persona files still require the already-scoped offline inventory/import flow before production cutover.

### 2026-09-16 — Post-completion correction: deleting `data/` no longer removes tenant-admin permissions
- Trigger: 用户本地验证发现删除 `data/` 后，PG 默认管理员仍可登录但进入 Admin/Settings 后表现为无权限；复现显示 `/api/auth/status` 已返回 `tenant_admin`/`is_admin=true`，但 `/api/settings/catalog` 被后端按 legacy `CurrentUser.is_admin` 判定为非管理员并返回 403，同时 grants 分配目标仍可能从 `data/system/auth/users.json` 查找。
- Root cause:
  - DeepTutor 当前有两类“管理员”语义：legacy local `admin` 代表本地 `data/user` 文件工作区管理员；PG `tenant_admin` 代表租户/部署级管理员。前端和 auth token 已采用 `tenant_admin`，但 settings、tool policy、skills/personas/partners/system 等部分后端路径仍只检查 legacy `user.is_admin`。
  - `multi_user.grants` 在 PG provider 绑定时仍依赖 `data/system/grants/*.json` 与本地身份 JSON fallback，导致删除 `data/` 后授权/分配目标丢失或变为空授权。
  - 默认 Content Workspace 被当作必须已存在的本地目录；删除 `data/user/workspace` 后 turn runtime 会因默认 workspace 不存在而失败。
  - 本地 `DEEPTUTOR_POSTGRES_CONFIG` 与默认配置路径仍指向 `data/user/settings/postgres.json`；删除 `data/` 后 backend startup 先因 `postgres_config_missing` 失败，说明 PG 部署配置本身也不应以 deletable `data/` 为默认位置。
- Code changed:
  - 新增 `deeptutor/multi_user/roles.py`，用 `can_manage_deployment()` 明确表达部署级管理员权限，用 `is_grant_restricted_user()` 明确普通用户 per-user grant 约束；settings/system/skills/personas/partners/tool access/turn executor/read_skill 等入口改用该语义。
  - `deeptutor/services/config/settings_draft.py` 的 tenant-admin draft 解析不再落入当前 tenant local path；settings draft/readiness 页面入口使用部署/admin scope，避免 `local path service is unavailable for this scope` 500。
  - `deeptutor/multi_user/grants.py` 在 provider context 绑定 PostgreSQL runtime 时，从 `enterprise.users` 解析用户、从 `enterprise.runtime_policies(policy_kind='user_grant')` 读写 grants；本地 `data/system/grants` 只保留为未绑定 PG 的 local-dev fallback。
  - `deeptutor/api/routers/multi_user.py` 的 assignment target 改用 PG-aware `grant_subject_record()`，避免 `data/system/auth/users.json` 删除后 PG 用户无法被分配。
  - `deeptutor/services/workspace/service.py` 允许默认 workspace/projection 在本地盘清空后重建；非默认自定义 workspace 仍保持缺失即报错。
  - `deeptutor/app/postgres_runtime.py` 将默认 PG 部署配置路径改为 runtime home 的 `config/postgres.json`；`.env.example` 和 `docs/postgresql-runtime-runbook.md` 改为推荐 `/etc/deeptutor/postgres.json` 或 `config/postgres.json`，不再推荐 `data/user/settings/postgres.json`。
- Migration assessment:
  - No new PostgreSQL schema migration required: reused existing `enterprise.runtime_policies` and `enterprise.users`.
  - No OpenFGA or Keycloak migration required.
  - Frontend permission key/contract unchanged: frontend already consumes `is_admin=true` for `tenant_admin`; this slice fixes backend parity.
- Permission matrix:
  - Settings/model catalog/admin runtime APIs → backend `can_manage_deployment()` / existing `require_admin` where token-gated → PG role `tenant_admin` or legacy local `admin` where applicable → no OpenFGA/Keycloak/default-role migration → existing admin/settings UI keys.
  - Per-user grants assignment → `require_admin` + PG-aware `grant_subject_record()`/`runtime_policies` → PG `tenant_admin` managing same-tenant users → no OpenFGA/Keycloak migration → existing admin users/grants UI.
  - Tool/skill/persona/partner runtime availability → `is_grant_restricted_user()` only for ordinary users → PG `tenant_admin` unrestricted for deployment resources, ordinary users restricted by PG grant → existing surfaces.
- RED/GREEN evidence:
  - `tenant_admin` settings test first failed because `/api/settings/catalog` treated PG admin as non-admin; implementation added deployment-admin helper and wired settings/catalog/llm-options/draft paths.
  - Tool access test first failed because PG `tenant_admin` attempted to load local grants; implementation made deployment admins unrestricted.
  - PG-backed grants tests first failed because `save_grant` and assignment target could not resolve PG users without local `data/system/auth/users.json`; implementation added PG user/grant storage.
  - Workspace regression first failed with `WorkspaceError: The selected workspace folder does not exist.` after deleting the default workspace; implementation recreated only default workspace roots.
  - Default PG config path tests first failed because `default_postgres_config_path()` returned `data/user/settings/postgres.json` and `load_default_postgres_config()` failed after `data/` deletion; implementation moved the default to `config/postgres.json`.
  - Tenant-admin draft test first failed with `RuntimeError: local path service is unavailable for this scope`; implementation resolved settings draft through deployment/admin scope instead of tenant local path.
- Verification run:
  - `.venv/bin/python -m pytest -q tests/multi_user/test_grants_and_settings.py tests/multi_user/test_tool_access.py tests/persistence/postgres/business/test_pg_backed_grants.py tests/services/workspace/test_content_workspace.py::test_default_workspace_is_recreated_after_runtime_data_is_deleted tests/api/test_unified_ws_turn_runtime.py::test_turn_runtime_tenant_admin_uses_deployment_default_without_grant tests/api/test_default_pg_runtime.py::test_default_pg_config_path_is_outside_deletable_data_directory tests/api/test_default_pg_runtime.py::test_default_pg_config_can_survive_runtime_data_deletion` → 20 passed.
  - `.venv/bin/python -m ruff check deeptutor/multi_user/roles.py deeptutor/api/routers/settings.py deeptutor/services/config/settings_draft.py deeptutor/multi_user/tool_access.py deeptutor/services/session/turns/executor.py deeptutor/tools/builtin/__init__.py deeptutor/multi_user/skill_access.py deeptutor/multi_user/partner_access.py deeptutor/api/routers/partners.py deeptutor/api/routers/system.py deeptutor/api/routers/skills.py deeptutor/api/routers/personas.py deeptutor/multi_user/grants.py deeptutor/api/routers/multi_user.py deeptutor/services/workspace/service.py deeptutor/app/postgres_runtime.py tests/multi_user/test_grants_and_settings.py tests/multi_user/test_tool_access.py tests/persistence/postgres/business/test_pg_backed_grants.py tests/services/workspace/test_content_workspace.py tests/api/test_default_pg_runtime.py` → passed.
  - `openspec validate externalize-data-directory-for-kubernetes-runtime --strict` → passed.
  - `openspec instructions apply --change externalize-data-directory-for-kubernetes-runtime --json` → 50/50 tasks complete, `all_done`.
- Not claimed:
  - This correction does not migrate legacy model API Secret plaintext from deleted local files. Production model credentials still follow the Secret-reference provider rules in this proposal. If an operator deletes local-only model files before importing/Secret-mapping them, the Secret material is intentionally not reconstructed from PG.

### 2026-09-16 — Post-completion correction: knowledge base/LightRAG remains usable after `data/` deletion
- Trigger: 用户继续本地验证发现“知识库完全无法使用”。复现显示当前默认 KB `test` 是 `lightrag-server` 外部连接，后端按外部资源只读语义拒绝上传/建文件夹（409），但列表 API 返回 `read_only=false`，导致前端开放本地写入口；同时旧前端 bundle/cache 仍可能请求 `/api/knowledge-bases/upload-policy` 并被动态 `/{kb_name}` 路由误判；删除 `data/` 后新 pytest/新进程导入 `knowledge.py` 还会因缺失 legacy `main.yaml` 直接失败。
- Code changed:
  - `deeptutor/services/config/loader.py`：`load_config_with_main("main.yaml")` / async variant 在文件缺失时返回空 runtime config 并注入 canonical runtime paths，不写回 `data/`；未知非 main YAML 仍抛 `FileNotFoundError`。
  - `deeptutor/api/routers/knowledge.py`：新增 `/api/knowledge-bases/upload-policy` 兼容别名，返回与 `/supported-file-types` 相同的 upload policy；`list_knowledge_bases()` 对 metadata/info 中的 connected KB type 使用 `is_connected_kb()` 标记 `read_only=true`。
  - `tests/api/test_knowledge_router.py`：新增 legacy upload-policy alias 与外部 connected KB read-only 回归；相关多用户路由测试补充显式 current user context，符合当前 PG/multi-user API 前提。
  - `tests/services/test_config_loader.py`：新增缺省 `main.yaml` 契约测试，并更新 explicit project root 测试为验证 runtime paths 而非要求 legacy YAML 本地存在。
- Local runtime remediation:
  - 保留现有外部连接 `test`（`rag_provider=lightrag-server`，remote server pointer），不删除或迁移其远端资源。
  - 通过本地 API 创建可写托管 KB `local-lightrag`（`rag_provider=lightrag`，无初始文档）并设为默认；该 KB 用于 DeepTutor 内上传/索引，外部 `test` 在重启后将显示只读。
  - LightRAG preflight 仍使用前一轮配置：native `lightrag` package installed，chat model/embedding model configured；未输出 API key/Secret。
- RED/GREEN evidence:
  - 新 `test_load_config_with_main_treats_missing_main_as_empty_runtime_config` 首次失败于 `FileNotFoundError: main.yaml`；实现后通过。
  - 新 `test_upload_policy_legacy_alias_returns_supported_file_types` 首次返回 500/动态路由误判；新增 alias 后通过。
  - 新 `test_list_marks_external_connected_kbs_read_only` 首次得到 `read_only=false`；列表标记 connected KB 后通过。
- Verification run:
  - `source .local/deeptutor-dev/env.sh && .venv/bin/pytest tests/services/test_config_loader.py -q` → 5 passed.
  - `source .local/deeptutor-dev/env.sh && .venv/bin/pytest tests/api/test_knowledge_router.py::test_supported_file_types_returns_upload_policy tests/api/test_knowledge_router.py::test_supported_file_types_can_delegate_all_extensions tests/api/test_knowledge_router.py::test_upload_policy_legacy_alias_returns_supported_file_types tests/api/test_knowledge_router.py::test_list_reuses_manager_config_snapshot tests/api/test_knowledge_router.py::test_list_marks_external_connected_kbs_read_only tests/api/test_knowledge_router.py::test_remote_kb_file_listing_is_empty_without_creating_local_storage tests/api/test_knowledge_router.py::test_remote_kb_rejects_local_file_operations_without_creating_storage -q` → 12 passed, 1 warning.
- Migration assessment:
  - No new PostgreSQL schema migration required.
  - No OpenFGA or Keycloak migration required.
  - No additional concrete storage product matrix added; persistent file requirements remain PostgreSQL + S3-compatible ObjectStore + Secret/Settings provider.
- Not claimed:
  - This correction does not migrate documents from the external `test` LightRAG Server into DeepTutor; external connections remain pointers. If the user wants DeepTutor-managed uploads, use the new `local-lightrag` KB or run an explicit import.

### 2026-09-16 — Follow-up UI correction: connected KB Files/Add Documents panels honor `read_only`
- Trigger: 用户仍在 `/knowledge-bases/test` 触发 `Knowledge base 'test' is connected to an external resource and is read-only...`。HTTP 验证显示 `/api/knowledge-bases` 已返回 `test read_only=true`，但 dev server 日志显示前端仍从 Files 面板发起 `POST /api/knowledge-bases/test/folders`。
- Root cause:
  - 后端与列表 API 已正确标记外部 `lightrag-server` KB 为只读，但 `KbFilesTab` 没有把 `kb.read_only` 传给 `KbDocumentList`。
  - `KbDocumentList` 没有 `readOnly` prop，因此始终展示新建文件夹、拖拽移动、删除等本地文件写入口。
  - Add Documents 上传判定 `kbCanUploadDocuments()` 没有检查 `kb.read_only`，虽然 detail wrapper 会 no-op，但 UI 仍可能误导用户。
- Code changed:
  - `web/components/knowledge/KbFilesTab.tsx`：向 `KbDocumentList` 传递 `readOnly={kb.read_only}`。
  - `web/components/knowledge/KbDocumentList.tsx`：新增 `readOnly` prop；只读时隐藏 New folder、move/delete controls，禁用 drag/drop 写操作，并显示外部资源只读提示。
  - `web/lib/knowledge-helpers.ts`：`kbIsUploadable()` / `kbCanUploadDocuments()` 在 `kb.read_only` 时始终返回 false。
  - 新增 `web/tests/kb-document-list-readonly.spec.tsx`，并扩展 `web/tests/lightrag-indexing-model.test.ts` 的 read-only 上传判定回归。
- RED/GREEN evidence:
  - `cd web && npm run test:unit -- tests/kb-document-list-readonly.spec.tsx` 首次失败：只读渲染仍存在 `New folder` button；实现后通过。
  - `cd web && npm run test:node` 首次显示新增 `read-only knowledge bases never accept local uploads` 失败；实现后该子测试转为 `ok`。
- Verification run:
  - `cd web && npm run test:unit -- tests/kb-document-list-readonly.spec.tsx` → 1 passed.
  - `cd web && npm run typecheck` → passed.
  - `cd web && npm run test:node` → 新增 read-only 子测试已通过；该全量命令仍有 1 个既有架构测试失败：`the frontend has no retired transport, URL, or compatibility surface`，与本轮 connected-KB read-only UI 修正无关，未作为本修正完成证据。
- Migration assessment:
  - No PostgreSQL schema migration, OpenFGA migration, Keycloak migration or storage-provider change required.
