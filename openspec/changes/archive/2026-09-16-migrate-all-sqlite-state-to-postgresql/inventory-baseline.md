# 实施前完整入口与依赖基线

2026-09-14 冻结，源码 HEAD `b96589df4e3b027f1c4b8b86b3b647c4de1cd6a0` 加当前首切片/用户未提交修改；业务迁移尚未完成。声明版本与本机已安装版本分列，不将静态未激活当作零 SQLite 运行证明。本文是 [inventory](inventory.md) 的详细调用/测试矩阵，不另立实施计划。除页面/API 路由字面量外，本文全部源码、依赖声明和测试路径均以仓库根为基准；不使用 brace、glob 或省略号表示冻结文件清单。

## 1. 结论摘要

1. 当前运行图不是“一个 SQLite”：有 **6 个写库族 + 1 个只读直扫族**：会话/题库、Learning、Reading catalog、Cron、Partners runtime status、每 KB MarginNote，以及 Memory 对会话库的只读 SQL。生产源码中有 9 个直接 `import sqlite3` 文件；若把包内测试算入则为 11 个。
2. `get_session_store()` 只对通用调用者做 SQLite/PocketBase 二选一；**至少 12 个生产模块仍显式调用 `get_sqlite_session_store()`**，所以只替换默认工厂不会迁完题库、导入、图书、课程、mastery 与 cron 消费者。
3. 默认 Web lifespan 会主动运行旧 chat/workspace migration，并由 background leader 启动 Partners、Cron、恢复器；交互 CLI `deeptutor chat` 也启动 Cron。这些都是启动前 PG 预检和“零 SQLite”进程门禁必须覆盖的真实后台入口。
4. 当前内建 capability 基线是 **11 个**，不是旧概览中的 7 个：`chat`、`ask_questions`、`deep_solve`、`deep_question`、`deep_research`、`math_animator`、`visualize`、`mastery_path`、`immersive_reading`、`course_study`、`immersive_watching`。PG-only 不能以首切片 chat 白名单缩小此集合。
5. Matrix 只声明范围 `matrix-nio>=0.25.2,<1.0.0` / `matrix-nio[e2e]>=0.25.2,<1.0.0`；项目 `.venv` 未安装 `matrix-nio`、`python-olm` 或 `olm`。**没有可报告的精确 nio/libolm 实测版本**，也没有普通或 E2EE 行为测试。task 1.23 仍是硬阻断项。
6. 现有 inventory 遗漏的可选 SDK 风险至少有两条：
   - `pageindex 0.2.16` 传递安装 `openai-agents 0.20.0`，其中自带 `SQLiteSession`、`AsyncSQLiteSession`、`AdvancedSQLiteSession` 及 SQLite-capable `SQLAlchemySession`；当前 DeepTutor/PageIndex 调用未传 `session=`，静态看未激活，但没有零 SQLite 运行探针证明。
   - `llama-index-core 0.14.24` 传递依赖 `aiosqlite`/`SQLAlchemy[asyncio]`，并提供默认 `sqlite+aiosqlite:///:memory:` 的 `SQLChatStore`；当前 DeepTutor 使用 `StorageContext`/Simple 或 FAISS 文件存储，未引用 `SQLChatStore`，仍需依赖与运行期门禁覆盖。
7. 当前测试大量锁定 SQLite 行为，但除首切片 `extensions/enterprise/tests` 的身份/文本会话外，其余题库、Learning、Reading、Cron、Partners status、MarginNote、Memory、Matrix 没有真实 PG 对等测试。Web E2E 的 Reading/Book 用前端 mock，不能作为 PG smoke。

## 2. 精确版本与依赖声明

### 2.1 当前项目环境（声明与实际分开）

