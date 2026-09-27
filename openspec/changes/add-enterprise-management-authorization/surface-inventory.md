# 管理授权入口盘点（2026-09-27，实施基线，尚非放行矩阵）

本表只描述 DeepTutor 仓库现状和正式接线时必须检查的动作，不把开发态原型的 `role` 切换或合成 fixture 当作服务端权限。权威动作、范围和敏感级别来自 `management/0001_authorization_base.sql`；所有模板均**不默认授予登录者**。

## 当前可达性

| 入口 | 当前状态 | 正式接线约束 |
| --- | --- | --- |
| 企业 HTTP | `api/application.py` 的 router 白名单仅含认证、Webhook、审计、会话、资源、语音、WS、健康与公开 UI 设置；无 `/api/v1/oms/*`、`/api/v1/tms/*` 管理路由 | OMS/TMS 分别接独立可信会话；每条读/写/导出 API 重新判定动作与对象，不复用普通 `dt_token` |
| 企业 WS | `/api/v1` 下复用通用 turn WebSocket；无管理写命令 | turn/session 身份与 owner 不得转换成 OMS/TMS 管理权；未来新增管理消息须独立路由与同一授权服务 |
| 企业 CLI / SDK | `test_oms_management_entrypoints.py` 固定 CLI 命令集与 SDK 公共方法无 OMS/TMS/Provider/额度写方法 | 未来新增命令/SDK 方法不能绕过本产品 Enterprise 程序鉴权和外部在线复验；PG 只保存授权事实 |
| 后台 job | 当前无管理角色、学校开通或额度授权 job 入口；存在其他业务恢复/会话任务 | 后续管理任务须显式服务主体、发起学校及派发时复验；不得借平台管理员 token |
| 独立 OMS/TMS Web | 仅 `/oms/prototype/*`、`/tms/prototype/demo-school/*` 为 development 合成演示；两端 `app/page.tsx` 不开放正式入口，生产原型路径 404 | 正式界面只接各自安全 DTO、独立会话和 API client；不能把合成状态持久化为权限 |
| core 旧路由 | `test_application.py` 的 router allowlist 与旧写入口负例仍在 | 不靠路由注册顺序覆盖；保留未挂载状态，正式接线后逐项核对旧入口仍 404/405 |

旧写入口固定负例包含 `PUT /api/settings/catalog`、`/draft`、`/ui`、`/mcp/servers/example`，`POST /api/settings/apply`、`/tests/llm/start`、`/providers/openai-codex/oauth/start`、`/api/skills/create`、`/api/skills/install`、`/api/partners`、`/api/v1/oms/releases`、`/providers`、`/tenants/foreign-tenant/grants`，`PUT /api/skills/pdf`、`/api/v1/tms/settings/model`、`/api/v1/oms/secrets/provider`，`DELETE /api/skills/pdf` 与 `POST /api/v1/tms/settings/model/activate`。其中 `PUT /api/settings/ui` 应为 405，其余应为 404；普通租户登录或伪造 `X-Scopes` 均不得改变结论。

## 权威动作与原型入口

