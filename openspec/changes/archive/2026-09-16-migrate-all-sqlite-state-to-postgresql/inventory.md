# SQLite 退出范围与真实入口清单

2026-09-13，静态核查当前工作区。表中为当前存在的调用，不是迁移已完成声明；精确版本、完整调用方、11 个 capability / 9 条 WS 与逐域测试映射已冻结于 [实施基线](inventory-baseline.md)；它不代表迁移通过。`.secrets`、现有用户数据库和第三方服务数据均未读取。

## 1. 直接业务库与读取方

| 当前权威/调用 | 主要源文件（相对仓库根） | 必须保留的行为与目标 |
| --- | --- | --- |
| `chat_history.db` | `deeptutor/services/session/sqlite_store.py`、`services/session/__init__.py` | sessions/messages/turns/events 复用已有 PG；notebook_entries/categories/entry_categories 补齐 PG。默认工厂退出 SQLite/PocketBase；不只迁 chat |
| `mastery.sqlite3` | `deeptutor/learning/storage.py`、`learning/migration.py`、`learning/event_hub.py` | 路径/会话/交互/事件/租约、topic metadata/source、CAS 与重放；旧 v1/v2 文件读取只在离线导入工具 |
| `_catalog.sqlite3` | `deeptutor/reading/catalog_store.py`、`reading/store.py` | 材料、工作区/tab、阅读会话/关联与恢复；不以路径名作为身份或资源所有权 |
| `jobs.sqlite3` | `deeptutor/services/cron/repository.py`、`cron/service.py`、`cron/executor.py` | at/every/cron、时区、暂停/变更、原子领取/结果、重启；JSON 旧任务导入也退出业务启动路径 |
| `_runtime/status.sqlite3` | `deeptutor/services/partners/runtime_status.py` | partner 状态投影、版本/worker 身份/过期、跨进程读取；从现有受控 partner 配置映射 tenant/owner，缺映射拒绝，不当全局可读缓存 |
| MarginNote 每 KB SQLite | `deeptutor/capabilities/marginnote4/store.py` | objects/devices/cursors/tombstones、设备撤销、批次/增量同步/搜索；以 tenant/owner/KB/device 复合归属替代任意 db_path |
| Memory 快照直接 SQL | `deeptutor/services/memory/snapshot/adapters.py` | `read_chat_entities/read_quiz_entities/probe_chat_entities` 改为 PG 查询与版本游标，保留快照内容、去重及删除可见性，不把只读直连当豁免 |

## 2. 必须收敛的共享会话旁路

以下调用 `get_sqlite_session_store()` 或其具体模块，不能只改 `get_session_store()` 就认为完成：

- `api/routers/question_notebook.py`、`api/routers/sessions.py` 的 quiz-results、`api/routers/imports.py`、`api/routers/book.py`。
- `tools/question_bank.py`、`agents/question/history.py`、`agents/_shared/tool_composition.py`。
- `capabilities/mastery/tools.py`、`learning/topic_materials.py`。
- `book/inputs.py`、`services/courses_state.py`、`services/cron/executor.py`。

同一关系同时被课程/图书、题库和 chat 引用时，查询、计数、搜索、导出、删除与后台恢复都走相同 provider/owner/version；有文件载荷的测试继续覆盖现有资源契约，不能丢引用或把 SQLite 文件打包成 PG blob。

## 3. 间接依赖与可选渠道

`deeptutor/partners/channels/matrix.py` 为 `AsyncClient` 设置 `store_path`，配置 sync token / E2EE 并调用 `load_store()`，没有显式 PG store。task 1.23 已将 Matrix 依赖锁定为 `matrix-nio==0.26.0`、E2EE `matrix-nio[e2e]==0.26.0` + `vodozemac==0.10.0`；`python-olm` / `olm` / libolm 不属于该锁定栈。完整 store 方法、SQLite 模型字段、加密边界和线程模型见 [matrix-storage-protocol.md](matrix-storage-protocol.md)。

nio 0.26.0 内置 store 包含 SQLite 实现，并支持自定义 `MatrixStore`；默认客户端配置在加密依赖可用时选择 `DefaultStore`。因此这是**条件性间接 SQLite 路径，不是每次普通 Matrix 启动都会创建数据库的断言**；1.24–1.26 必须用 PG store 与专属 worker 替换该路径。

实施必须固定实际 nio/libolm 版本，交付 PG-backed adapter 与普通/E2EE 两种契约测试；覆盖设备身份、账户/会话密钥的加密序列化、设备信任、房间状态、同步游标、重启及重放。不能改用 `SqliteMemoryStore`、关闭 E2EE 或吞掉 load_store 错误完成零 SQLite 指标。库内同步接口通过有界线程执行整个客户端存储交互，不能在 event loop 中阻塞 PG 或嵌套异步循环；细节见 design。

其余受本仓库控制的 SDK/provider/plugin 也须执行依赖与运行期扫描。用户任意第三方插件或外部独立服务的内部数据库不由本仓库重写，但受支持内置/可选渠道不能被静默排除；新增路径发现后扩充本清单和任务，缺证据不通过全量验收。

## 4. 启动与打包覆盖