| 项目 | 源码/声明 | 当前 `.venv` 实际 |
| --- | --- | --- |
| DeepTutor | `deeptutor/__version__.py`: `1.6.7` | `deeptutor==1.6.7`（editable 元数据出现两次，但同版本） |
| Python / SQLite C runtime | `requires-python >=3.11,<3.15` | Python `3.14.7`; stdlib SQLite `3.53.4` |
| `aiosqlite` | `pyproject.toml` 的 root/CLI-only groups、`requirements/cli.txt`: `>=0.19.0` | `0.22.1`；DeepTutor 源码没有 `import aiosqlite`，但 LlamaIndex 传递需要它 |
| PocketBase SDK | `pyproject.toml` 的 root/server groups: `pocketbase>=0.12.0` | `0.17.3` |
| LlamaIndex | `pyproject.toml` 的 root/CLI-only groups、`requirements/cli.txt`: `llama-index>=0.14.12` | umbrella/core 均 `0.14.24`; `SQLAlchemy==2.0.52` |
| PageIndex | `pyproject.toml` 的 root/CLI-only groups、`requirements/cli.txt`: `pageindex>=0.2.10,<0.3.0` | `0.2.16`; 传递 `openai-agents==0.20.0` |
| Matrix 普通 | `pyproject.toml` 的 matrix extra / `requirements/matrix.txt`: `matrix-nio>=0.25.2,<1.0.0`, `mistune>=3.0.0,<4.0.0`, `nh3>=0.2.18,<1.0.0` | 三者均未安装，未验证 |
| Matrix E2EE | `pyproject.toml` 的 matrix-e2e extra / `requirements/matrix-e2e.txt`: `matrix-nio[e2e]>=0.25.2,<1.0.0`; `python-olm` 仅由 extra 传递 | `matrix-nio` / `python-olm` / `olm` 均未安装，系统 libolm 未探测 |
| PG 首切片 | `extensions/enterprise/pyproject.toml` 与 `extensions/enterprise/requirements-test.lock`: `psycopg[binary]==3.3.5`, `psycopg-pool==3.3.1` | root `.venv` 均未安装；默认 core/CLI-only 也尚未声明 PG driver |
| 可选 GraphRAG | `graphrag>=3.0.1,<4.0.0; python_version<'3.14'` | Python 3.14 下不解析；未安装，含其 LanceDB/C/native 子图的 SQLite 行为未验证 |
| 可选 LightRAG | `lightrag-hku==1.5.7` | 未安装，未验证 |
| 可选 CodeBuddy Agent SDK | `codebuddy-agent-sdk>=0.3,<0.4` | 未安装；其内置 headless CLI/子进程存储未验证 |

**精确性结论：**当前能准确陈述的是“声明范围”和本 `.venv` 解析结果，不能把 `matrix-nio>=0.25.2,<1.0.0` 写成已锁定版本。Matrix PG adapter schema、线程模型和 E2EE 迁移字段必须等 task 1.23 在隔离环境固定 wheel/hash、Python、libolm 后再冻结。

### 2.2 间接 SQLite 依赖补漏

| 依赖/路径 | 本地证据 | 当前激活判断 | 后续门禁 |
| --- | --- | --- | --- |
| PageIndex → OpenAI Agents | `pageindex==0.2.16` 要求 `openai-agents>=0.18.1`; 实装 `0.20.0`; `.venv/lib/python3.14/site-packages/agents/memory/sqlite_session.py`、`.venv/lib/python3.14/site-packages/agents/extensions/memory/advanced_sqlite_session.py`、`.venv/lib/python3.14/site-packages/agents/extensions/memory/async_sqlite_session.py`、`.venv/lib/python3.14/site-packages/agents/extensions/memory/sqlalchemy_session.py` 存在 | `.venv/lib/python3.14/site-packages/pageindex/local_chat.py` 的 `Runner.run`/`Runner.run_streamed` 未传 `session=`；DeepTutor 也未导入这些 Session 类，静态未激活 | PageIndex cloud/OSS SDK 工具真实新进程运行时拦截文件和 `:memory:` SQLite；升级版本重复审计 |
| LlamaIndex core SQL chat store | 实装 core `0.14.24`; `.venv/lib/python3.14/site-packages/llama_index/core/storage/chat_store/sql.py` 默认 `sqlite+aiosqlite:///:memory:` | DeepTutor LlamaIndex pipeline只使用 `StorageContext`、Simple/FAISS persist，未导入 `SQLChatStore` | LlamaIndex 建库/查询新进程零 SQLite 探针；不得把 `:memory:` 视作允许 |
| Matrix nio store | `deeptutor/partners/channels/matrix.py` 总是传 `store_path`，配置 `store_sync_tokens=True`，有 device 时 `load_store()`；E2EE 依赖可用性分支 | 依赖未安装，普通与 E2EE 均不可实测；现有 `load_store()` 异常被吞后继续同步是迁移风险 | 精确锁版本；普通/E2EE 分别验证 store class、回调线程、完整账户/Olm/Megolm/设备/房间/token 字段和故障停止语义 |
| 其它可选 SDK/插件/子进程 | Matrix 之外的 partners SDK、GraphRAG/LanceDB、LightRAG、CodeBuddy、解析器 extras 当前未全装 | 静态仓库 grep 不能证明 wheel 内 C extension 或子进程不打开 SQLite | 最终 wheel 的依赖树/SBOM + syscall/audit-hook 子进程探针；发现路径后扩充 inventory，不可预先白名单 |