| 原型页面/操作组 | 服务端动作与目标范围 | 默认模板（须显式授予） | 当前缺口 |
| --- | --- | --- | --- |
| OMS 工作台、学校列表/聚焦学校 | `ops.oms.access` (`platform` 或逐 `school`)；每所学校另 `ops.tenants.read` (`school`) | security/config admin 平台入口；operator/auditor 逐校入口 | 原型菜单显隐不是 API；跨校列表只能逐校过滤，不得以入口动作全量返回 |
| OMS 供应商连接、模型与服务、Secret | `ops.providers.read/manage`、`ops.credentials.manage` (`platform`) | config admin | Secret 须单独动作、字段脱敏与审计；原型其他资源目录按钮尚未逐项映射正式 API |
| OMS 服务供给 | `ops.supply.read/manage` (`platform` 或逐 `school`) | operator 仅逐校；全局供给另授平台动作 | 全局和定向同时影响时双范围判定；原型按钮未接权限 DTO |
| OMS 学校权益/额度 | `ops.entitlements.read/manage`、`ops.quotas.read/manage` (目标 `school`) | operator 逐校 | TMS 不得有写入口；数量/版本/幂等与权限均须在同一事务复核 |
| OMS 用量、成本、审计/导出、客户与任务 | `ops.usage.read` (`school`)、`ops.cost.read` (`platform`)、`ops.audit.read/export` (`both`)、`ops.clients.read` 与 `ops.jobs.read` (`school`) | operator/auditor 有部分读动作；成本、导出不在默认模板 | 成本/导出需独立敏感动作；前端缺正式导出授权与 DTO；不得泄漏跨校或私有正文 |
| OMS 异常核对 | `ops.reconciliation.manage` (目标 `school`) | 无默认模板 | 后续仅经显式角色/委托发放；原型不能充当操作入口 |
| OMS 平台人员、角色/动作、人员学校范围、授权审计 | `ops.permissions.manage` (`platform`) 启动写；每个待授 `ops.*` 另受委托上界；审计读另 `ops.audit.read` | security admin 只有治理动作，不自动拥有业务动作 | 原型 4 个页面已区分平台人员与学校账号；正式按钮、候选来源、双人审批、版本/审计回读未接 API |
| TMS 学校概览、成员与权限 | `tenant.tms.access`、`tenant.members.read` (会话唯一 `school`) | school admin/operator/auditor | 学校码只作可信绑定一致性检查；目录查找须独立第三方应用用户令牌合同 |
| TMS 角色/成员授予、撤权、授权记录 | `tenant.permissions.manage` (当前 `school`)；待授 `tenant.*` 另受委托上界 | school admin；首次登录不自动获得 | 首位管理员另用真实订阅 actor 一次性引导/本人激活流程，不能在直授表单给出；高风险角色待审批 API |
| TMS 应用/成员与服务访问 | `tenant.clients.manage`、`tenant.access.manage` (当前 `school`) | school admin/operator | 服务 grant 不带额度数量且不得越过 OMS 学校权益；关系两端回读同一持久事实 |
| TMS 配额/用量 | `tenant.quotas.read`、`tenant.usage.read` (当前 `school`) | school admin/operator/auditor | 只读；原型调用与配额 fixture 不得成为真实账务数据 |
| TMS 知识与共享资源 | `tenant.kb.manage` (当前 `school`) 加目标对象 owner/显式 grant | school admin | 管理动作不等于个人会话、笔记、记忆、文件或 KB 正文读取 |

迁移目录共 OMS 19 个、TMS 9 个动作；`sensitive=true` 的写/成本/导出不得经普通单人直授，`tenant.school.bootstrap` 只由 Enterprise 程序在真实订阅 actor 本人匹配及一次性栅栏通过后执行，不放入普通角色授权表单。模板版本固定在 assignment；自定义角色只能引用**同应用域、同目标范围、当前 active** 的 catalog key，并且授予时逐动作小于等于授予者显式委托上界。原型的动作选择器只是有限合成场景，不是目录全量展示或服务端上限。

## 开发原型操作标签核对

以下为对 `OmsPrototype.tsx`、`OmsAuthorization.tsx`、`TmsPrototype.tsx`、`TmsAuthorization.tsx` 的导航、`Button`、`rowActions`、确认框和详情链接逐组扫描。`确认`、`取消`、`查看关联对象` 不是新权限，只沿用发起操作或目标读动作；任何未列入 PG catalog 的原型写操作都**不得**直接迁成正式 API。

