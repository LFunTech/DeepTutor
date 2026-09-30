# 执行证据

## 2026-09-28 任务 1.1 descriptor 与执行者矩阵

- 重新运行 `extensions/enterprise/frontends/scripts/generate-provider-descriptors.py`，更新 OMS provider descriptor 快照到当前 DeepTutor settings 源码；随后 `--check` 通过。
- 当前快照覆盖：LLM 40、task 40、embedding 13、search 18、TTS 9、STT 9、imagegen 8、videogen 3 个候选，以及 37 个 connection target。新增/同步差异包括 Cheaper Inference、Unifically、Lemonade embedding、Volcengine Speech TTS/STT。
- 新增 `service-provider-settings-matrix.md`，把服务字段、条件规则、真实执行者加载点、计费测试边界和未支持门禁逐项固定。矩阵明确：搜索无模型列表、task 回退不免费、RAG/LightRAG 不直连内部 PG/图、外部 Agent/工具未有稳定 adapter/usage 合同时保持 unsupported、个人偏好不提升为平台 Provider。
- 该任务是清单与 descriptor 对齐，不代表配置版本化迁移、正式写 API、逐执行者确认或真实可计费测试已完成；这些仍归 1.3、2.1–2.4、3.x。

## 2026-09-28 验证

- `generate-provider-descriptors.py --check` 通过，确认 OMS provider descriptor 快照与当前 DeepTutor settings 源码一致。
- 前端全量 `npm test` → **250 passed / 25 files**；OMS/TMS typecheck 与 lint 均通过。
- 企业后端全量 **761 passed、3 skipped**；OpenSpec 全量 strict **30 passed、0 failed**。

## 2026-09-28 任务 1.3：PG 配置事实迁移与旧 JSON dry-run

完成内容：

- 新增 `oms/0019_provider_settings_configs.sql`，为全服务 Provider/执行者设置建立三类 OMS 事实表：
  - `oms.provider_setting_configs`：草稿/active、版本、descriptor version 和状态事实；
  - `oms.provider_setting_confirmations`：逐目标执行者确认结果与脱敏摘要；
  - `oms.provider_setting_import_dry_runs`：旧 JSON 映射 dry-run 的来源、hash 与脱敏结果。
- 迁移只定义表和索引，不新增 DB 函数、触发器、PostgreSQL ENUM 或枚举型 `CHECK`；业务状态、服务 key、确认语义、Secret ref 和 JSON 结构均由 DeepTutor 应用层校验。
- 新增 `deeptutor_enterprise.oms.provider_settings`：
  - `build_provider_settings_dry_run()` 将本地 JSON 设置按当前服务 section 做受控 dry-run；
  - 识别 connections/models/task_models/embedding/search/TTS/STT/image/video/解析/RAG/external_agents/tools 等顶层 section；
  - 对 `secret`、`api_key`、`client_secret`、`access_key` 等字段做路径级脱敏，只记录 `secret_paths`，不输出明文；
  - `record_provider_settings_dry_run()` 将 canonical hash 与脱敏结果写入 PG，供后续 OMS 草稿迁移确认。
- 更新企业 MigrationRunner 的 OMS schema drift 校验，纳入新表和索引；更新迁移清单测试。

验证：

- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_oms_ledger_migration.py::test_new_oms_migrations_have_no_database_business_routines_or_enum_checks extensions/enterprise/tests/test_oms_ledger_migration.py::test_oms_ledger_migration_is_versioned_and_repeatable extensions/enterprise/tests/test_oms_ledger_migration.py::test_provider_settings_dry_run_is_versioned_and_redacts_legacy_json --tb=short` → 3 passed。
- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/oms/provider_settings.py extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py extensions/enterprise/tests/test_oms_ledger_migration.py` → passed。

限制：

- 本切片只完成 PG 事实结构与 legacy JSON dry-run；尚未开放正式 OMS 写 API/前端、逐服务真实探针、逐实例确认和回退状态机，因此任务 2.1–3.2 不因本项完成。
- 未修改 EduPlus2、Keycloak 或 OpenFGA；OMS `ops.*` 授权仍由 DeepTutor Enterprise 程序判定。

## 2026-09-28 任务 2.1/2.2：OMS Provider 设置正式读写 API 与权限负例

完成任务：2.1、2.2。

实现内容：

- 扩展 `deeptutor_enterprise.oms.provider_settings` 为正式配置服务层：
  - `save_provider_settings_draft()`：保存全服务配置草稿，应用层校验 section 白名单、HTTPS endpoint、Secret 只能为 `env:` 引用；
  - `test_provider_settings()` / `publish_provider_settings()`：逐目标执行者确认 Secret ref 可解析，并支持 `oms_provider_settings_confirmation_hook` 做 backend/canary 等实例确认；
  - `rollback_provider_settings()`：执行者失败后丢弃坏草稿，恢复 desired 到旧 active；
  - `read_provider_settings()`：返回脱敏 desired/active、安全 secret path，不回显 Secret ref 或明文。