补充：删除 `aiosqlite` 直接声明仍不能消除 Python 自带 `_sqlite3`（当前 SQLite 3.53.4）；零访问验收必须拦截 `sqlite3.connect`、SQLAlchemy SQLite URL、文件后缀、`:memory:`，并覆盖 native/子进程，不能只 grep import。

## 3. 直接 SQLite 权威库、只读探针与实际调用方

### 3.1 会话、turn/event 与 question notebook (`chat_history.db`)

- 实现：`deeptutor/services/session/sqlite_store.py`；构造器即建目录、迁移 schema、打开 SQLite。表：`sessions`、`messages`、`turns`、`turn_events`、`notebook_entries`、`notebook_categories`、`notebook_entry_categories`。
- 默认装配：`deeptutor/services/session/__init__.py:get_session_store()` 在无 provider 且无 PocketBase 时直接 `return get_sqlite_session_store()`；`deeptutor/app/container.py:StoreProvider.get()` 是 Web/WS/CLI/SDK 共享根；`deeptutor/services/session/turn_runtime.py` / `deeptutor/services/session/turns/lifecycle.py` 还可从全局工厂取 store。
- **显式 SQLite 调用方（不能只换 `get_session_store`）：**
  - API：`deeptutor/api/routers/question_notebook.py`（15 个 endpoint 取 store）、`deeptutor/api/routers/imports.py`、`deeptutor/api/routers/sessions.py` 的 `/quiz-results`、`deeptutor/api/routers/book.py` 的 quiz attempt 落题库。
  - agent/tool：`deeptutor/tools/question_bank.py`、`deeptutor/agents/question/history.py`、`deeptutor/agents/_shared/tool_composition.py` 的题库 mount gate。
  - mastery/course/book/background：`deeptutor/capabilities/mastery/tools.py`、`deeptutor/learning/topic_materials.py`、`deeptutor/book/inputs.py`、`deeptutor/services/courses_state.py`、`deeptutor/services/cron/executor.py`。
- **通用工厂的额外真实消费者：**`deeptutor/api/routers/sessions.py`、`deeptutor/api/routers/courses.py`、`deeptutor/api/routers/dashboard.py`、`deeptutor/api/routers/mastery_path.py`、`deeptutor/api/routers/reading.py`、`deeptutor/capabilities/mastery/binding.py`、`deeptutor/learning/navigation.py`、`deeptutor/services/chat_hints.py`、`deeptutor/services/mastery_hints.py`、`deeptutor/services/reading_hints.py`、`deeptutor/services/courses_state.py`、`deeptutor/services/doctor.py`、`deeptutor/services/session/legacy_migration.py`、`deeptutor/services/session/turn_runtime.py`、`deeptutor/services/session/turns/lifecycle.py`。
- PocketBase 旁路：配置 `integrations.pocketbase_url` 后 `get_session_store()` 创建 `PocketBaseSessionStore`；`deeptutor/services/auth.py` 与 `deeptutor/services/pocketbase_client.py` 也切到 PocketBase identity。当前 ping 失败日志甚至声明“fall back to SQLite”，目标态必须改为失败关闭。PB collection 至少包含 `sessions/messages/turns/turn_events` 与 users；branch parent 尚未完整实现，迁移验证不能只看通用 protocol。

