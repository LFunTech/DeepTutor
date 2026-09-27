## Purpose

EduPlus2 的已验签订阅 Webhook 是智能体基座学校接入与订阅生命周期的业务权威。DeepTutor Enterprise 不再通过 online resolve 二次核验学校接入或开停；应用内权限、资源就绪、本地隔离及逐服务额度仍各自独立。

## ADDED Requirements

### Requirement: 真实 Webhook 必须验证传输并可靠接收

系统 SHALL 验证 `timestamp.event.raw-body` HMAC、时间窗、大小、event/header 一致、事件白名单和已签名 body 中学校/应用/订阅必需 ID 结构。应用 ID SHALL 从验签后的 `app.id` 取得，不得依赖静态目标应用 ID 配置或未签名请求字段。该验证只确认投递身份/完整性，不对 Webhook 业务事实调用 online resolve 二次核验。真实事件 SHALL 在 PG inbox 持久提交后才返回 2xx；失败返回可重试 5xx。inbox SHALL 保留最小脱敏投影、独立密钥的规范化业务摘要和状态，不得保存原始 body、OAuth Secret、token、签名或 Webhook Secret。同 event ID 同业务事实幂等；同 ID 不同学校/应用/订阅/状态/created actor 拒绝并告警。mock 只用于签名 URL demo，不产生业务事实。

#### Scenario: 已签名真实事件与故障接收
- **WHEN** 目标应用的真实 `subscription.created` 验签且结构正确
- **THEN** inbox 提交后返回 2xx；若 PG 提交失败则返回 5xx，不能先确认后丢失事件

#### Scenario: 重复与冲突
- **WHEN** 同一 event ID 以不同投递时间重投相同投影，或以相同 ID 携带不同业务事实
- **THEN** 前者幂等、不重建学校或重放状态；后者冲突隔离并告警，不覆盖事实

### Requirement: 已验签 created 事件直接建立稳定学校映射

系统 SHALL 基于目标应用真实 `subscription.created.tenant.id` 自动且幂等创建/定位内部学校 ID 与唯一绑定，不再要求 online resolve、人工补库或另一个外部学校接口确认该学校事实。`school_code` 只可展示或辅助定位，不是稳定键或凭据。显式非学校类型、非法已签名应用 ID、外部 ID 与既有不同内部学校冲突时 SHALL 隔离，不能开放学校业务。学校 UUID、绑定、目标应用 client、投影及数据库 onboarding 标记 SHALL 在一个 PG 事务中初始化；失败整体回滚、发送端同事件重试，2xx 不遗留待完成的本地数据库步骤。该标记只代表数据库学校空间完成，不能代替 AI 资源 ready。AI 多学校运行时、资源配置与执行隔离由 B1/B2 和 OMS/TMS 提案负责，不是本 Webhook 的完成前置。Webhook SHALL NOT 创建可用学校账号、TMS/OMS 管理权限或绕过本地隔离。

#### Scenario: 首所学校订阅
- **WHEN** 无绑定的学校收到合法真实 `subscription.created`
- **THEN** inbox、稳定映射、目标应用 client、投影及 PG onboarding 标记同事务完成；AI 资源仍可 pending，学校管理/激活与 AI 执行分别按自身门禁决定

#### Scenario: 重投与学校码变更
- **WHEN** 相同外部学校 ID 的事件重投或携带新学校码
- **THEN** 仍定位同一内部学校，不新建第二个学校，也不因 URL/学校码改变授权范围

### Requirement: 生命周期只投影已验签事件

系统 SHALL 对八类 `subscription.*` 按同一学校—应用的本地持久接收顺序串行投影，使用本地 generation 防并发旧结果覆写新结果；订阅状态有效才记录外部 allowed，停用/终止/到期和未知或矛盾状态不得放行。新事件的 inbox、映射和投影 SHALL 在一个事务内提交后才返回 2xx；投影失败整体回滚并返回可重试 5xx，不得先确认后沿用旧允许资格。系统 SHALL NOT 用 online resolve、证明 TTL、事件 timestamp、订阅 ID 大小或哈希再决定学校当前资格。恢复 SHALL NOT 覆盖本地 enabled/隔离/资源 ready 门禁。

#### Scenario: 暂停后恢复
- **WHEN** 已接入学校依次收到已验签的暂停和恢复事件
- **THEN** 暂停事件使新业务拒绝；恢复事件按其订阅状态恢复外部资格，但本地隔离仍拒绝新业务