| 原型可操作标签组 | 正式后端动作；额外对象限制 |
| --- | --- |
| OMS 运营概览、学校资料、学校列表/服务资料 | `ops.oms.access`，逐校 `ops.tenants.read`；学校详情还须对应权益/额度读动作，不因导航可见返回全校 |
| OMS 服务授权（演示）、撤销授权、授予额度、调整额度、撤销未用额度 | `ops.entitlements.manage` 或 `ops.quotas.manage` + 目标学校；读取消耗明细另 `ops.usage.read` |
| OMS 模型与服务、Provider profile/模型新增、配置草稿/提交发布、供应商连接新增/编辑、凭据来源/状态 | 读 `ops.providers.read`，写 `ops.providers.manage`；凭据读取/写入另 `ops.credentials.manage`，Secret 不进入普通 DTO |
| OMS Agent/工具/Skills/知识基础能力/运行资源的平台策略草稿、适用范围草稿、管理平台策略、保存草稿 | 目前只有合成原型；catalog 未给这些资源独立写动作，**正式入口未定义且不得按 `ops.oms.access` 放行**；须在所属提案扩目录后单独授权 |
| OMS 服务供给、取得记录、供给项目、关联供给/额度/学校、待核对 | 读 `ops.supply.read`，变更 `ops.supply.manage`；异常核对写另 `ops.reconciliation.manage`，并按全局/逐校目标选 scope |
| OMS 用量、调用详情、审计与治理、授权审计、导出 | 逐校 `ops.usage.read`、对应范围 `ops.audit.read`；成本另 `ops.cost.read`、导出另 `ops.audit.export`；原型无可放行正式导出按钮 |
| OMS 授予/撤销平台角色、授予学校范围角色、新增自定义角色、复核/拒绝角色或授权、选择候选、身份与核验 | `ops.permissions.manage` + 逐动作/范围委托；敏感角色需双人审批，候选只来自可信 OMS 登录登记；选择/详情不能自填 `sub` 或查询学校账号 |
| TMS 学校概览、成员资料/学校角色/本校目录查找 | `tenant.tms.access`、`tenant.members.read` + 当前学校；目录还需获批第三方应用用户令牌与数据策略，不以 `tenant.members.read` 代替外部目录授权 |
| TMS 学校角色新增、角色动作、成员授予/撤销、授权记录 | `tenant.permissions.manage` + 当前学校及逐动作委托；首位管理员另 `tenant.school.bootstrap`，高风险不从直授表单提交 |
| TMS 应用新增、应用资料/接入状态、服务范围添加/移除、成员访问授予/撤销 | `tenant.clients.manage` 或 `tenant.access.manage` + 当前学校；服务须先在 OMS 给该校授权，成员/应用关系双向同源回读 |
| TMS 服务资料、配额清单/关联配额/消耗明细、调用用量 | `tenant.quotas.read`、`tenant.usage.read` + 当前学校；无额度写动作，原型的“新增服务”仅指本校应用使用关系 |
| TMS 知识库、文档清单、处理任务/申请重试、访问范围、共享资源 | `tenant.kb.manage` + 当前学校；正文/个人资源另 owner 或显式 grant；处理重试目前仅合成原型，不得借学校管理员角色读取他人私有正文 |
| TMS 管理事件、授权记录 | 当前学校内脱敏事件读；catalog 尚无独立 `tenant.audit.read`，正式审计读方法须在授权服务设计时限定为 `tenant.permissions.manage` 的受控回读或另扩目录，不得以 `tenant.tms.access` 返回全量审计 |

`test_application.py` 固定企业 API 的 router allowlist、旧写入口 404/405、普通租户 token 和伪造 `X-Scopes` 不开放 OMS/TMS；`test_oms_management_entrypoints.py` 固定 CLI/SDK 没有管理直写。当前 `deeptutor/persistence/postgres` 的 `GlobalScope` 通用 seam 只表示无租户事务上下文，**不表示平台权限**；上游 `upstream/main` 的实际合并演练仍属 5.1 门禁，不属于本盘点通过的证据。

## 源码/合并风险及未闭合项

- 本轮新增管理授权/授予/撤权代码仅在 `extensions/enterprise`，无新增 core runtime patch。工作区既有 `deeptutor/persistence/postgres/{scope,connection}.py` 的 `GlobalScope` 泛化是上游中立的事务 scope seam，但其当前上游合并演练尚未完成；不将本次单测等同于 upstream mergeability 验收。
- 现有按钮/菜单和 API/CLI/SDK/WS/后台均已盘点；未来真实 API 的 method、对象 ID、状态 descriptor、403/409 仍未实现，须在 3.2、4.1–4.3 逐路由补可执行负例。权限 catalog 的 28 个动作大于 OMS/TMS 原型动作选择器子集，不能以原型选项证明所有动作都接入。
- 旧 `oms/authorization.py` 基于已撤回发送端平台权限端点，现已删除并以入口负例固定不可导入；正式实现仍须以本仓库 `management.authorization` 为唯一决策源，不能因 OIDC 验签通过就获得 `ops.*`。