### 3.2 Learning (`mastery.sqlite3`)

- 实现/旧迁移：`deeptutor/learning/storage.py`、`deeptutor/learning/migration.py`。表：`mastery_paths`、`mastery_path_sessions`、`mastery_interactions`、`mastery_events`、`mastery_path_leases`、`mastery_topic_meta`、`mastery_topic_sources`。
- 实际调用方：
  - API：`deeptutor/api/routers/mastery_path.py` 全部 topics/progress/WS 流程；`deeptutor/api/routers/sessions.py` 删除时 detach。
  - capability/tool：`deeptutor/capabilities/mastery/binding.py`、`deeptutor/capabilities/mastery/capability.py`、`deeptutor/capabilities/mastery/tools.py`。
  - 业务：`deeptutor/learning/navigation.py`、`deeptutor/learning/service.py`、`deeptutor/services/mastery_hints.py`。
  - turn runtime/background：`deeptutor/services/session/_turn_runtime_shared.py`、`deeptutor/services/session/turns/learning_adapter.py`、`deeptutor/services/session/turns/request_preparer.py`、`deeptutor/services/session/turns/executor.py`，覆盖 lease 领取/释放、恢复、commit 后事件路径。
- 漏项：现 inventory 的 `deeptutor/learning/event_hub.py` 是重要消费者，但实际构造器/路由/turn runtime 文件也必须列入；仅迁 storage 与 API 会留下后台 lease/恢复 SQLite。

### 3.3 Reading (`_catalog.sqlite3` + 文件内容)

- SQLite 实现：`deeptutor/reading/catalog_store.py`；表：`reading_schema`、`reading_materials`、`reading_workspaces`、`reading_workspace_materials`、`reading_workspace_sessions`、`reading_session_links`。
- `deeptutor/reading/store.py` 仍直接只读 `_catalog.sqlite3` 来解析 content state，且管理材料正文/manifest/assets/position/annotation/bookmark 文件。PG-only 本 change只替换 SQLite catalog/状态，不能误把 S3/文件范围偷换成 PG blob。
- 实际调用方：
  - API：`deeptutor/api/routers/reading.py`、`deeptutor/api/routers/reading_extensions.py`、`deeptutor/api/routers/multi_user.py`（账号预置/清理）。
  - capability/tool：`deeptutor/capabilities/reading/capability.py`、`deeptutor/capabilities/reading/tools.py`、`deeptutor/capabilities/course_study/capability.py`、`deeptutor/capabilities/course_study/tools.py`。
  - 业务：`deeptutor/reading/ingestion.py`、`deeptutor/reading/knowledge_capture.py`、`deeptutor/reading/references.py`、`deeptutor/reading/service.py`、`deeptutor/reading/export.py`、`deeptutor/reading/epub_bilingual.py`、`deeptutor/services/courses_state.py`、`deeptutor/services/reading_hints.py`。
  - turn runtime：`deeptutor/services/session/_turn_runtime_shared.py`、`deeptutor/services/session/turns/request_preparer.py`。
- 漏项：原 inventory 未列 `course_study`、reading extension、多用户清理、turn request material/tab 恢复与 annotations/bookmarks 这些调用面。

### 3.4 Cron (`jobs.sqlite3`)

