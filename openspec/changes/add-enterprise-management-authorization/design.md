# 设计：OMS/TMS 双应用域权限与管理交互

## Context

需求与决策见 [proposal](proposal.md)。当前普通第三方 JWT exchange 依赖 `tid/eui`，不能成为 OMS 平台会话；`PlatformOidcJwtVerifier` 尚未装配。`oms.school_bindings` 的 `0011` 仅建空表，未经受控核验。TMS 曾假设外部管理员 webhook/双负责人权限；用户现明确首位管理员身份由真实 `subscription.created.actor.user_id` 提供，本产品程序负责一次性引导与本人激活。两端目前只有合成原型，生产管理入口未开放。

**验证证据分级**：2026-09-26 test-cn Woodpecker #58、Webhook secret 同步和 EduPlus2 控制台 8/8 个 `subscription.*` mock HTTP 204 只证明签名 demo 接收；真实事件仍 503。2026-09-18 的真实 discovery/JWKS、M2M、client resolve 和本地交互登录/WS 证据可复用；当时 profile/permission M2M POST 曾返回 404/405，过期 user JWT 的 smoke 未完成完整 exchange。用户现已指定 OMS Client ID，但这些证据仍不等于 `eduplus-platform-admin` 的授权码登录、实际 token audience、在线账号状态、学校权威绑定、TMS 管理员身份或权限撤销已验收。实施时只针对缺口做脱敏核验，不重复已通过的 Webhook demo。

## Goals / Non-Goals

**Goals**：一个 **DeepTutor Enterprise 程序授权内核**、两个互不继承的应用域；每个菜单、按钮、深链、API、导出和后台动作可追溯到具体动作与目标范围；安全开通首位学校管理员；即时本地撤权；清晰呈现待开通、无权、过期、学校停用及身份核验失败。

**Non-Goals**：不成为 EduPlus2 用户、学校、密码、账号停用或订阅生命周期主数据；不修改其代码/Keycloak/OpenFGA；不让 OMS 日常管理 TMS 成员、client、私有正文或额度以外的学校资源；不赋予 TMS 平台配置/供给/额度写权；不让角色代替个人 owner/grant；不把原型 fixture 变成生产权限源。

## Decisions

### 1. 权威、身份和会话

EduPlus2 已交付且适用的 OIDC issuer/JWKS、client/audience、稳定 `sub` 和可核验的学校身份绑定只证明**认证与身份识别**，不决定任何本产品角色、动作、委托或开通资格。DeepTutor Enterprise 程序是 OMS/TMS 应用权限的唯一决策与写入权威；PG 仅持久化该程序使用的主体、授权、审批、版本和审计事实。对 OMS 使用独立平台会话，按 `(issuer,sub)` 绑定；对 TMS 使用独立学校会话，将已认证学校标识映射到受控绑定的内部学校。`tid/eui/eit` 可作为 TMS 既有租户协议输入，但 `eit=adm`、JWT role、用户名、外部 profile 缓存不自动授予本产品管理员权限。身份有效性或学校身份绑定未获证明时敏感写入失败关闭；学校生命周期 Webhook 是独立业务状态输入，不产生授权。两端 session 使用不同 audience、cookie/存储与 CSRF/Origin 边界，不能互换；不得把普通租户 `dt_token` 变成 OMS token。

**OMS Client 合同**：用户指定 EduPlus2 平台管理端 Client ID 为 `eduplus-platform-admin`，它是 OMS 平台身份对接的预期 Client，而不是每校 Webhook 下发的应用 Client。正式配置按环境确定 issuer/端点及公开 Client ID，Secret（若该 Client 使用）只留服务端；登录回调必须验证真实授权码换票结果的签名、issuer、`azp`/client 绑定、适用 audience、状态与稳定 `sub`。`client_id` 与 token `aud` 不应预设相同，也不能仅凭 `azp=eduplus-platform-admin`、平台 JWT role 或 Client Secret 授予 `ops.*`。该 Client 是否具备适用于 OMS 的平台人员检索、在线账号核验和授权码登录能力仍须目标环境实测；在证据形成前保持正式登录/管理写入口关闭。

