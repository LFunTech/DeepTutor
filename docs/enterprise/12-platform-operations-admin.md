# 12. 学校智能体管理后台与平台智能体运营后台

## 权责与当前状态

DeepTutor 本地部署继续保留自己的 Web 设置页；面向学校云服务的 **TMS（学校智能体管理后台）** 与 **OMS（平台智能体运营后台）** 是两个独立构建、独立部署的前端，共享同仓管理设计系统、表格/表单及服务业务组件，不共享应用源码、登录会话或敏感 DTO。后端可共用 DeepTutor 执行语义与企业扩展中的权威业务总账，不因此复制两套核心逻辑。业务文案使用“学校”；`tenant_id`、`tenant.*` 等技术字段保留。EduPlus2 `school_code` 是学校租户代码，不是稳定 ID 或授权凭据。

当前独立 OMS/TMS 只有**开发态高保真原型**；本地 DeepTutor Web 的 `/oms`、`/tms` 是 404 占位，原型生产路径亦返回 404。已实现的 EduPlus2 API-only 联邦访问与 `/enterprise/audit/eduplus2` 审计页不等于管理后台。真实平台身份、完整管理 API、执行者生效、供给/权益/用量闭环及正式前端尚须按实施提案验收；不得以原型 fixture、菜单显隐或保存草稿宣称已经上线。

现行双域权限设计以 [`add-enterprise-management-authorization`](../../openspec/changes/add-enterprise-management-authorization/proposal.md) 为待批准主合同；业务与原型以 [`add-c1-oms-operations-prototype`](../../openspec/changes/add-c1-oms-operations-prototype/proposal.md)、[`add-b2-tms-management-prototype`](../../openspec/changes/add-b2-tms-management-prototype/proposal.md)、[`add-enterprise-oms-business-logic`](../../openspec/changes/add-enterprise-oms-business-logic/proposal.md) 与对应实施 change 为准。旧“OMS 只读 Provider / 独立 DeepTutor 云端平台设置 / TMS 修改额度 / 每百万 Token 计费、租户费用、欠费及独立模型资格 webhook”已失效；旧 [`add-oms-token-billing-and-arrears`](../../openspec/changes/add-oms-token-billing-and-arrears/replacement-decision-draft-2026-09-26.md) 只保留历史，不执行其 tasks 或同步冲突 delta。三阶段发布门禁见 [02](02-rollout-testing-and-migration.md)，入口命名与当前实现见 [11](11-api-and-entrypoints.md)。

## 两级管理对象

| 范围 | TMS：当前学校 | OMS：平台获授权范围 |
| --- | --- | --- |
| 入口/身份 | `/tms`，EduPlus2 已交付身份/账号/学校核验 + DeepTutor PG 的本校 `tenant.*`；路径 `school_code` 与稳定学校 ID 绑定核对 | `/oms`，EduPlus2 既存 OIDC 身份及在线账号状态 + DeepTutor PG 的 `ops.*`、`platform`/`school` 范围和撤权 |
| 可维护 | 当前学校用户、应用/client、KB/文件等学校实例与已获授权资源内的使用分配；本校 ZIP Skill 自用 | 五类平台资源、全服务 Provider/连接及 Secret 引用、Skill global 发布/授权、服务供给、学校服务授权、统一赠送/充值额度与核对 |
| 只读 | OMS 配置的本校服务授权、统一额度清单、原生单位消耗明细；已授权 global Skill | EduPlus2 学校生命周期、TMS client/app 注册状态、必要脱敏跨校运行/审计；采购成本仅单独授权 OMS 角色 |
| 禁止 | 改写 OMS 额度/供给/平台 Secret、跨校访问、二次分配 global Skill | 直接开停学校、注册/注销 TMS client、编辑学校私有正文、冒充用户、管理任何学校账号或开通首位 TMS 管理员、把成本变成学校账单 |

OMS 主导航按工作台、学校与权益、资源目录、资源供给、用量与运行、审计与治理分组。对象从列表逐级进入具名专题抽屉：学校资料、服务授权、额度清单分开；用量在用量列表按学校筛选。新增/编辑/授权用独立表单模态框，撤销/发布等影响性动作另经确认；一个抽屉只负责一个专题，关闭保留列表筛选。五类资源为模型与外部服务、Agent/能力、工具与集成、知识/内容基础能力、运行资源。普通运营优先看到业务状态、影响和下一步，技术字段默认折叠；权限、加载、空、失败、同步延迟、待核对分别呈现，不用静态假数据上线。

DeepTutor 本地设置字段、provider descriptor、条件字段、执行校验仍是配置语义来源；**云端企业配置写入仅归 OMS**，覆盖连接、LLM/task/embedding/search、TTS/STT、image/video、解析/OCR、RAG 等实际服务。保存是草稿而非生效，须经过测试、发布、目标执行者装载确认；部分失败保留旧 active。Secret 只存受控引用，不回传明文。企业云端旧 `/settings` 平台管理页/API 及 CLI/SDK/后台直写旁路须在相应实施 change 中关闭；本地 Web 设置不因此退化。