- 实现：`deeptutor/services/cron/repository.py:SQLiteCronRepository`；表 `cron_jobs`、`cron_meta`；`CronService` 构造时默认 repo，`get_cron_service()` 使用 `jobs.sqlite3` 并可从 `jobs.json` 自动导入。
- 调用方：`deeptutor/tools/cron_tool.py`（schedule/list/cancel）；`deeptutor/api/main.py` lifespan/background leader 启停及跨 worker reload；`deeptutor_cli/chat.py` REPL 启停；`deeptutor/services/cron/executor.py` 回到 session store 执行任务；`deeptutor/services/partners/manager.py` 删除 Partner 时清 owner jobs。
- 无独立 Cron REST 页面/API；它仍是 chat、Partner、CLI 与后台能力，不能因为没有页面就排除。

### 3.5 Partners runtime status（运行目录由代码计算；未读取受限 `data/`）

- 实现：`deeptutor/services/partners/runtime_status.py:PartnerRuntimeStatusRepository`，表 `partner_runtime_status`。
- 调用方：`deeptutor/services/partners/manager.py` 发布、聚合、删除 runtime status；`deeptutor/api/routers/partners.py` lifecycle command 等待、详情、start/stop/reload/channel status；`deeptutor/api/main.py` background leader 自动启动/停止。
- 当前 row 只有 partner/status/owner/process payload 语义，缺 tenant/业务 owner/worker generation/TTL 的完整强制边界；目标 schema 不应照抄现表后宣称隔离完成。

### 3.6 MarginNote 每 KB SQLite

- 实现：`deeptutor/capabilities/marginnote4/store.py`；表 `mn4_objects`、`mn4_devices`、`mn4_cursors`、`mn4_tombstones`。
- 调用方：
  - `/api/marginnote4` 的 pair/devices/revoke/status/sync/heartbeat：`deeptutor/api/routers/marginnote4.py`。
  - 七个实际工具：`marginnote_search/read/list/documents/links/tags/cards`（`deeptutor/capabilities/marginnote4/tools.py`），由 `deeptutor/capabilities/marginnote4/binding.py` / `deeptutor/capabilities/marginnote4/capability.py` 注入 `_db_path`。
  - KB 注册/元数据/删除数据库及 `-wal/-shm`：`deeptutor/api/routers/knowledge.py`、`deeptutor/knowledge/manager.py`、`deeptutor/knowledge/kb_types.py`。
- 漏项：原 inventory 只列 store，未列知识库删除是数据库 writer、工具缓存 `_STORE_CACHE`、device API 的 `open_existing()` 只读/认证路径。

### 3.7 Memory 对 chat/quiz 的只读 SQLite 探针

- 直接 SQL：`deeptutor/services/memory/snapshot/adapters.py` 的 `read_chat_entities()`、`read_quiz_entities()`、`probe_chat_entities()` 均通过 `get_chat_history_db()` 后 `sqlite3.connect(file:...?mode=ro)`；异常会 warning 并返回空/回退，目标态不能把新 PG 数据静默成空。
- 消费者：
  - API `/api/memory/snapshot/{surface}`、`/refresh`、`/changes`（`deeptutor/api/routers/memory.py` → `deeptutor/services/memory/snapshot/__init__.py`）。
  - memory recall 的 `recent()`/stamps（`deeptutor/services/memory/recall.py`）。
  - consolidator audit/update 从 snapshot 读取（`deeptutor/services/memory/consolidator/modes/audit.py`、`deeptutor/services/memory/consolidator/modes/update.py`）。
  - 前端 `/memory*` 页面、`read_memory` 工具及会话 starter/suggestion 间接消费。
- 漏项：除显式 reader 外，`read_stamps()` 的 probe-first / full-read fallback 以及删除可见性、稳定分页、后台 refresh 都应映射为 PG 测试，不能只替换三个 connect。

### 3.8 不属于运行期业务 SQLite 的同字面量

这些引用应保留分类证据，而不是机械删除：

- `deeptutor/services/parsing/engines/tika/formats.py` 把 `.sqlite/.sqlite3` 当用户文档格式；它不把文件当 DeepTutor state。
- `deeptutor/services/path_service.py` 仅把 `.sqlite/.db` 列为需要私有权限的后缀。
- `deeptutor/services/session/source_inventory.py` 仅在注释中说明避免 sqlite-only helper。
- `deeptutor/learning/tests/test_v2_migration.py` 和未来离线 importer/旧格式 fixture 可读取隔离快照；不得进入业务运行图或扩大进程白名单。

