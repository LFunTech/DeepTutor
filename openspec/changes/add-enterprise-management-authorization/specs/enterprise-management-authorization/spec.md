## Purpose

规定智能体基座 OMS/TMS 双应用域的本产品权限、TMS 学校侧首位管理员受控开通、正式管理 UI 与全入口撤权。本文是完整实施目标；局部 PG 底座已有合成验证，不表示正式 API、外部身份/学校合同或正式 UI 已交付。

## ADDED Requirements

### Requirement: 外部身份与本产品权限必须分离

系统 SHALL 使用 EduPlus2 **已交付且适用**的 OIDC/稳定主体及学校身份合同进行认证与身份识别；EduPlus2 的角色、权限 API 或 JWT 角色 SHALL NOT 决定本产品 OMS `ops.*` 与 TMS `tenant.*` 操作。DeepTutor Enterprise 程序 SHALL 是唯一应用授权决策与写入控制点，PG 只版本化保存其主体、角色、assignment、委托、审批及审计事实；PG 用户/角色/GRANT 或 RLS 可见性 MUST NOT 代替程序逐动作鉴权，RLS/约束仅作隔离与完整性兜底。两个应用域 SHALL 有独立会话、权限目录与 API client，首次登录默认零权；`eit=adm`、学校码、请求 header、Webhook secret、普通租户换票和原型 fixture MUST NOT 授权管理操作。身份有效性或学校身份绑定不可核实时，敏感写入 MUST 失败关闭；学校 lifecycle Webhook 只影响业务状态，不授予人员权限。本 change MUST NOT 修改 EduPlus2、Keycloak 或 OpenFGA。

#### Scenario: 有效外部 token 但无本产品授权
- **WHEN** 已验证的 EduPlus2 主体首次进入 OMS 或 TMS，企业 PG 没有有效应用授权
- **THEN** 只进入无权/待授权状态，不获得管理员菜单、学校数据或写 API

#### Scenario: test-cn Webhook demo 已成功
- **WHEN** 测试环境已有签名 Webhook 的 8/8 mock 204 记录
- **THEN** 该记录只作为 Webhook demo 证据复用，不代替 OMS/TMS 登录、学校核验、授权或真实事件验收

### Requirement: 管理候选发现不得绕过本人身份与数据访问边界

OMS SHALL 只从可信 OMS 登录登记的待授权平台主体或单独核实的平台人员合同中发现平台候选，不得使用学校用户目录或 Webhook/M2M 凭据查询学校账号。TMS 可在已验证的第三方应用授权码用户令牌、应用凭证、当前学校订阅、数据策略及服务端学校范围同时成立时，分页搜索可见的已有学校账号；不能把通用 `client_credentials` 令牌、学校管理后台 token 或 `/api/v1/me/profile` 用作他人目录。目录搜索结果 SHALL 仅供辨认，授予本产品权限前 MUST 匹配候选本人已登录登记的 `(issuer,sub,school)` 与可信外部学校绑定；用户名、姓名、EduPlus2 `user_id`、主数据记录、URL 学校码及目录结果单独均不能赋权。未登录候选仅显示本人登录指引，不创建待激活授权；无目录授权、策略空范围、空结果、过期令牌及外部故障必须有可区分状态，不能伪称学校没有用户。

#### Scenario: Webhook 客户端换得机器令牌
- **WHEN** TMS 使用 Webhook 下发的 Client 凭据换得 `client_credentials` token，尝试以此搜索学校用户并授予角色
- **THEN** 本产品拒绝把该 token 或查询结果当作候选授权依据；须先完成适用的第三方应用授权码用户令牌与目录范围核验

#### Scenario: 可见用户尚未本人登录
- **WHEN** 有权限的学校管理员在目录搜索中找到某账号，但本产品没有该账号在当前学校的可信登录登记
- **THEN** 只显示受策略允许的最小辨认信息及本人登录指引，不创建角色 assignment 或首位管理员资格

### Requirement: 权限决策必须按应用、动作、范围和版本执行

企业 PG SHALL 版本化存储外部主体 `(issuer,sub)`、应用域、默认/自定义角色、动作、显式 `platform`/`school` 范围、有效期、撤权版本和追加审计。DeepTutor Enterprise 授权服务 SHALL 在所有启用入口按这些事实逐动作、对象与范围判定，未调用该服务的业务路径 MUST NOT 写入管理数据；数据库连接角色或 RLS 放行不构成操作者许可。OMS 动作只能以 `ops.*` 在 OMS 域判定；TMS 动作只能以 `tenant.*` 在会话唯一学校判定。`platform` 不得从任一学校授权推导；全局配置/Secret/未定向供给须 `platform` 范围，学校权益/额度及定向供给须目标 `school` 范围，同时影响两类范围时均须具备。写事务还须由程序锁定复核主体、权限、绑定及业务版本；撤权提交后旧会话、缓存或在途请求不得继续写入。

