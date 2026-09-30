# EduPlus2 Webhook 驱动的学校接入与生命周期

> **2026-09-27 修订稿，实施中**：用户明确要求：真实 Webhook 经 HMAC、时效、已签名应用 ID 结构及幂等校验后，其学校与订阅业务数据就是 DeepTutor 的权威来源。学校接入、暂停、恢复、到期不再调用 online resolve 二次核验，也不依赖周期性在线证明 TTL。此前批准的“通知 + online resolve”方案已被本决策取代；原实施勾选项需按新验收重评。本提案仅修改 DeepTutor，不修改 EduPlus2、Keycloak 或 OpenFGA；不自动授权发布、真实学校写入、提交或归档。

## Why

已签名的 `subscription.created` 应直接驱动稳定内部学校创建/绑定及 PG 学校数据空间初始化，其他 `subscription.*` 事件直接驱动本系统外部资格。Webhook 2xx 表示该数据库事务完整提交，不表示 AI 执行资源已就绪、用户已有权限或管理员已获权。**多学校 AI 运行时属于 B1/B2、OMS/TMS 正式业务，不得再作为本 Webhook 的实施前置。**

## What Changes

- 保留三段式 HMAC、时间窗、128 KiB 上限、事件/header 一致、已签名 body 中正整数 `app.id`、必需字段和 event ID/规范化事实冲突检查；退役静态目标应用 ID 配置，不能用未签名 header/URL 指定应用。mock 只用于 demo，不写业务。真实事件最小脱敏事实提交 PG inbox 后才返回 2xx；不保存原始 body、OAuth Secret、bearer token 或签名。
- 以事件中的稳定 `tenant.id` 与目标 `app.id` 建立唯一内部学校映射；`school_code` 仅为展示/定位信息。已验签 `subscription.created` 在同一事务初始化 PG 学校锚点、绑定、目标应用 client、投影和数据库初始化标记；失败整体回滚，由发送端重试。标记**不等于** AI 资源 `provisioning_status=ready` 或 `local_enabled=true`，也不授予 `tenant.*`/`ops.*`。
- 八类 `subscription.*` 在接收事务内按学校—应用串行投影，使用本地 generation/唯一事件 ID 防并发覆写、重复与同 ID 冲突。只有 inbox、映射和投影一并提交才返回 2xx；失败整体回滚，由发送端按 5xx 重试。资格直接来自已投影的事件状态，再与本地 enabled/ready/隔离及独立权限/额度取交集；不使用 online resolve 作为接校、开停、漏送对账或放行条件。
- `subscription.created.actor.type=user` 和 `actor.user_id` 仅作为首位 TMS 管理员候选。本人持已验签 OIDC JWT，经 `tid`、目标应用 `azp` 与 Webhook 数据库绑定后，可由 DeepTutor Enterprise 在一次事务中消费候选、激活本校管理员并写审计；Webhook 回调本身绝不直接赋权。若实际 `actor.user_id` 与 JWT `sub` 不相同则保持拒绝，须以真实脱敏联调证据确认映射。事件 `subscription.id` 保存为来源事实，不另查当前订阅 ID。**本 Webhook change 验收真实候选交接与隔离合成的激活 API 正负例；正式 TMS 尚未交付，真实本人登录/激活由管理授权及 TMS 提案验收，不作为 Webhook 接收链路的完成前置。**
- Webhook 提供学校/应用/生命周期的数据库资格判定；TMS 管理入口可在 AI 资源尚未 ready 时完成首管激活和配置，AI 新调用继续受本地 enabled/ready/隔离限制。B1/B2 负责把该资格接到各校 HTTP/WS/SDK/session/下载/任务运行时；OMS/TMS 负责正式界面与动作授权。OMS 逐服务额度独立，不生成订阅事件。必要历史/审计/管理只读按自身权限保留。

## 关联提案

`add-b1-b2-trusted-school-integration` 的学校绑定来源须改为本 Webhook 的稳定外部学校 ID，普通用户仍由 EduPlus2 OIDC/JWKS 认证；`add-enterprise-management-authorization` 的首位管理员激活须使用本地已投影生命周期，不再要求 online resolve 证明。两份依赖提案及其验收均需同步，不能以本提案替代独立权限和隔离实现。

## 风险与放行门禁

现有 Webhook **没有可比较的来源订阅版本**。若停用事件漏送，本地状态可能继续有效；若旧恢复/创建事件迟到，按接收顺序投影可能覆盖新状态。投递时间、接收时间和订阅 ID 都不能证明外部最终状态。新方案必须明确接受该残余风险，提供投递失败/积压告警、人工冻结与受控恢复；不能宣称漏送自动纠正或当前状态强一致。若产品要求该保证，须由 EduPlus2 提供来源版本或受信快照，本仓库不能伪造。**Webhook 数据库链路完成**只证明学校映射/PG onboarding、资格投影及首管候选交接；**真实学校 AI/管理放行**仍须 B1/B2 的双校隔离/全入口门禁和管理授权/TMS 的本人激活验收。不能把 204 或外部“已订阅”当作完整接入证据。