- 新增独立 OMS HTTP API：
  - `GET /api/v1/oms/provider-settings`；
  - `POST /api/v1/oms/provider-settings/dry-run`；
  - `POST /api/v1/oms/provider-settings/draft`；
  - `POST /api/v1/oms/provider-settings/test`；
  - `POST /api/v1/oms/provider-settings/publish`；
  - `POST /api/v1/oms/provider-settings/rollback`。
- API 统一通过 `ops.providers.read/manage` 和 `ops.oms.access` 进行 DeepTutor Enterprise 本地授权；auditor/security-only 角色无写权限，租户 token/伪造 header 仍由 OMS middleware/PEP 拒绝。
- 失败路径：明文 Secret 422、旧版本草稿 409、无写权限 403、缺失 Secret 发布 503 且保留旧 active；rollback 后 active 仍为上一已确认版本。审计只写 section/status/confirmed executors 等安全摘要。
- 企业装配 route allowlist 已显式纳入新 OMS provider-settings API，并继续拒绝旧云端管理旁路；本地 Web settings 不因本 API 改动被删除或替换。

验证：

- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_provider_settings_are_versioned_redacted_confirmed_and_permissioned extensions/enterprise/tests/test_application.py::test_enterprise_management_route_allowlist_is_narrow --tb=short` → 2 passed。
- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/oms/provider_settings.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py` → passed。

限制：

- 本轮确认的是应用层配置状态机和 OMS API；尚未为每个真实服务 adapter 完成可计费探针、学校服务准入、逐服务 usage/attempt 核对，因此 2.3、2.4、3.x 仍未完成。
- 不修改 EduPlus2、Keycloak、OpenFGA 或外部 repo。

## 2026-09-30 Provider 设置正式 UI 接线与本地回归同步

本节同步当前正式 OMS UI 与本地全量验证结果，不表示逐真实服务 adapter 探针、可计费配置测试或 test-cn 在线账号状态已完成：

- 权限/身份边界：
  - 正式 Provider 设置 API 与 UI 均只使用 DeepTutor Enterprise 本地 `ops.providers.read/manage` 和 `ops.oms.access`；租户 token、伪造 header、auditor/security-only 角色写入仍失败关闭。
  - 未新增 EduPlus2、OpenFGA 或 Keycloak 迁移；`eduplus-platform-admin` 在线账号状态和真实 test-cn 平台身份验收仍由管理授权 proposal 跟踪。
- 配置状态机：
  - 后端 Provider 设置 `draft/test/publish/rollback` 已支持 backend/canary 执行者确认、Secret ref `env:` 校验、缺 Secret 发布失败保留旧 active、rollback 丢弃坏草稿。
  - 正式 OMS 模型/Provider 页面按 `ops.providers.read/manage` 展示脱敏连接与 test/publish/rollback 按钮；响应和浏览器状态不回显 Secret ref 明文、环境变量名、`sk-*` 或 provider 密钥。
  - TMS 当前只读取学校安全 DTO，不接收平台 Provider/Secret 字段。
- 验证：
  - `npm test --prefix extensions/enterprise/frontends` → **27 files / 297 tests passed**，包含正式 OMS 模型/Provider 只读 DTO 脱敏与写按钮 payload 绑定。
  - `npm run typecheck:oms --prefix extensions/enterprise/frontends && npm run typecheck:tms --prefix extensions/enterprise/frontends && npm run build:oms --prefix extensions/enterprise/frontends && npm run build:tms --prefix extensions/enterprise/frontends` → **通过**。
  - `npm run lint --prefix extensions/enterprise/frontends` → **通过**。
  - `.venv/bin/python -m pytest extensions/enterprise/tests -q` → **803 passed, 3 skipped, 2 warnings**。
  - `openspec validate add-enterprise-all-service-provider-settings --strict` → 见本轮验证记录；`git diff --check` → **通过**。
  - 只读 upstream mergeability smoke：merge-base `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`，`git merge-tree "$BASE" HEAD upstream/main` 未发现冲突标记。

任务影响：新增勾选 **1.2.1、2.3.1、3.1.1、3.2.1**。父任务 **1.2、2.3、2.4、3.1、3.2** 仍不关闭；逐服务真实执行者配置加载/探针、可计费测试学校选择、OMS 服务准入/attempt 核对、真实外部服务失败/重试负例与完整未支持服务清单仍待完成。
