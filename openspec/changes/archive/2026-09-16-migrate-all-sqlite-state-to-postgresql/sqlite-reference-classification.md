# SQLite / aiosqlite residual reference classification

更新日期：2026-09-15。范围：task 1.42 对默认 PG-only runtime 的直接依赖、运行配置、SDK/plugin 传递存储风险、C/native 与子进程路径进行静态核查。业务默认运行图：禁止 SQLite 文件、`:memory:`、C/native sqlite3 连接和第三方默认 SQLite session；SQLite 只允许离线 import 工具和旧格式 fixture 显式使用。

## 1. 直接依赖与安装面

- aiosqlite direct runtime dependencies: none
- 已从以下默认安装面移除直接声明：
  - `pyproject.toml` `[project].dependencies`
  - `pyproject.toml` `[project.optional-dependencies].cli`
  - `pyproject.toml` `[project.optional-dependencies].server`（继承 core/cli 后也不再声明）
  - `packaging/deeptutor-cli/pyproject.toml` `[project].dependencies`
  - `requirements/cli.txt`
- 当前开发 venv 在重新安装前仍可能保留旧 editable metadata / 已安装 wheel 的 `aiosqlite`，不作为制品契约；2.1 wheel 构建安装会重新验证最终 metadata。

## 2. 传递 SDK/plugin 风险核查

- `llama-index-core==0.14.24` 仍声明 `aiosqlite` 传递依赖；DeepTutor 不再把它作为业务状态 backend。该包可用于 RAG 组件的内部可选 SQL 存储，默认业务状态不得因此访问 SQLite；1.43 的进程级 `sqlite3.connect` 门禁覆盖该风险。
- `matrix-nio==0.26.0` 安装包包含 `nio.store.database` SQLite store；默认 Matrix runtime 已由 PG-backed `PostgresMatrixStore` 接管，旧 nio SQLite store 仅作为离线 `matrix_nio_sqlite/v0.26` source 格式的兼容对象被识别。
- `openai-agents==0.20.0` 安装包包含 `agents.memory.sqlite_session`、`advanced_sqlite_session`、`async_sqlite_session` 等示例/可选 memory session；DeepTutor 当前默认工具/agent 组合不配置这些 memory classes。它们是静态未激活风险，受 1.43 新进程/子进程零 SQLite 门禁覆盖。
- `pageindex==0.2.16` 包内未发现 `sqlite` / `aiosqlite` 字符串命中。

## 3. 残余生产 `sqlite3` import 分类

### A. 受控离线 importer / source-check / verify（允许）

这些文件只处理 manifest 声明的独立只读 SQLite snapshot，不在默认业务入口装配：

- `deeptutor/persistence/postgres/offline_import/sqlite_snapshot.py` — SQLite Backup API 生成独立 snapshot 与 manifest。
- `deeptutor/persistence/postgres/offline_import/planner.py` — `source-check` / `plan` 读取不可变 snapshot 并输出导入计划。
- `deeptutor/persistence/postgres/offline_import/chat_sqlite.py` — `chat_history_sqlite/v1` 离线导入。
- `deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py` — `mastery_sqlite/v1|v2`、`reading_catalog_sqlite/v1` 离线导入。
- `deeptutor/persistence/postgres/offline_import/runtime_sqlite.py` — cron / Partners runtime status / MarginNote SQLite snapshot 离线导入。
- `deeptutor/persistence/postgres/offline_import/matrix_sqlite.py` — `matrix_nio_sqlite/v0.26` 离线导入。
- `deeptutor/persistence/postgres/offline_import/verify_report.py` — verify/report 对离线 snapshot 与 PG 目标做计数、摘要和语义校验。

### B. 旧格式 fixture / legacy module（默认业务运行图禁止）

这些文件保留给旧格式 fixture、离线源构造或旧单元测试；默认 accessor / provider 已改为 PG-only 或明确拒绝，不应由业务入口调用：

- `deeptutor/services/session/sqlite_store.py` — 旧 `chat_history.db` Store；`get_sqlite_session_store()` 已改为 PG-only deprecation error，包级 `SQLiteSessionStore` 已移除，仅直接模块 fixture 可显式使用。
- `deeptutor/learning/storage.py` — 旧 `mastery.sqlite3` Store；默认 `LearningService()` 无 PG unit 时 fail-closed，PG provider 在运行图中接管 mastery path/session/interaction/event/source。
- `deeptutor/learning/migration.py` — 旧 mastery v1→v2 文件迁移；运行构造器不再触发，旧数据经离线 importer 迁入 PG。
- `deeptutor/reading/catalog_store.py` — 旧 `_catalog.sqlite3` catalog；默认 reading provider / API / tools / capability 走 PG catalog 和资源 provider。
- `deeptutor/reading/store.py` — 旧 reading 单元/manifest fallback；默认 PG provider 下不会打开 `_catalog.sqlite3`，残余用于旧 fixture 读取。
- `deeptutor/services/cron/repository.py` — 旧 `SQLiteCronRepository`；默认 `get_cron_service()` 需要已启动 PG runtime，无 PG 时拒绝且不创建 `jobs.sqlite3`。
- `deeptutor/services/partners/runtime_status.py` — 旧 `PartnerRuntimeStatusRepository` 显式 fixture；默认 `get_partner_runtime_status_repository()` 从 PG runtime 创建 repository，无 PG 时拒绝且不创建 `status.sqlite3`。
- `deeptutor/capabilities/marginnote4/store.py` — 旧 MarginNote SQLite object/device/cursor store；默认 API/KB/capability 入口已通过 PG store/provider 接线，旧 db_path 不再授予归属。

## 4. 非连接型字符串 / 文档注释（不构成 SQLite 运行路径）

- `.sqlite` / `.sqlite3` 文件后缀在 `deeptutor/services/path_service.py` 与 parser format 清单中仅用于隐私/文件类型处理，不创建连接。
- `deeptutor/persistence/postgres/configuration.py` 中的 `sqlite_path` 等字段仅用于拒绝旧配置并给出升级错误。
- cutover rollback 文案中的 `legacy_sqlite` 是回退矩阵状态，不启用 backend。
- 代码注释和 OpenSpec 文档中出现的 `SQLite` 均不视作运行路径，但需由 1.43 动态门禁验证没有隐藏访问。

## 5. 证明方式与后续门禁

- 静态命令：`rg -n "aiosqlite" pyproject.toml packaging requirements deeptutor tests` 只剩本门禁测试；生产 `import sqlite3` 文件已全部列入本报告。
- 包 metadata 测试：`tests/test_packaging_metadata.py::test_aiosqlite_is_not_a_direct_runtime_dependency` 覆盖 root、CLI extra、server extra、CLI-only wheel 和 requirements/cli。
- 分类门禁：`tests/persistence/postgres/test_sqlite_reference_inventory.py` 扫描生产 `sqlite3` imports，要求每个文件在本文档分类。
- 1.43 继续新增新进程/子进程零 SQLite 访问测试，覆盖默认入口、SDK/plugin 间接存储和 Matrix 普通/E2EE；本报告本身不替代动态门禁。
