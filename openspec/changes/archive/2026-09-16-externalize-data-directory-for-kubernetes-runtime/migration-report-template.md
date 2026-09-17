# Data Directory Migration Report Format

用于 `data/` 文件与 settings 离线 inventory / plan / import / verify / report。报告只能包含脱敏 metadata、hash、Secret 引用和错误 code；不得包含 Secret 明文、长期下载 URL 或私有文件正文。

## Report metadata
- Report schema: `deeptutor.data-migration-report/v1`
- Change ID: `externalize-data-directory-for-kubernetes-runtime`
- Mode: `inventory | plan | import | verify`
- Source fingerprint:
- Source root:
- Generated at:
- Operator:
- Target tenant:
- Target provider summary:
  - PostgreSQL schema version:
  - ObjectStore provider:
  - Settings provider:
  - Secret provider:

## Source inventory row
| Field | Required | Notes |
| --- | --- | --- |
| `source_path` | yes | Relative to frozen source root; reject path escape and symlink traversal. |
| `source_kind` | yes | `settings`, `system`, `postgres-resources`, `workspace`, `notebook`, `knowledge_base`, `memory`, `partner`, `log`, `runtime`, etc. |
| `category` | yes | One of `forbidden-authority`, `externalized`, `projection`, `scratch`, `cache`, `offline-import-input`, `local-dev-only`. |
| `sha256` | files only | Hash computed from read-only source bytes. |
| `size_bytes` | files only | Source byte length. |
| `owner_source` | when known | Legacy owner/user identifier; never inferred from arbitrary path alone. |
| `tenant_target` | when mapped | Target tenant ID or explicit unresolved marker. |
| `owner_target` | when mapped | Target owner ID or explicit unresolved marker. |
| `sensitive_fields` | settings only | Field names/classes only, never values. |
| `decision` | yes | `import`, `skip`, `block`, `manual-secret-map`, `local-dev-only`. |
| `reason_code` | yes | Stable machine-readable reason. |

## Plan/import target row
| Field | Required | Notes |
| --- | --- | --- |
| `source_path` | yes | Must match inventory row. |
| `target_provider` | yes | `postgres`, `objectstore`, `settings-provider`, `secret-provider`, `projection`, `skip`. |
| `target_table` | when PG | Example: `enterprise.resource_objects`, `enterprise.runtime_settings`. |
| `object_bucket` | when object | Bucket alias only if safe; no credentials. |
| `object_key` | when object | Backend-generated key; must include tenant/owner namespace or opaque UUID prefix. |
| `object_sha256` | when object | Must equal source hash after upload. |
| `secret_reference` | when secret | Reference name/version only, e.g. `env:MODEL_API_KEY@v3`; no values. |
| `reference_rewrites` | when needed | Business references updated from local path to resource handle. |
| `state` | yes | `planned`, `imported`, `verified`, `blocked`, `failed`. |
| `error_code` | on failure | Sanitized. |

## Blocking conditions
- Unknown owner/tenant mapping.
- Source hash drift between inventory and import.
- Symlink/path escape or non-regular file where a regular file is required.
- Secret plaintext without explicit Secret provider mapping.
- Target conflict not covered by idempotent replay rules.
- Cross-tenant object prefix or PG reference mismatch.
- Attempt to import `scratch`, `cache`, or `local-dev-only` as production authority.

## Verification summary
- Row counts by category and target provider.
- Bytes by resource kind.
- Imported object count and total bytes.
- PG metadata rows inserted/updated/skipped.
- Secret mappings required / provided / missing.
- Authorization-path read checks passed/failed.
- Old local path fallback negative checks passed/failed.
- Dangling/pending cleanup jobs created.
- Manual operator confirmations required.

## Redaction requirements
- No DSN, API key, token, cookie/signing/auth epoch secret, ObjectStore access key, or long-lived URL.
- No private file body, notebook body, prompt/persona body, or model response content in generic reports.
- Error messages must use stable codes and bounded sanitized details.