**人员发现不是授权**。2026-09-27 核对的 [User Data API](https://eduplus-test.f123.pub/docs/user-data/user-data-api/) 文档将 `/api/v1/me/profile` 限定为当前登录用户本人，将 `/api/v1/open/userdata/users` 限定为经审批的第三方应用授权码**用户令牌**（`azp=app_credentials.client_id`）、有效学校订阅及 `DataAccessPolicy ∩ UserAccessPolicy` 可见范围。Webhook 的 `oauth_client.client_id/client_secret` 和 `client_credentials` M2M 令牌不自动满足此条件；M2M 文档中的 `/api/v1/users` 只是调用示例，尚未核实可用性、目录范围、学校隔离和授权用途，不能接为管理候选源。TMS 若以其学校会话访问目录，须先证实该会话所用 OAuth Client 已按第三方应用审批，并在后端代理按可信学校 ID 过滤/复核可见结果；若不是该类 Client，须另设计受控的授权码用户会话，不可偷偷把 M2M 令牌、学校管理后台 token 或 OMS token 顶替。`dept_id` 在当前 `/users` 文档中虽被接受但不生效，不能用于隔离；任何返回的 `user_id` 是 EduPlus2 内部 ID，`k_user_id` 才对应 Keycloak `sub`，均不能脱离可信 issuer、当前学校及候选本人登录直接赋权。目录仅包含可见已有账号，主数据中的未开通人员不能成为授权候选。

TMS 的“查找成员”只用于有 `tenant.members.read` 的本校管理员定位和辨认对象：服务端分页查询、最小字段映射，区分结果为空、策略无范围、未开通目录能力、令牌失效、订阅失效和上游故障；不得全量同步学校账号至本产品或把搜索关键词/手机号当稳定主体键。选中目录记录后，只有本产品已登记且由本人可信 TMS 登录绑定的 `(issuer,sub,school)` 与目录 `k_user_id`、权威学校 ID 同时匹配，才可进入授权确认。未登录者可显示“请本人先登录”指引，但不创建待激活 assignment，也不让管理员手填 `sub`。`/api/v1/me/profile` 只能支持登录者本人核验，不能用于检索别人；是否提供足够在线账号/学校停用状态仍须单独验收。

OMS 平台人员列表与候选来自以 `eduplus-platform-admin` 完成可信 OMS 登录的待授权登记，以及将来**单独核实**的平台人员目录（如存在）；不得调用学校 `/open/userdata/users` 或把其 `k_user_id` 当平台任职证明。首位平台安全管理员的初始受控登记另行验证，不能由普通待授权候选自举。

已有外部能力按“已验证、需补针对性验证、不可用”登记，附环境、接口、调用身份、脱敏响应/时间、失败模式与有效期。已通过的 test-cn mock 只登记为 Webhook demo，不在权限门禁中重做；旧本地 discovery/resolve 可作为机制证据，但正式 OMS/TMS 的适用性须分别验证。未知接口不臆造名称或成功语义。

### 2. 授权模型与决策顺序

企业 PG 保存 `principal`（外部 issuer/sub、状态/版本）、`application`（固定 `oms`/`tms`）、`role_definition` 与不可变版本、`role_action`、`assignment`、`scope_grant`（`platform` 或经核验的 `school_id`）、授予委托上界 `delegation_policy`、有效期、`policy_version`、审批命令与追加审计。**所有请求先进入 DeepTutor Enterprise 的统一 PEP/授权服务**，由程序读取这些事实、按当前动作、应用域、目标对象/范围、主体状态、授予有效期及学校绑定版本逐项计算；未匹配即拒绝。PG RLS、CHECK、唯一性和事务锁只做数据隔离、完整性及撤权竞态兜底，不能把连接使用的数据库角色或 RLS 可见行当成操作者的 `ops.*`/`tenant.*` 许可，也不为每个操作者创建 PG role。`ops.*` 只属 OMS；`tenant.*` 只属 TMS，且仅 `school` 范围。自定义角色不能声明另一应用域动作或未登记的 key。`ops.permissions.manage` 或 `tenant.permissions.manage` 只允许启动授权变更；可授予的动作/范围另受版本化委托上界限制，且不因可委托而获得该业务动作的执行权。OMS 安全管理员持 `platform` 范围的授权治理动作可向经核验学校发放被委托的 `school` grant，但不因此读取学校业务数据或自动取得该校业务动作。角色模板修改不静默扩展既有 assignment：受影响主体需显式确认新角色版本。旧 assignment 固定其可扩权的动作上界；全局动作停用/收缩以退役标记和策略版本栅栏覆盖所有旧版本，主体/范围撤权直接使 assignment 失效，故收缩/撤权立即生效而不会因仍引用旧角色版本复活。默认角色可建议最小权限，但任何首次登录均默认零权。

`platform` 授权不能从某一 `school` 授权推导；全局 Provider/Secret/未定向供给查 `platform`，学校权益、额度和学校定向供给查指定 `school`，同时影响两者时双查。OMS 跨校列表/导出只包含逐校已授权目标；不能凭 `ops.oms.access` 列出全部学校。TMS 请求从会话的唯一学校绑定构造目标；URL `schoolCode`、query/body/header 只可做一致性比对，不可切换学校。TMS 的 `tenant.*` 管理能力不等于成员个人会话、笔记、记忆、私有文件或 KB 正文读取，后者仍由 owner/已支持的显式 grant 控制。应用/服务访问 grant 不能扩大 OMS 学校服务授权，也不包含额度数量。

高风险 OMS 平台授权（`ops.credentials.manage`、`ops.cost.read`、`ops.audit.export`、`ops.permissions.manage` 与委托上界扩展）需要两名不同且当前有治理及相应委托资格的平台审批者；被授权人不能参与自身授权/审批。授权变更按目标 `(application,principal,school)` 加锁、版本比较并写追加审计，审批期间任何一方被撤权或外部失效即失败关闭。普通学校日常成员访问授予可由本校具备委托上界的管理员单人完成，但不能自授、自批或撤销最后管理员。

服务端决策顺序：认证并验证应用会话 → 在线核验外部账号/学校状态（按操作风险）→ 解析权威学校绑定 → 读取当前本产品主体与 policy version → 逐动作和范围授权 → 资源 owner/grant 与 OMS 服务权益等业务前置 → 事务内锁定/复核授权、绑定、对象版本 → 写入并追加审计。平台/学校管理写、导出、敏感读取均要求当前决策；只读缓存如使用必须带版本和短 TTL，不能用于写入。撤权与并发写遵同一锁序，撤权提交后的请求不能凭旧会话成功。后台 job 只用显式服务主体 grant、原始可信发起归属及派发时重验，不借平台管理员 token。旧核心 admin/OMS router 不挂企业 app，CLI/SDK/WS 没有直写旁路。

### 3. 角色、动作与管理员开通

默认模板均以迁移版本登记、首次主体不自动套用：OMS `platform_security_admin` 只管理平台人员的本产品角色及范围；`platform_config_admin` 管全局 Provider/Secret；`platform_operator` 仅获显式学校的权益/额度等动作；`platform_auditor` 仅限已授范围的脱敏只读与单独导出。敏感成本、Secret 和导出分别授权，不从普通读或角色名称暗含。TMS `school_admin` 可在本校管理本产品角色/成员/应用/服务访问与共享资源；`school_operator` 仅有授予的对象管理动作；`school_auditor` 仅有本校脱敏只读；普通成员无管理入口。实际模板动作清单由后端版本化 catalog 定义，管理员可建本应用域自定义角色，但不能超出自身显式委托上界授予动作或范围，也不能扩大 OMS 学校服务权益。

首位 TMS 管理员由**已验签真实 `subscription.created` 事件的 `actor.user_id`**一次性导入：接收服务先校验三段式 HMAC、时效、事件 ID、非 mock、目标应用与订阅、学校稳定 ID/绑定及事件顺序；仅 `actor.type=user` 且 `actor.user_id` 非空时，以本环境配置的 OIDC issuer + 该 Keycloak User ID 建立本校待激活主体与不可重复消费的引导记录。`actor` 在 EduPlus2 文档中只是可选触发者，不是其权限角色；将其指定为本产品首位管理员是用户确认的 **DeepTutor Enterprise 产品策略**，而非对外部角色语义的推断。候选本人随后通过 TMS 认证，其 `(issuer,sub,school)` 必须与事件主体及当前受控学校绑定精确匹配；Enterprise 程序在事务内重验本地学校业务状态、引导记录未消费/未撤销、是否已有历史管理员以及当前版本，才激活唯一 `school_admin` assignment 并追加脱敏审计。重复投递只回放同一结果；订阅续期、恢复或重订不得复活旧授权。`actor` 缺失、`type=system`、`user_id=null`、mock、错应用/学校或本人身份不匹配时只处理允许的生命周期部分，**不得**授予可用管理员权，并进入待人工核对状态。真实事件尚未验收前，正式首位开通写入口不装配；OMS 不提供学校账号/开通页面。

首位管理员完成后，TMS 的 `tenant.permissions.manage` 在当前学校内管理后续角色和成员授权，但授予内容不得超出本校显式委托上界。TMS 不创建 EduPlus2 账号；候选人必须先本人登录形成待授权主体。禁止自授、自批、把自定义角色权限扩过授予人的委托上界、撤销最后一名可用学校管理员。学校重绑/停用、账号停用或会话撤权即阻断写入；学校重新启用不自动恢复已撤销本产品授权。OMS 不提供任何学校账号列表、候选查询、首位管理员开通或 TMS 成员/角色/client 管理入口。

### 4. 入口—动作—范围—默认模板矩阵

以下为版本化 catalog 的最低基线；同一菜单下的敏感查询、导出和写入不得仅凭入口动作放行。模板只表示可供管理员显式授予的集合，**不自动赋予新登录主体**，服务端动作 key 与前端菜单/按钮 key 同源。

| 页面/接口或操作 | 后端动作与范围 | 可显式授予的默认模板 | 前端入口/按钮 key |
| --- | --- | --- | --- |
| OMS 工作台和学校列表 | `ops.oms.access`；学校行另需 `ops.tenants.read` + 目标 `school` | security admin、获校授权的 operator/auditor | `ops.oms.access`、`ops.tenants.read` |
| 全局 Provider 配置、Secret | `ops.providers.manage`、`ops.credentials.manage` + `platform`，读/写分权 | config admin；security admin 不因角色名称自动获 Secret | 同后端动作 key |
| 学校权益、额度、定向供给 | `ops.entitlements.manage`、`ops.quotas.manage`、`ops.supply.manage` + 目标 `school`；影响全局供给另需 `platform` | 明确获校授权的 operator | 同后端动作 key |
| 成本、审计与导出 | `ops.cost.read`、`ops.audit.read`、`ops.audit.export` 分别授予所需范围 | 单独授权的 auditor/security admin | 同后端动作 key |
| 平台人员、角色/动作、平台人员学校范围 | `ops.permissions.manage` + `platform` 启动变更；目标学校须核验，授予动作/范围另受委托上界控制；不读取学校账号 | security admin | `ops.permissions.manage` |
| 首位学校管理员待激活/本人激活 | 已验签真实 `subscription.created.actor.user_id` + 目标 `school`，本人 TMS 登录精确匹配；Enterprise 一次性引导策略 | 无默认人工作者角色；事件与本人身份同时满足才可激活 | `tenant.school.bootstrap`（仅内部引导动作，非普通菜单授权） |
| TMS 入口与学校成员 | `tenant.tms.access`、`tenant.members.read` + 会话唯一 `school` | 显式授予的 school admin/operator/auditor | 同后端动作 key |
| TMS 学校角色/成员授予 | `tenant.permissions.manage` + 当前 `school` + 显式委托上界；禁止自授及最后管理员撤销 | school admin | `tenant.permissions.manage` |
| TMS client 与应用/服务访问 | `tenant.clients.manage`、`tenant.access.manage` + 当前 `school`，并遵 OMS 服务授权上界 | school admin 或显式 operator | 同后端动作 key |
| TMS 本校额度与用量 | `tenant.quotas.read`、`tenant.usage.read` + 当前 `school`；无写动作 | school admin、显式 auditor | 同后端动作 key |
| 私有正文 | 无管理角色默认动作；owner 或该资源已有显式 grant | 无 | 不显示管理入口 |

低风险读动作仍需明确定义。迁移生成具体 catalog、默认模板关系和前后端安全 DTO；实现须对每个现有路由/菜单/按钮逐项补齐矩阵，不得把本表作为省略业务资源权限的白名单。

### 5. OMS UI 与交互

独立“平台智能体运营后台”在“审计与治理”下只设**平台人员**、**角色与动作**、**平台人员学校范围**与**授权审计**。学校范围列表只列平台人员的 OMS `ops.*` 操作范围，不列学校账号；旧“学校后台开通”入口、直达深链和 API 全部移除。平台人员列表只返回获授权的最小元数据，不提供学校用户目录或任意 `sub` 搜索；新增对象只从已完成可信 OMS 登录的平台候选中选取。详情抽屉分“身份与核验”“角色/范围”“变更历史”；平台授权/撤销及高风险操作使用独立模态框，显示差异、影响学校、失效时间、审批、原因及当前版本，确认后回读审计编号。平台范围与学校操作范围用明确标签和不同选择控件，不能把“全部学校”误作某校 grant；平台人员不能在 UI 给自己扩权，最后平台管理员操作禁用且直调 API 仍 403/409。

UI 的 `GET /api/v1/oms/me/permissions` 只返回当前可见动作、范围摘要、policy version 和有效期，不返回可复用凭据；每次真实 API 再鉴权。401 引导重新登录；403 清理旧敏感内容并显示缺少的动作/范围；409 版本冲突要求回读，不自动重试写；外部核验失败或绑定待核验显示“暂不可操作”，不渲染成无学校或零数据；撤权通知使旧页面退出受保护操作。所有状态文字来自后端 descriptor，权限前端显隐仅是可用性，不是安全边界。

### 6. TMS UI 与交互

独立“学校智能体管理后台”的“成员与权限”下设**成员**、**学校角色**、**访问关系**及**授权记录**。学校抬头固定展示已核验学校名称、code 和状态；无跨校选择器。`/tms/{schoolCode}` 的深链在服务端先核对会话学校与规范 code。成员列表可查看待授权、有效、过期、停用状态；只允许从已登录且归属本校的候选主体授予本产品角色，不能创建外部用户。角色页显示动作矩阵和生效版本；成员详情的“学校角色”“应用访问”“服务访问”“共享资源”是不同聚焦抽屉，禁止把全校服务列表冒充某成员已获授权。应用↔成员、应用↔服务从两端回读同一关系；服务必须先获 OMS 学校授权，配额与用量仍只读。私有正文始终另验 owner/grant。

首次进入时无管理员显示“学校后台待开通”，候选主体只能查看申请状态与必要联系渠道，不得查看成员或学校业务数据；已提交的待激活状态显示事件身份匹配与过期/异常信息，不展示任意人可点击的批准按钮；只有事件中同一主体本人完成真实 TMS 登录才触发服务端受控激活。前端身份切换只是原型演示，不可作为正式授权。日常授予从列表选对象→独立模态框选本校角色/动作及有效期→预览有效权限与受影响关系→填写原因→确认→回读授权记录。撤权列出会失效的菜单、应用/服务访问和在途操作；取消保留表单。角色模板变更、过期、学校停用、外部接口故障、无权、空结果分别显示。`GET /api/v1/tms/me/permissions` 仅返回本校安全动作与菜单 key；不返回 OMS `ops.*`、成本、Secret、采购或跨校 DTO。TMS 管理员也不能从角色管理页增加额度或修改 OMS 服务授权。

两端共享的权限矩阵/状态/确认等**纯展示组件**接收各自服务端安全 DTO；应用容器持有独立 API client、会话、动作目录与路由。不要在共享组件内通过 `isOms/isTms` 读取另一端权限或隐藏先返回的敏感字段。开发原型只用标明“演示”的合成候选、审批/撤权状态；生产原型路径继续 404，正式界面只接真实 API。

### 7. API、迁移和发布门禁

管理 API 按应用域分离：OMS `/api/v1/oms/me/permissions`、`/principals`（仅平台人员）、`/roles`、`/school-grants`（仅平台人员 OMS 操作范围）、`/authz-audit`；TMS `/api/v1/tms/me/permissions`、`/school-bootstrap-status`、`/members`、`/roles`、`/access-grants`、`/authz-audit`。具体方法/DTO 在实施任务细化；所有写操作都含 expected_version、幂等键、原因、actor/request ID 和审计回读，不接受任意 `subject`/`school` header 作为身份。列表分页/范围有上限，导出另授动作，目标不存在按防枚举 404。`GET /me/permissions` 不替代 API 权限。授权服务只在企业扩展装配，核心如需通用 seam 必须记录受影响入口、上游合并风险与回归测试。

新增本仓库**后续版本**的企业 PG 迁移，不改已应用的 `oms/0011_school_binding.sql`：主体、应用域、角色/动作版本、assignment/范围/有效期、版本栅栏、Webhook 初始管理员一次性引导记录、待激活状态与高风险审批、追加审计、必要 RLS/唯一/最后管理员约束及旧数据显式映射。外部数字学校 ID 的类型若与真实接口不符，以新迁移适配，不猜测回填。迁移需隔离合成数据 dry-run/apply/verify、重复运行、drift、回退；旧全局 admin/tenant_admin、EduPlus2 client registration 的 `registered_by_surface='oms'` 历史值不自动提升或删除。**不做 EduPlus2/OpenFGA/Keycloak 迁移**；真实 `subscription.created.actor` 的签名、应用/学校绑定与本人激活合同未通过前，不开放首位开通写路由。

开放顺序为身份合同与真实签名订阅事件核验 → PG 权限事实/一次性引导迁移和 TMS 本人激活 → OMS/TMS 管理 API 正负例 → 两端真实权限 UI → 双学校、撤权竞态、CLI/HTTP/WS/SDK/后台与 upstream 兼容 → 受控 test 环境联调。已有 Webhook mock demo 不重做，也不计入首位管理员身份/激活验收。真实租户数据、生产发布、提交/归档另按授权执行。

## Risks / Trade-offs

| 风险 | 缓解 |
| --- | --- |
| TMS 本地权限与外部学校成员状态漂移 | 写入前在线核验账号/学校；外部接口缺失即关闭；待授权主体不自动获权，学校停用独立阻断 |
| 学校侧开通被候选人自证或生命周期事件冒充 | 仅签名真实 `subscription.created.actor` 登记候选；本人 TMS 登录精确匹配后一次性激活；事务内唯一性；缺 actor/身份或真实事件合同即关闭写入 |
| 某校 `school` grant 被误当平台 `platform` grant | 两类 scope 不可隐式转换，动作目录显式标记，API/迁移和 UI 负例覆盖 |
| 角色模板升级造成静默扩权 | 角色版本固定于 assignment；新动作显式批准，收缩/撤权立即生效 |
| 旧 token/菜单或缓存绕过撤权 | 写事务重验并锁定版本；前端清理敏感缓存；HTTP/WS/SDK/job 同一鉴权入口 |
| 过度修改 core 影响 upstream merge | 优先企业包；仅通用 seam 经单独审阅，并验证认证、turn、session owner、audit correlation |

## Migration Plan

1. 先批准本 change 与受影响 OMS/TMS 业务、原型、正式界面提案的新权限边界；旧版批准不自动覆盖。test-cn 旧证据复用，针对未验证外部能力补脱敏记录。
2. 在隔离 PG 中新增版本化授权事实与 TMS 事件引导/本人激活迁移，验证默认零权、唯一性、RLS 兜底、撤权竞态、幂等及最后管理员保护；不修改 EduPlus2。缺少真实订阅事件的 actor/学校绑定与本人激活证据时不装配正式开通写路由。
3. 逐应用接管理 API 和前端权限 UI；旧同名管理路由在企业 app 不装配，旧角色不隐式迁移。前端灰度不放行后端缺权。
4. 受控 test 环境仅在既存外部接口与双学校 401/403/200 证据齐全后打开对应路由；回退停止新授权与写入、保留授权和审计历史，不能删除 grant 或账务事实来恢复旧版。