#### Scenario: 学校授权冒充平台授权
- **WHEN** 某 operator 只有学校 A 的 `ops.supply.manage`，请求修改全局 Provider 或未定向供给
- **THEN** API 返回 403，不写入、不泄露其他学校或 Secret

#### Scenario: 撤权与在途写入竞态
- **WHEN** 学校授权撤销与旧会话中的额度写入并发
- **THEN** 两者按相同锁序串行；撤权提交后的写请求不能使用旧版本成功

### Requirement: 角色与默认授权不得产生隐式扩权

默认角色模板 SHALL 通过本仓库版本化迁移登记；角色名称、外部身份类型或旧 `admin/tenant_admin` MUST NOT 自动授予角色。自定义角色仅能包含同一应用域已登记动作，授予人不得超出自身显式、版本化的可委托动作与范围上界，委托能力不得自动成为业务执行权限。扩展角色模板动作须对受影响 assignment 显式确认新版本，收缩/撤权须立即生效；禁止自授、自批和无恢复路径地撤销最后一名可用平台/学校管理员。敏感成本、Secret、导出与 TMS 学校侧首位管理员开通各用独立动作；OMS MUST NOT 拥有开通学校管理员的动作。零活跃 OMS 平台安全管理员环境 MAY 通过单独配置门禁执行一次性首位 OMS 管理员初始化；该初始化 MUST 只接受已验签 OMS 平台会话本人，Cookie 写请求 MUST 校验 Origin/CSRF，程序 MUST 在事务内串行确认仍无其他活跃 `platform_security_admin` 后创建/激活当前主体并授予版本化 `platform_security_admin`/`platform_config_admin`，同主体重复请求 MUST 幂等，第二主体或非零管理员 MUST 失败。高风险平台授权及委托上界扩展 SHALL 由两名不同且当前有相应治理/委托资格的平台主体审批，被授权主体不得参与自身审批；批准时重验外部状态与当前版本。

#### Scenario: 新模板版本增加高风险动作
- **WHEN** 平台模板新增 `ops.credentials.manage`，既有 operator 未被重新批准
- **THEN** 其旧 assignment 不获得 Secret 管理权限

#### Scenario: 零管理员环境初始化首位 OMS 管理员
- **WHEN** 已验签 OMS 平台主体在本产品没有任何活跃 `platform_security_admin` 时显式调用首位管理员初始化
- **THEN** 系统只为该主体创建本地平台安全/配置管理员事实并追加审计；之后第二主体再调用返回冲突，且该过程不读取或采信 EduPlus2 权限角色

#### Scenario: 自定义角色越界
- **WHEN** TMS 学校管理员在自定义角色中填写 `ops.quotas.manage` 或另一学校 ID
- **THEN** 服务端拒绝该角色/授权，不能靠前端字段过滤实现隔离

### Requirement: 首位 TMS 管理员仅可由真实订阅事件 actor 一次性引导并本人激活

TMS SHALL 仅在身份绑定有效、学校业务状态可用且该校尚无历史首位引导记录时执行一次性管理员开通；OMS MUST NOT 列出、选择、创建或审批任何学校账号。系统 MUST 只从目标应用、学校绑定、订阅 ID 结构、签名、时效和事件 ID 均核验通过的**真实非 mock** `subscription.created` 提取 `actor.type=user` 的非空 `actor.user_id`，以配置的 issuer 与 Keycloak User ID 登记待激活本校管理员身份。事件 `subscription.id` MUST 用于审计、幂等和冲突检查；本阶段不要求 DeepTutor 另查当前订阅 ID 作为登录或首位激活条件，事件当前性及迟到旧事件处理按用户决策由 EduPlus2 负责。此身份指定是 **DeepTutor Enterprise 的产品授权规则**，不是 EduPlus2 外部权限判定；EduPlus2 的管理员角色、`eit=adm`、学校码、Webhook mock 或前端选择 MUST NOT 授权。候选本人完成 TMS 登录并精确匹配 `(issuer,sub,school)` 后，Enterprise 程序在同一事务重验当前学校—应用有效、事件栅栏、学校绑定/状态和版本，幂等激活唯一 `school_admin` assignment 与脱敏审计。`actor` 缺失/system/null、身份不匹配、重复事件或恢复/重订 MUST NOT 绕过一次性栅栏产生新可用管理员；不允许通过无管理员现状重播已消费或已撤销的历史引导复活权限。真实事件与本人激活尚未验收时开通写入口 MUST 保持关闭；后续学校角色只由本校 TMS 管理。

#### Scenario: 重放或非 actor 本人尝试激活
- **WHEN** 重复/恢复订阅事件到达，或与事件 `actor.user_id` 不同的主体登录 TMS
- **THEN** 服务端拒绝新授权；既有审计和已撤销的管理员权限不复活

#### Scenario: 事件缺少可用 actor 或学校在激活前失效
- **WHEN** 事件 `actor` 缺失/system/null，或学校绑定撤销/lifecycle 暂停后候选人尝试激活
- **THEN** 不创建可用管理员授权，进入待核对或失败状态并保留脱敏审计