## EduPlus2 client/app 与学校身份

TMS 管理员在当前可信学校上下文登记 `client_id`；DeepTutor 调 EduPlus2 通用 `POST /api/v1/open/oauth-clients/resolve` 核验权威 app ID、学校 ID、名称和状态。返回学校必须与当前稳定绑定一致，不能凭路径 `school_code`、同名学校、请求 header 或人工输入代管其他学校。同 provider 的 active `client_id` 唯一；同校同 app 只允许一个 active client。冲突返回 409，跨校拒绝；注销保留历史审计，替换 client 先 retire/revoke 旧注册。OMS 仅在 `ops.clients.read` 下受控查询，不提供注册、注销或暂停；跨校修复若确需平台操作须另立授权流程。Token exchange 仍要求 JWT、active registration、学校/app 状态和审计，详见 [11](11-api-and-entrypoints.md)。

学校管理员外部账号和学校归属来自 EduPlus2 已交付身份/在线账号/学校核验链路，各校隔离；本产品 `tenant.*` 由 DeepTutor Enterprise 程序按 PG 事实显式授权，`eit=adm` 或普通租户换票不授予 TMS 管理权。首位管理员身份由签名真实 `subscription.created.actor.user_id` 一次性登记，候选本人完成 TMS 登录并匹配后由 Enterprise 程序激活；OMS 不管理任何学校账号。DeepTutor 不另建 EduPlus2 密码或学校组织主数据。TMS 的用户、KB、应用管理必须只在当前学校 owner/grant 范围内，不能用菜单隐藏代替后端归属校验。本校额度及服务授权由 OMS 配置，TMS 只读；TMS 上传 tenant owner Skill 仅本校自用，与获授权 global 同名时先提醒并取得学校管理员确认，运行时 tenant 版本优先。DeepTutor builtin Skill 在云端作为只读 global，默认未授权，OMS 复核包版本并按校授权；本地 builtin 自动发现不变。

## 服务供给、额度与实际消耗

外部供应商经核验的服务资源形成**服务供给批次**；OMS 在同一额度列表中按“获取方式=赠送/充值”向学校授予原生单位额度。授予只是未使用承诺，真实供应商 attempt 才形成实际消耗；赠送先于充值，供给可授予量须扣除历史消耗、未用承诺与在途预留，不能重复扣。每个可调用服务分别校验学校授权、有效额度、兼容供给、配置 readiness 与可信硬上界；无可信上界或证据时不冒充可硬配额放行。Token 使用供应商可信 usage，非 Token 使用合同认可的原生单位；Agent 顶层不重复扣底层子调用。远端结果未知、流中断、异步未完成保持预留并标为待核对，不按零释放。

**服务额度耗尽只拒该服务的新调用**；学校账号仍可登录、进入获授权的 TMS 管理页、查询历史及使用其他服务，平台账号的 OMS 管理也不受其牵连。EduPlus2 签名 lifecycle webhook 是学校开通/暂停/恢复的唯一权威，暂停才按其语义影响全入口，OMS 只查询；额度不能写成 `tenant.suspended`。本目标不设置学校售价、费用、账单、欠费或独立模型资格事件。OMS-only 供应商成本须有采购/调用证据和独立权限，缺证据显示未核定，不向 TMS 返回。

## 权限与迁移矩阵（目标，非当前已开放 API）

下列 `ops.*` 与 `tenant.*` 都是 **DeepTutor 本产品应用能力**，不声称是 EduPlus2 relation。必须核实既存 OIDC issuer/audience/client 与稳定主体/学校身份；主体 `(issuer,sub)`、OMS/TMS 动作与 `platform`/`school` 范围、撤权版本及默认/自定义应用角色由 DeepTutor Enterprise 程序管理和判定，PG 只版本化保存事实并提供隔离/一致性兜底，不以 PG 用户/GRANT/RLS 作为操作者授权。首次登录默认零权。平台 admin、operator、auditor 按当前具体能力授权，不由角色名称、`tenant_admin`、`eit=adm`、JWT role、Webhook `actor` 或伪造 header 推导。缺认证/身份合同、本地权限服务或 403/200 正负例时不装配跨学校写路由；不修改 EduPlus2/OpenFGA/Keycloak。