## 4. 默认入口/页面/API/WS/CLI/SDK/工具/后台矩阵

| 域 | 默认页面 | API / WS | CLI / SDK | 工具 / capability | 后台/生命周期 | 当前存储结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 身份/默认装配 | `/login`, `/register`, `/admin/users` | `/api/auth/*`, 所有 auth dependency | `start`, `serve`, `run`, `chat`; `DeepTutorApp(container=None)` | 全 capability 的前置主体 | lifespan/build/recovery | 当前 JSON/PocketBase/local-admin 与 SQLite fallback；目标必须 PG fail-closed |
| 会话/turn/event | `/`, `/chat`, `/chat/[sessionId]`, `/space/chat-history` | `/api/sessions/*`, canonical `/ws` | `run`, `chat`; SDK start/stream/cancel/reply/regenerate/list/get/rename/delete | 11 个 capability 均通过 turn runtime | startup legacy migration、recovery | 默认 SQLite；PB 条件旁路 |
| Question notebook | `/space/questions` | `/api/question-notebook/*`, `/api/sessions/*/quiz-results`, `/api/imports/chat-history` | 无专用 question CLI；SDK 无 question-bank CRUD | `question_bank`, mastery quiz/grade, deep_question history | quiz/turn finalize、book capture | 多个显式 SQLite caller |
| 通用 notebook | `/notebooks*` | `/api/notebooks*` | `notebook *`; SDK notebook CRUD | `list_notebook`, `write_note` | 无 | 当前主要 JSON/Markdown，非本任务 SQLite 表，但功能基线不可删除 |
| Mastery/Learning | `/mastery*` | `/api/mastery-paths/*`, `/ws/mastery-paths` | `run mastery_path`/alias `mastery`; SDK 可通过 turn capability | 全 `mastery_*`、`mastery_topics/sessions/open/new`; `course_study` 交叉 | event hub、lease、turn recovery | `mastery.sqlite3` |
| Reading | `/reading*` | `/api/reading/*` | `run immersive_reading`/alias `reading/read`; SDK 可通过 turn capability | `reading_*`, `material_*`, reader tools；`course_study` | request preparation/workspace restore | `_catalog.sqlite3` + 文件 |
| Courses/Books | `/courses*`, `/books*` | `/api/courses/*`, `/api/books/*`, `/ws/books` | `book list/health/refresh-fingerprints`; `run course_study` | `course_*`; book agents | book compile/runtime，cron可引用会话 | 通过 session/question/reading/learning 间接 SQLite |
| Cron | 无专页/无专用 REST | canonical chat/partner 流程间接 | `chat` 启动 service | `cron` | Web background leader/executor | `jobs.sqlite3` + 启动 JSON 导入 |
| Partners/Matrix | `/partners*` | `/api/partners/*`, `/ws/partners/*`, `/ws/partner-groups/*` | `partner list/start/stop/create`; chat REPL | partner memory/invoke tools | auto-start/channel workers/runtime status | status SQLite；Matrix `store_path` 条件间接 SQLite |
| MarginNote | `/knowledge-bases*` 中连接/设备 UI | `/api/knowledge-bases/connect-marginnote4`, `/api/marginnote4/*` | KB/capability 间接 | 7 个 `marginnote_*` | sync/heartbeat，KB 删除 | 每 KB SQLite |
| Memory snapshot | `/memory*` | `/api/memory/snapshot/*` 等 | `memory show/clear`（其它 memory 文件路径亦须保持） | `read_memory` | refresh/consolidator/recall | chat/quiz read-only SQLite |

### 4.1 全 capability 基线（不得缩窄）

`deeptutor/runtime/bootstrap/builtin_capabilities.py` 当前注册 11 个：