### Requirement: TMS 日常授权只管理可信当前学校

TMS SHALL 仅允许学校管理员凭本校 `tenant.permissions.manage` 管理已本人登录且经核验归属当前学校的主体、TMS 角色、应用/服务访问和可授权共享资源；不得创建 EduPlus2 用户、切换学校、修改 OMS 服务授权/供给/额度或读取他人的私有正文。服务访问 grant 必须从属于 OMS 当前学校服务授权，且不含额度数量。资源内容读取仍需 owner/已支持的显式 grant。学校管理员不得自授，也不得授予超过自身委托上界的动作或范围，也不得撤销最后一名可用管理员。

#### Scenario: 路由学校码被篡改
- **WHEN** 学校 A 管理员请求 `/tms/{schoolCode}` 指向学校 B，或在 body/header 伪造 B 的学校 ID
- **THEN** 路由与 API 均拒绝，不返回 B 的品牌私有上下文、成员或资源

#### Scenario: TMS 尝试扩大额度
- **WHEN** 学校管理员从 UI 或直调 API 修改学校服务授权、赠送/充值额度或应用额度上限
- **THEN** 服务端拒绝，TMS 仍只读本校额度和真实消耗

### Requirement: OMS 授权管理 UI 必须与 API 同权限

独立 OMS SHALL 仅提供平台人员、OMS 角色与动作、平台人员学校操作范围及授权审计的列表→聚焦详情→独立操作模态框。`school` 范围只限制平台人员对目标学校的 `ops.*` 操作，不是学校账号或 `tenant.*` 授权。OMS MUST NOT 提供学校账号候选、首位管理员开通、学校角色或成员维护入口/API；旧深链须失效。页面 SHALL 展示平台主体/目标学校核验、动作与 `platform`/`school` 范围、有效期、角色版本、权限差异、原因、审批人、撤权影响和审计编号。仅从已可信 OMS 登录的平台待授权主体中选择候选，不提供任意外部 ID 自填赋权；高风险变更须复核。前端按服务端权限摘要显示入口，但后端对查询、写入和导出逐次执行相同或更严格的授权；无权/外部故障/版本冲突/待审批不得渲染为成功或空数据。

#### Scenario: 旧页面撤权后提交
- **WHEN** 平台人员仍打开旧授权模态框，但其 `ops.permissions.manage` 或目标学校范围已被撤销
- **THEN** 写 API 拒绝，界面清理敏感缓存、显示权限变化并提供安全回读，不自动重放写入

### Requirement: TMS 权限 UI 必须呈现学校内关系而非平台能力

独立 TMS SHALL 在“成员与权限”提供成员、学校角色、访问关系和授权记录，并在首位管理员建立前提供真实订阅 actor 引导与本人登录匹配状态；固定展示可信当前学校，无跨校选择器。成员详情 SHALL 区分学校角色、应用访问、服务访问、共享资源；应用↔成员、应用↔服务两端回读同一授权事实，不把全校服务列表冒充个人已授权关系。首次开通前仅显示待事件/待本人匹配/待核对进度，不泄露学校业务数据；页面不得提供人工自批。角色授予/撤销显示有效权限、影响和原因，提交后回读审计。TMS 服务端 DTO 与前端 MUST NOT 包含 OMS `ops.*`、Secret、成本、供给采购或跨校数据；配额/用量只读。

#### Scenario: 首位管理员仍待本人匹配
- **WHEN** 待授权候选人进入该校 TMS
- **THEN** 页面只展示开通状态与必要联系渠道，不能进入成员列表或自行批准

### Requirement: 管理授权必须可审计、可迁移和可验证

DeepTutor SHALL 以本仓库后续版本 PG 迁移建立权限事实、范围、一次性 Webhook actor 引导/本人激活、高风险审批、撤权及审计表，不修改已应用 `oms/0011_school_binding.sql`，不从旧 `admin/tenant_admin` 或历史 `registered_by_surface='oms'` 自动回填平台权限。迁移须支持隔离合成数据 dry-run/apply/verify、幂等、drift、RLS 兜底与回退。写入需 expected_version、幂等键和原因，审计记录 actor、应用、动作、目标、前后版本、审批、request ID、结果而不记录 token/Secret/私有正文。正式开放前 SHALL 验证无权 403、默认管理员和自定义角色正例、双学校/伪造 header、身份失效、真实事件 actor 引导/本人激活、最后管理员及撤权竞态，并检查 CLI、HTTP/WS、SDK、后台、session owner、audit correlation 与当前 upstream 兼容性；缺真实事件/身份合同的入口保持关闭。

#### Scenario: 旧管理员数据迁移
- **WHEN** 迁移扫描到旧本地 `admin` 或 EduPlus2 `eit=adm` 用户
- **THEN** 不自动生成 OMS/TMS 角色；报告待受控登记对象和校验原因
