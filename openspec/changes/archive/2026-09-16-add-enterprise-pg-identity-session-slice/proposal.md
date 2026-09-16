# A1 首个实施子切片：企业装配、可信身份与 PostgreSQL 会话

> 后续决策说明：本 change 的 34/34 与 local 兼容测试是当时批准范围的历史证据。用户现已要求默认 Web/CLI/SDK 全部 PG-only、取消 local/SQLite，见[后续全量迁移 proposal](../migrate-all-sqlite-state-to-postgresql/proposal.md)。新目标尚未实施，不倒改本切片任务或把历史通过结果当作全仓迁移通过。

## Why

现有 DeepTutor 的容器/会话协议可复用，但身份、默认 scope、启动迁移和部分会话入口仍绑定本地文件或 SQLite；直接增加 PG Store 不能形成可信的企业调用链。按用户确认，首个 proposal 只交付 A1 内“企业装配 → 固定租户本地认证 → PG 会话 → 重连/恢复”的完整子切片，其余 A1 另立后续 proposal，避免一次实施整个结构化状态领域。

## What Changes

- 新增独立 `deeptutor-enterprise` 包与显式应用组合入口；core 只增加通用 provider/scope/lifecycle 接口，复用原有聊天、HTTP/WS 和 SDK 语义，不复制教学内核或运行时 monkey patch。
- 企业入口显式装配 PG、可信身份、Secret 和会话依赖，拒绝缺 provider、无 scope、不兼容 schema/核心版本和误用本地入口；导入/启动不创建本地身份、settings 或会话权威文件。
- 建立应用 PG 版本化迁移、受限运行角色、连接池及事务级 scope；固定内部 tenant、稳定内部 user、租户复合外键和 FORCE RLS。`StoreScope`、runtime registry 与进程内事件/命令 namespace 纳入 tenant + owner，不能复用不同租户的 runtime。
- 交付受控账号初始化/维护、本地密码登录、`dt_token`、退出及停用/凭证变更后的失效检查；固定租户仅由部署配置选择，管理员不默认读取他人会话。不接入 EduPlus2，不开放多租户生产。
- 交付 PG sessions/messages/turns/events 及会话自身的摘要、分支和偏好；接通纯文本聊天、继续会话、历史/trace、重命名、分支选择、regenerate、reply/cancel、事件重放与无外部资源的删除。保留事件信封和 `cost_summary`，不能以回放固定内容代替真实聊天。
- 收敛本切片的 SQLite/文件旁路，包括会话路由、SDK 默认初始化、后台账户枚举及启动迁移；未纳入的功能按明确依赖拒绝执行，不访问 local Store，不返回空列表/成功伪装已经适配。
- 提供单执行者下的持久状态、排空和中断后失败可见性，不承诺重启后自动续跑 agent。完成真实 PG、HTTP/WS/SDK、两测试租户及同租户双用户的正负向验收，保留独立本地模式回归。
- **BREAKING（仅企业入口）**：未认证/缺 tenant 的 local-admin 回退、客户端覆盖 tenant、未适配原生管理/工具入口不可用；独立 local/CLI 模式不随本提案强制改名或切 PG。

## Capabilities

### New Capabilities

- `enterprise-runtime-composition`：独立企业包、显式 provider/lifecycle 装配、切片能力边界及无本地回退。
- `enterprise-scoped-persistence`：应用 PG 迁移/角色/事务、可信 tenant/owner scope 与缓存/runtime 隔离。
- `enterprise-local-identity`：固定租户本地身份、受控初始化、认证/失效和最小身份操作审计。
- `enterprise-session-lifecycle`：真实入口的 PG 会话、事件、交互控制及单执行恢复。

### Modified Capabilities

无。当前 `openspec/specs/` 尚无正式规范；总纲 change 的四个能力继续持有完整里程碑要求，本提案新增细粒度实施契约，不复制或降低总纲规范。

## Impact

- **拟新增**：`extensions/enterprise/` 下包元数据、bootstrap/API 装配、identity、PG session/identity stores、应用迁移与集成测试；准确文件拆分见 [design](design.md)。用户于 2026-09-13 明确批准执行本 proposal；按 tasks 实施，仅使用独立隔离测试 PG。
- **拟调整 core**：`app/container.py`、`app/facade.py`、`multi_user/{models,context,paths}.py`、auth、session factory/protocol/scope、`services/session/turns/` 与会话/API 组合边界。只处理本切片实际依赖，不顺手迁移所有学习/题库模块。
- **接口**：保留已有 `/api/auth/*` 中本切片登录/状态/退出契约、`/api/sessions/*` 会话契约和 `/api/v1/ws`；不将通用 API 整体搬到 `/api/v1/tms/*`。TMS/OMS 页面及管理 API 留待对应后续 change。
- **依赖**：新增 PG driver/连接池和版本化应用迁移工具，置于企业包依赖中，经同步/异步调用兼容测试后锁版本；本切片不新增图 driver、S3 client、K8s provisioner 或 EduPlus2 SDK。

## Scope and Delivery Status

**状态：已获用户批准 apply，34 项子任务已实现并完成隔离验证；未合并、归档或上线，完整 A1/G1 未通过。** 2026-09-13 用户要求“执行proposal”。实现、真实 PG/模型、回归、费用边界及未交付范围见 [执行证据](execution-evidence.md)。

### 本次不交付，但完整路线仍必须交付

- PG 可编辑 settings、模型目录/grants 管理、完整审计查询；memory/notebook、题库/学习/阅读等其余已启用结构化状态。
- KB/动态 skills/personas metadata 与服务 binding、S3/附件/持久文件、LightRAG/HugeGraph 集成、真实教材和容量验收。
- `/tms` 完整管理体验、Woodpecker/K8s 发布、存量系统实际切换、EduPlus2、OMS、多执行者/HA。

真实文本聊天所需模型连接、固定工具白名单和非敏感启动配置通过**最终通用 provider 的受控只读部署配置 + Secret 引用**提供；不创建第二套可编辑配置库、测试专用聊天引擎或 JSON 投影权威。已获批准的完整 M1 功能不因本次只验收子集而被删减；尚缺的依赖阻断生产放行。

### 总纲与后续提案关系

上位范围：[总纲 proposal](../replace-rollout-with-three-production-stages/proposal.md)、[总纲 tasks](../replace-rollout-with-three-production-stages/tasks.md)、[企业实施总纲](../../../docs/enterprise/02-rollout-testing-and-migration.md)。本提案覆盖总纲 1.4、1.5、1.6 的主要实现以及 1.1/1.3/1.7/1.13 的适用子范围；具体对应见 [design](design.md#总纲映射与剩余责任)。

本 change 的 [tasks](tasks.md) 记录子切片执行证据；总纲保留原 90 项作为汇总门禁，只有原项的全部范围完成才可勾选，不因本切片完成自动勾选 1.7、A1 或 M1。其余 A1 后续分别规划配置/授权、个人内容及学习状态、资源元数据/检索契约和汇总验收；本轮不提前生成或假称这些 proposal 已存在。A3 环境/CI、B1 外部契约和 H 目标评估仍按总纲从 A1 起并行准备，不变成此切片的全部交付物。