- 通用：`chat`, `ask_questions`, `deep_solve`, `deep_question`, `deep_research`, `math_animator`, `visualize`。
- 本次状态强相关：`mastery_path`, `immersive_reading`, `course_study`。
- 同样必须保留：`immersive_watching`（虽无直接 SQLite Store，仍走 session/turn runtime）。

### 4.2 全 WebSocket 基线

`tests/api/test_websocket_routing.py` 固定 9 条：`/ws`、`/ws/books`、`/ws/questions/mimic`、`/ws/questions/generate`、`/ws/questions/judge`、`/ws/knowledge-bases/{kb_name}/progress`、`/ws/mastery-paths`、`/ws/partners/{partner_id}`、`/ws/partner-groups/{group_id}`。PG-only smoke 不能只跑 `/ws` chat。

### 4.3 CLI 基线

根命令：`run`, `start`, `stop`, `serve`, `doctor`, `init`；子树：`partner`, `chat`, `kb`, `skill`/`skills`, `memory`, `plugin`, `config`, `session`, `notebook`, `provider`, `book`, `workspace`。业务 PG 预检应覆盖所有实际读写命令；`--help`/版本、纯 import、离线 plan/source-check 保持无连接。

### 4.4 SDK 基线

`DeepTutorApp` 公开：capability contract/availability、turn start/stream/cancel/reply/regenerate、session list/get/rename/delete/active、notebook list/create/get/add/update/remove/reference resolve。默认构造器通过 `get_application_container()` → `StoreProvider` → `get_session_store()`，当前可落 SQLite/PocketBase；显式 container 可走首切片 PG。SDK 残留对象已开始做 provider guard，但只有首切片验证，Reading/Learning/Cron/Partner 仍未成为 SDK 领域接口。

## 5. 逐域现有测试映射与缺口

所有测试清单均在 [冻结文件清单](inventory-files.json) 的 `tests` 对象中逐项展开；其 `path_base` 为仓库根，清单只含字面路径，不使用 glob、brace 或省略号。以下 key 是逐域映射，不是路径简写：

| 域 | `inventory-files.json` 测试组 | 已有 PG 覆盖 | 关键缺口 |
| --- | --- | --- | --- |
| Session/turn/event | `session_turn_event` | `enterprise_pg_session_slice` | 默认 app/CLI-only 全路径仍是 SQLite；PG 只覆盖首切片 route/profile，notebook/categories/完整关联未覆盖 |
| Question notebook/import/book quiz | `question_notebook_import_book_quiz` | 无对应 PG repository 测试 | CRUD/filter/search/stats/category、file payload、dedup、book/mastery/tool 真入口均待真实 PG |
| Learning/Mastery | `learning_mastery` | 无 | schema、CAS、lease、事件顺序、断线重放、后台恢复、API/WS/tool 全 PG 矩阵 |
| Reading | `reading`；前端 mock 清单为 `reading_mock_e2e` | 无 | catalog PG、owner/FK、workspace/session/link/position/annotation/bookmark、原页面真实后端 smoke；现有 E2E 使用 mock API |
| Cron | `cron` | 无 | Web/CLI/Partner/background、原子 claim/CAS、时区、重启、不确定外部结果均无 PG 测试 |
| Partners status | `partners_status` | 无 | tenant/owner/worker generation/TTL、跨进程 leader-reader、跨用户/API 负例 |
| Matrix 普通/E2EE | `matrix` | 无 | 没有测试导入 `MatrixChannel`；无普通收发、E2EE、重启、信任、旧消息解密、完整 store 协议/线程/故障测试 |
| MarginNote | `marginnote` | 无 | PG schema/scope、设备 token/hash/revoke、cursor+tombstone 原子、API/tool/KB 删除 |
| Memory read-only probes | `memory_read_only` | 无 | 新 PG 数据、删除、owner、稳定分页/版本 cursor、后台 refresh；当前 probe tests 自建 SQLite |
| 默认路由/入口 | `default_routing_entry` | `enterprise_pg_session_slice` 中的首切片 HTTP/WS/SDK/CLI chat/session | 没有最终 wheel 下完整页面/API/WS/CLI/SDK/后台的统一 PG smoke；前端 E2E 多为 fetch mock |
| 打包/间接 SDK | `packaging_optional_sdk` | 无零 SQLite 运行门禁 | 未测试 wheel 依赖树、optional extras、native/C、subprocess、`:memory:`/文件 SQLite 拒绝 |

