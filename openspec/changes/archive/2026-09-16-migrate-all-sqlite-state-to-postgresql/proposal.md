## Why

首个身份/会话切片已经完成，但默认应用仍选择 SQLite，题库、学习、阅读、调度、Partners、MarginNote 与快照读取也有独立数据库或直连旁路。用户进一步明确：**全部迁到 PostgreSQL，并取消独立 local/SQLite 模式；默认 Web、CLI、SDK 都必须连接 PG**。仅扩大企业聊天白名单、关闭其它功能或保留 SQLite 备用入口不满足本次要求。

## What Changes

- **BREAKING：PG-only 默认运行契约。** 本仓库构建的 Web/API/WS、`deeptutor start/serve/run/chat`、其它业务 CLI、SDK 和后台执行全部使用应用 PG。缺配置、不可达、schema 不兼容即明确失败，不创建 SQLite、改走 PocketBase 或内存业务库。允许本机运行并连接本机 PG；取消的是无 PG 的存储模式，不是 CLI 或本机部署。
- 复用并下沉首个切片的通用 PG 连接、scope、迁移、身份与会话实现到 core；企业包继续负责企业部署、外部身份与治理策略，core 不反向依赖企业包。保持一条 schema 历史和一份业务数据，不能复制第二套 tenant/session 表。
- 完整替换默认会话/消息/事件及题库条目、学习/掌握路径、阅读目录/工作区、cron、Partners 状态、MarginNote 对象/设备/游标/删除标记；Memory 快照、图书/课程/导入/agent 工具改用同一 PG provider。Matrix 的间接存储与 E2EE 状态同样纳入，详见 [调用清单](inventory.md)。
- 保留现有可用功能、API 数据契约、分支/分页/搜索、事件和取消/恢复语义；同步改造真实调用方、后台与默认前端流程，不以空数据、禁用菜单、缩减 capability 或仅通过新专用入口验收。
- 交付受控、离线、只读 SQLite 导入：显式归属映射、源版本/指纹、ID 冲突与引用重写、导入账本/重试、验证及停写切换。禁止业务启动自动迁移、写旧库或双写。SQLite 仅允许在隔离导入工具及旧格式测试 fixture 使用，运行态临时 SQLite/cache 也不例外。
- 同步退出的 PocketBase 业务后端也交付获授权只读导出/离线 PG 导入，复用相同 manifest、归属/ID 映射与验证；不因拒绝旧 backend 就把其现有历史数据搁置，不删除或改写用户远端服务。
- 更新完整应用与 CLI-only 包、requirements、开发/测试与容器启动说明；实际 PG 测试替代 SQLite 运行测试，增加全进程和子进程零 SQLite 访问门禁。

## Capabilities

### New Capabilities

- `postgres-only-runtime`：默认入口、依赖装配、可信身份、故障关闭及完整能力兼容。
- `postgres-business-stores`：全部原 SQLite 业务域、间接客户端状态和调用链的 PG 持久化及并发/隔离。
- `sqlite-to-postgres-cutover`：只读导入、幂等与冲突、完整验证、停写切换和受控恢复。

### Modified Capabilities

当前 `openspec list --specs` 为空，尚无正式 spec 可声明 MODIFIED；以上作为新能力记录。它们**明确取代**首切片中“入口与独立本地模式兼容”的后续目标，不倒改该切片已完成的历史证据。与两个活动 change 的规范收敛顺序见 [design](design.md#规范替代与总纲映射)；归档仍须单独批准。

## Impact

- 默认启动、认证、容器/provider、路径/缓存、各业务 Store、全部相关调用方、安装包和测试基础设施；迁移是破坏兼容的版本发布，不能当作现有零配置安装的透明小补丁。
- 需要应用 PG schema/default-data/data-import migration；复用本仓库版本化 runner、复合 FK/RLS 与受限运行角色。**不引入另一套 Flyway/Alembic 历史，不修改外部 Keycloak/OpenFGA、检索 PG 或 HugeGraph。**
- PG-only 指本应用所有 SQLite 状态退出运行，不把 S3 文件、HugeGraph 图、只读 prompts 或全部 JSON/Markdown 都搬进 PG。完整 settings/grants/memory 正文、对象与检索替换仍按 A1/A2 总纲交付；本次涉及的 SQLite 依赖不能以此排除。

## 状态与批准边界

2026-09-13：用户确认全量 PG-only 方向及取消 local 兼容。2026-09-14：设计评审后获准在当前 master 工作区直接实施，保留全部已有修改，不提交或推送。本 change **实施中**，完成范围以 [tasks](tasks.md) 与 [execution-evidence](execution-evidence.md) 为准。前置为首切片的工作区实现和隔离验证（34/34，未合并/发布），不重新勾选或抹去该记录。

实现与数据库验证使用隔离合成数据，不连接用户业务数据库或导入用户旧数据。真实导入仍须另行核实源、目标、归属与备份并取得授权；不提交、发布、切换或归档。用户已指定 `.secrets` 中模型配置，并明确本次真实模型验收的调用次数与供应商费用暂不设上限；该授权仅供必要验收，逐调用记录用量且不输出密钥。所有未完成实现及验收任务保持未勾选。