- `deeptutor/api/main.py` lifespan、所有受支持 API/WS 注册、`runtime/launcher.py` 与容器镜像入口。
- `deeptutor/app/container.py` 默认单例/启动迁移、`app/facade.py` SDK 惰性服务、`deeptutor_cli/main.py` 及业务子命令。
- 企业 bootstrap/provider 与既有 34 项回归；core 不依赖企业包的独立安装。
- root `pyproject.toml`、`packaging/deeptutor-cli`、`requirements/cli.txt`、server/all/matrix 依赖组合和包 SQL 资源。
- 所有后台恢复、cron/Partners/Matrix 子进程、agent/tool 与 SDK 对象脱离上下文后的访问，不仅 HTTP happy path。

允许无数据库执行 `--help`、`--version`、纯模块 import、静态配置检查、离线源检查；业务读写、模型派发、后台调度开始前必须完成 PG/可信主体/schema 预检。单独静态前端开发服务器不持有 DSN，业务由已连接 PG 的后端提供。

## 5. 核查方法与状态

本轮执行 `rg -n -i 'sqlite|aiosqlite'`、直接 connect/import 与 factory 调用扫描、Matrix 构造/加载路径检查、OpenSpec 状态读取；这是范围证据，不是业务测试。实施门禁需在禁止 SQLite 文件、内存库及子进程连接的条件下启动新进程，跑真实默认入口与上述所有域；只搜文件名或删除 import 不足以验收。

## 6. 导入引用图与重写规则

以下是必须覆盖的字段族；各源版本的实际 JSON key/表字段须在任务 1.30/1.32 固定为机器可校验 mapping manifest，与对应 parser/测试同版本。未知源版本或机器引用不可识别时拒绝受影响批次，不把“其它 metadata”当作丢弃理由。

| 源字段/位置 | 目标字段/位置 | 重写与验证器 |
| --- | --- | --- |
| sessions.id、messages.session_id、turns.session_id | 对应 PG session 引用 | source+owner+旧 ID→唯一目标 session；目标已有记录不覆盖，复合 owner/FK 验证 |
| messages.id / parent_message_id | PG messages.id / parent_message_id | parent DAG 拓扑分配整数，验证无环/缺父及 parent<child，原时间保留 |
| sessions.summary_up_to_msg_id、分支 preferences/selected_branches、active leaf | PG 摘要锚点、preferences、active_leaf_id | 同一 session 消息映射，验证每个可选分支实际存在，不更改用户普通文本 |
| turns.id、assistant/user_message_id；turn_events.turn_id/seq | PG turn/message/event | source+turn 映射与消息锚点验证，保留原事件 seq/信封；缺失字段按已知源版本显式补齐 |
| notebook_entries.session_id/turn_id/question_id、分类关联 entry/category ID | PG notebook/分类关系 | 区分业务 question ID 与数据库 row ID，分类/题目不做全局数字替换，验证所有权/去重语义 |
| learning path/session/topic/source/interaction、reading workspace/material/session/link | 各 PG 领域实体/关联 | 同一 mapping registry，验证路径、资料和 session 双向引用/原排序/删除状态 |
| messages.events_json/metadata_json/attachments_json、事件 metadata | 相应 PG JSON 与资源引用 | 仅已定义的 session/message/turn/resource 引用路径重写；文件 locator 走资源清单，provider 私有/普通内容保持原样并按原脱敏规则输出 |
| operation request/result、cron job payload、图书/课程输入、旧链接 | PG 请求/调度/输入及迁移链接映射 | 版本化 typed parser 识别 schema 中 ID；幂等请求按目标规范重算指纹，旧在途操作不自动重跑；未知机器引用拒绝并报告 |
| MarginNote KB/device/object/cursor、Matrix user/device/room/session/token | PG 对应范围键/密钥状态 | 本地外键映射；远端协议 ID/opaque cursor 不重写，验证设备/KB scope、序列化/解密与撤销 |

旧 SQLite 没有首切片 PG operations 表时不凭空生成成功记录；迁移已有 PG schema 1 时 operations 和原请求保持原 ID/指纹，不能把 SQLite 的转换规则套到既有 PG。离线源可保留原字段以便审计，但正式业务只有目标映射后的权威版本。

## 7. 同步退出的 PocketBase 数据

当前 `deeptutor/services/session/pocketbase_store.py` 使用 `sessions/messages/turns/turn_events` 等 collection，`services/auth.py` 与 `services/pocketbase_client.py` 还有 users 认证路径。虽然应用不直接调用 sqlite3，它是默认工厂的另一运行后端；PG-only 取消它时必须处理其既有数据。

新增只读 exporter/离线 importer，支持本应用使用的集合/关系和实际版本，保留用户映射、会话/消息/事件与文件引用。PocketBase 内部 record ID 与业务 session ID 分开映射，字符串 message ID 转 PG 整数；不把用户密码/token、admin 凭证写入报告或直接用于目标认证。详细停写/导出/维护门禁见 design 第 6 节。不得删除用户远端 PocketBase、改写其 schema，或把其所有非 DeepTutor 集合纳入自动迁移。

## 8. 实施基线补录（2026-09-14）

[完整入口/依赖/测试矩阵](inventory-baseline.md) 补充实际 Learning/Reading 运行器、CLI cron、MarginNote KB 删除与 Memory 后台调用。PageIndex→OpenAI Agents SQLite session、LlamaIndex SQLChatStore 属于新增的**静态未激活风险**，须在任务 1.42/1.43 用最终安装制品验证，不能直接当作已有运行 SQLite，也不能因未激活就放过依赖升级。Matrix nio 0.26.0 / vodozemac 0.10.0 与线程协议已由 task 1.23 锁定并记录；PG schema 仍需 task 1.24 按该协议冻结。