| 入口/API | 后端能力与目标校验 | 边界 |
| --- | --- | --- |
| `/tms`、`/api/v1/tms/kbs`、本校资源 | `tenant.tms.access`、`tenant.kb.manage` 等具体权限 + 当前学校 owner/grant | 学校管理员或显式授权角色；不以 KB 权限作为全部菜单的共同前置 |
| `/api/v1/tms/members`、`/roles`、`/access-grants` | `tenant.members.read`、`tenant.permissions.manage`、`tenant.access.manage` 按读写分别授权 + 会话当前 `school` | 只选本人已登录且学校归属经核验的主体；不自授、不撤最后管理员、不扩大 OMS 服务授权 |
| `/api/v1/tms/eduplus2/clients` | `tenant.clients.manage` + resolve 权威学校/app + 唯一约束 | 仅当前学校注册、查询、注销；OMS 不能调用写路径 |
| `/tms` 额度/用量 | `tenant.quotas.read`、`tenant.usage.read` + 当前学校安全 DTO | 无额度新增/调整/撤销，不返回供给成本/Secret/跨校字段 |
| `/oms`、`GET /api/v1/oms/tenants` | `ops.oms.access` + `ops.tenants.read` + 查询所需 `school` 范围 | EduPlus2 lifecycle 只读，学校管理员不能进入 |
| OMS 平台资源、Provider/连接、Secret 引用 | `ops.providers.read/manage`、`ops.credentials.manage` 逐动作 | 全局配置/Secret 须 `platform` 范围；配置写入仅高权限，Secret 管理不从普通读继承 |
| OMS 供给、学校服务授权与额度 | `ops.supply.read/manage`、`ops.entitlements.read/manage`、`ops.quotas.read/manage` 逐动作；未定向采购用 `platform`，学校定向供给/授权/额度用目标 `school`（兼有则双查） | 写入须版本/幂等键、原因和审计；不得改 lifecycle |
| OMS 用量、核对、成本、审计/导出 | `ops.usage.read`、`ops.reconciliation.manage`、`ops.cost.read`、`ops.audit.read/export` 分权 | 成本/导出单独授权，待核对不伪作零；不读学校私有正文 |
| OMS client/app、任务状态 | `ops.clients.read`、`ops.jobs.read` | 查询脱敏元数据，不在 OMS 注册 client 或任意重试/取消任务 |
| OMS 平台人员角色与学校操作范围 | `ops.permissions.manage` + `platform` 授权治理，目标学校须核验；可授予动作/范围另受委托上界限制，不隐含目标学校业务读权 | 只维护 DeepTutor 产品权限，默认零权、受控初始管理员、版本/原因/审计/撤权；不编辑外部账号或学校 |
| TMS 首位管理员本人激活 | 签名真实 `subscription.created.actor.user_id`、目标应用/学校绑定与本人 OIDC `sub` 匹配 | 仅 Enterprise 程序一次性激活该校首位 `school_admin`；mock/system/null、重放、错校或身份不匹配均不授权 |

正式 UI 在 OMS “审计与治理”下设平台人员、角色与动作、平台人员学校范围、授权审计；TMS 学校侧开通及“成员与权限”下设成员、学校角色、访问关系、授权记录。两端均为列表→聚焦详情→独立操作模态框，显示范围、角色版本、有效期、原因、权限差异、审批/撤权影响及审计编号。首次 TMS 待开通主体只能看事件 actor 待本人匹配/待核对状态，不看学校业务数据；OMS 不能搜任意外部 `sub` 直接赋权。401 重新登录、403 清理旧敏感缓存、409 回读版本、外部核验失败显示暂不可操作，不把错误伪装为空结果。

所有管理接口先认证/逐动作授权，再判定所需 `platform`/`school` 范围；涉及学校时绑定权威目标学校；普通业务 API 不接受任意学校 override 或 BYPASSRLS 连接。前端显隐与后端 401/403/404、版本冲突及审计一致。写入审计包含 actor、目标学校、前后版本、原因、request ID、结果，绝不记录 token/Secret/完整私密正文；导出同样按字段白名单和权限限制。LightRAG 运行元数据由受控 API/观测取得，OMS 不持图凭证、不读检索正文或直连内部 PG/HugeGraph。

## 实施与验收门禁

正式实施优先 `extensions/enterprise/` 和企业装配；如缺跨 CLI、HTTP/WS、SDK、后台一致的通用 seam，先单独审阅 upstream-neutral 核心补丁、入口影响、上游合并风险及测试，不能因原型直接修改核心。OMS 应用角色、权限、学校绑定及审计只走 DeepTutor 企业 PG 版本化迁移的 dry-run/apply/verify、重复幂等及 drift 检查，不手工改真实数据，也不修改 EduPlus2/OpenFGA/Keycloak。TMS 外部身份/在线账号/学校核验若缺既存接口，须由所属团队独立交付；本产品 TMS `tenant.*` 权限只在本仓库实施。

至少验证：可信平台/学校身份与深链学校绑定、默认/自定义角色 200 和越权 403、OMS 有权限的供给/授权/额度写入与审计、TMS 额度只读及跨校负例、真实配置逐服务执行者确认与失败回退、赠送优先和并发硬上界、逐 attempt 原生单位用量/未知预留/Agent 防双扣、额度耗尽但登录/管理/历史/其他服务仍可用、EduPlus2 lifecycle 独立准入、旧云端管理旁路关闭且本地设置正例。另验证 CLI、HTTP/WS、SDK、后台 session ownership 与审计关联、生产原型 404、两端独立构建和共享组件一致性；未验证项不随文档勾选或开发原型自动放行。EduPlus2 client/app 注册与 token exchange 的正负例沿用 [11](11-api-and-entrypoints.md) 的受控契约。