首切片 PG 测试有价值但边界明确：`extensions/enterprise/tests/test_sessions.py` 覆盖 owner-scoped text sessions/turn/events/branch/CAS/delete，`extensions/enterprise/tests/test_application.py`、`extensions/enterprise/tests/test_flows.py`、`extensions/enterprise/tests/test_isolation_matrix.py` 覆盖专用 HTTP/WS/SDK/CLI 组合；它不等于默认 `deeptutor/api/main.py` 的全部路由，也不覆盖上述其余域。

## 6. 相对现有 `inventory.md` 的新增漏项清单

1. capability 清单漏掉 `ask_questions`、`immersive_reading`、`course_study`、`immersive_watching`；验收必须按当前 11 项而非首切片/旧文档集合。
2. Session 通用调用方漏掉 dashboard、hints、doctor、turn lifecycle/runtime、mastery/reading session 绑定等；直接 SQLite 清单虽列主文件，但没有显示 `ApplicationContainer.StoreProvider` 是 Web/WS/CLI/SDK 公共根。
3. Learning 漏掉 `deeptutor/services/session/turns/learning_adapter.py`、`deeptutor/services/session/turns/request_preparer.py`、`deeptutor/services/session/turns/executor.py` 和 `deeptutor/services/session/_turn_runtime_shared.py` 的 lease/恢复调用。
4. Reading 漏掉 `course_study`、reading extensions、多用户账号清理、request preparer、annotations/bookmarks/EPUB pairing 与 knowledge capture/export/references 调用面。
5. Cron 漏掉 `deeptutor_cli/chat.py` 实际启动服务、`deeptutor/api/main.py` background control/reload、Partner 删除清 jobs。
6. Partners status 漏掉 `deeptutor/api/routers/partners.py` 的跨 worker lifecycle 等待/状态返回；只有 store 名不足以测试权限/TTL。
7. MarginNote 漏掉 API device/sync 入口、7 个工具、binding `_db_path`、KB 删除数据库/WAL sidecar 和工具级缓存。
8. Memory 漏掉 `read_stamps()` probe-first/full-read fallback 的真实消费者：API refresh、recall、consolidator；返回假空是当前异常路径，必须做失败语义测试。
9. Matrix 现有测试实际上没有导入/运行 channel；`load_store()` 失败会被吞并继续同步，这与目标“PG 故障停止同步”直接冲突。
10. 可选 SDK 漏掉 PageIndex→OpenAI Agents SQLite session 实现和 LlamaIndex `SQLChatStore` 的 `:memory:` 默认；当前静态未激活不代表最终 wheel/升级后安全。
11. `aiosqlite` 是 root/CLI-only 直接声明但源码未导入，同时又是 LlamaIndex core 的传递依赖；task 1.42 不能简单从一处删行，应验证解析后的 wheel 仍可能安装它以及运行图不调用它。
12. `sqlite3` 是 Python stdlib/C runtime，删除 pip 包或 `.db` 后缀搜索无法证明零访问；必须覆盖 native/子进程。

## 2026-09-15 task 1.23 Matrix protocol lock update

Baseline 1.1 记录的是实施前状态：Matrix 依赖未安装且只有版本范围。task 1.23 已在隔离 `.venv` 中安装并实测 `matrix-nio==0.26.0`；E2EE 绑定为 `vodozemac==0.10.0`，`python-olm` / `olm` / libolm 不在该锁定栈。`pyproject.toml` 与 `requirements/matrix*.txt` 已改为精确 pin；完整 storage protocol 字段、加密边界和线程模型见 `matrix-storage-protocol.md`。这只解除 1.24 schema 设计的前置不确定性，不表示 Matrix PG adapter 或普通/E2EE 收发验收已完成。