#### Scenario: 迟到旧事件或漏送
- **WHEN** 不同 event ID 的旧事件迟到，或停用事件根本未送达
- **THEN** 系统按已持久接收顺序处理、记录可观察冲突/积压并支持授权人工冻结；不得声称识别了外部真实最新状态或自动发现所有漏送。无来源版本/快照时，残余风险必须在验收与运营文档明确披露

### Requirement: 首位管理员 actor 仅为待核验候选

系统 SHALL 只从真实非 mock `subscription.created.actor.type=user`、非空 `actor.user_id` 保留未授权候选；system/null/其他事件不产生候选。学校稳定映射后，候选本人 SHALL 以已验签 OIDC Bearer JWT 的 `iss/sub/tid/azp`、目标应用 active client、Webhook 投影/PG onboarding、学校 binding_version 和本地一次性引导事务匹配，方可激活 DeepTutor 自有本校 `school_admin`，并在同一事务中写主体、assignment、候选终态、bootstrap 状态及审计。AI 资源尚 pending 不得阻止 TMS 首管激活，但不得因此开放 AI 新调用。若真实 `actor.user_id` 与 JWT `sub` 未能匹配，SHALL 拒绝而不是猜测映射。Webhook 本身不得赋权；`subscription.id` 仅保留为来源事实，不另查当前订阅 ID。引导已消费/撤销或绑定变化不得因迟到/重复事件复活候选权限。

TMS 的应用 ID SHALL 从已验签 JWT `azp` 对应的本校 active client 登记和同一学校—应用 Webhook 投影确定，不能从静态全局配置或请求参数取得。一个应用的停用 SHALL NOT 覆盖另一应用的有效 TMS 管理资格；仍须对目标应用独立检查其投影、人工冻结及本地权限。

#### Scenario: system 或已完成引导
- **WHEN** created actor 为 system/null，或学校已完成首位管理员引导后又收到 created
- **THEN** 学校生命周期可处理，但不得新增可用管理员授权

#### Scenario: 同校不同应用
- **WHEN** 同一学校的应用 A 已订阅且 JWT `azp` 匹配 A 的 active client，而应用 B 的事件停用
- **THEN** TMS 只按 A 的投影与本地权限判断；B 不得把 A 的资格覆盖，也不得用 B 的 actor 候选激活 A 的管理员

### Requirement: 全入口租户准入与逐服务额度相互独立

系统 SHALL 提供可由正式入口消费的学校—目标应用 Webhook 投影、PG onboarding、binding_version 与本地人工冻结数据库资格；TMS 管理/首管激活入口不应被 AI `local_enabled/provisioning_status` 阻断，但必须检查生命周期、人工冻结和独立应用权限。各校新登录、token exchange、HTTP/WS 新 turn、下载授权和后台派发叠加本地 enabled、资源 ready、执行者隔离等门禁的**正式多学校运行时装配**归 B1/B2；OMS/TMS 正式界面和逐动作授权归各自提案。历史、审计、必要管理只读按各自权限保留。OMS 单服务额度不足只拒绝相应服务新调用，不改写学校生命周期、不生成订阅事件、不注销会话；生命周期拒绝与额度不足使用不同稳定业务码及后端 display descriptor。

#### Scenario: 单服务额度不足但学校有效
- **WHEN** 学校处于已投影有效状态且图像服务额度耗尽
- **THEN** 登录、管理、历史和其他获授权服务继续可用，仅图像服务新调用返回额度错误

### Requirement: 持久投影与运营风险必须可观察

系统 SHALL 保证 inbox 与投影原子提交、事务失败由发送端按 5xx 重试、重投幂等并按学校—应用串行处理并提供脱敏积压/失败/冲突指标及告警；保留/清理策略不得破坏 event ID 幂等与 actor 终态。不得以周期 online resolve 覆盖 Webhook 事实。系统 SHALL 提供经 DeepTutor 自有 `ops.reconciliation.manage` 与目标学校权限控制、版本化命令及审计的人工冻结/诊断/解除服务；后续 Webhook 不得清除本地冻结，解除本地冻结不得把外部 denied 变成 allowed。正式 OMS UI/身份适配器由管理授权/OMS 提案装配。无来源版本/快照时无法保证漏送或迟到事件后的外部最新状态。inbox、actor 终态和命令幂等事实默认不自动删除，容量阈值只告警，不直接清空。

#### Scenario: 投影事务中断后重试
- **WHEN** inbox 写入后投影事务中断或数据库不可用
- **THEN** 不得返回 2xx；本地事务回滚，发送端重试后可幂等完成投影，不得出现已确认但仍沿用旧 allowed 的窗口
