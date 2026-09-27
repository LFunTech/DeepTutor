# 设计：签名 Webhook 权威与本地学校生命周期投影

## 决策及不可提供的保证

用户明确选择**已验签 Webhook 作为学校接入和订阅生命周期的唯一业务权威**。HMAC/时效/目标应用/schema/幂等是传输真实性及完整性门禁，不是调用其他接口复核业务事实。online resolve 可在其他 OAuth 用途继续存在，但不得决定学校创建、订阅开停或生命周期放行；不再维持“在线证明 TTL”或周期性 resolve 对账。

EduPlus2 现有事件没有可比较的来源版本。实现采用**本系统同一学校—应用持久接收顺序，最后一个不同 event ID 的已接受事件为本地状态**。这不是外部真实时间顺序。重复 event ID 不改变状态；同 ID 不同规范化业务事实冲突拒绝并告警。迟到旧事件仍可能改变状态，漏送事件不会被本系统自动发现。不能把接收顺序、`timestamp` 或订阅 ID 描述成来源版本；必须在运营界面/告警和验收中披露此限制。

## 入口与事务

1. 接收原始 body 上限 128 KiB；按 `timestamp.event.raw-body` 对当前/轮换窗口上一 Webhook Secret 做常数时间 HMAC 比较，并检查 5 分钟时间窗、event/header 一致、事件白名单和已签名 body 中的正整数学校/应用/订阅 ID。`app.id` 由验签后的 body 取得，不配置静态目标应用 ID，不接受未签名 header/URL 指定应用。明确 mock 标记与 `mock_` event ID 只确认 URL，不写业务。
2. 真实事件仅提取学校/应用/订阅稳定 ID、订阅状态、必要 client ID、`created.actor` 最小身份事实及 event ID；独立稳定 inbox 密钥生成规范化摘要。不落原始 body、OAuth Secret、签名和 token。
3. 同一学校—应用使用 PG 事务锁串行接收，在一个事务内插入 inbox、自动绑定、分配本地 generation 并完成投影；`created` 同时初始化以学校 UUID 分区的 PG 事实空间、目标应用 client 和数据库 onboarding 标记。整体提交后返回 204；任一步失败整体回滚并返回 5xx，由发送端重试。不存在已 2xx 但本地投影/PG 初始化未完成的窗口。未绑定学校的非 created 事件保留脱敏 inbox 并以 denied/`school_not_bound` 终结，不能 2xx 后留下永不处理的 pending，也不据此建校。

## 学校映射和投影

- 只从目标应用的真实 `subscription.created` 建立学校：用 `tenant.id` 唯一、幂等地创建/定位内部 UUID 与绑定；`tenant.code` 不是键或授权凭据。显式非学校类型不接入学校业务；缺省类型依现有事件合同处理并记录脱敏诊断。已有同一外部 ID 指向不同内部学校或同一内部学校指向不同外部 ID 时冲突隔离，不能自动重绑。旧固定租户 `not_required` 不因外部事件隐式迁移或合并。
- 本提案的**资源初始化仅指数据库学校事实空间**：学校 UUID 锚点、稳定绑定、目标应用 client、生命周期投影及 onboarding 标记。它们在一个事务内幂等完成，失败用同一 event ID 重试；标记只证明 PG 初始化完成。AI 模型、存储、KB 等执行资源及其 `provisioning_status/local_enabled` 由 B1/B2 与 OMS/TMS 正式业务配置，不由 Webhook 虚假置为 ready。Webhook 不创建学校用户、TMS 管理员或 OMS 人员。
- 接收事务按本地 generation 串行投影。订阅状态 `active/subscribed` 可形成外部 allowed；`suspended/terminated/expired` 等非有效状态形成 denied；未知、相互矛盾或未支持值保持 unknown/denied，不能猜成 allowed。`expiring/plan_changed` 仅用事件携带的订阅状态，不从事件名猜开停。跨订阅 ID 的事件仍按本地持久接收顺序处理，不能假设 ID 大小代表新旧。
- 入口分层：学校**管理/激活入口**读取 `Webhook 当前投影 ∧ PG onboarding 完成 ∧ 绑定版本 ∧ 未人工冻结 ∧ 本地 recovery normal ∧ DeepTutor 应用权限`，不要求 AI 执行资源 ready；**AI 新调用**另叠加 `local_enabled ∧ provisioning_status=ready`、执行者/资源与逐服务额度门禁。B1/B2 接入各校多学校运行时，OMS/TMS 装配正式管理入口。`webhook_school_controls` 的版本化冻结独立于订阅投影，后续 Webhook 不能清除。冻结/诊断/解除由 Enterprise 程序按 `ops.reconciliation.manage`、目标学校、expected_version、command ID 和审计判定；解除只撤本地额外门禁，不能把 Webhook denied 变成 allowed。投影失败整体回滚并由发送端重试。无 online resolve、无证明过期自动拒绝；未收到停用事件时本地仍可能 allowed，这是明确接受的漏送风险。

## Actor 与权限

仅已验签 `subscription.created.actor.type=user` 且非空 `actor.user_id` 形成待核验候选；system/null 或其他事件不形成候选。TMS 引导 HTTP 入口仅接受 Bearer JWT，由 OIDC/JWKS 验签后将 `iss/sub/tid/azp` 与同学校、目标应用的 Webhook PG 投影及 active client 绑定；请求体、URL 或 JWT 角色不构造学校/动作权限。本人候选与当前学校资格、binding_version、一次性 bootstrap 状态、主体、`school_admin` assignment、候选终态和审计在**同一写事务**中核对/提交。AI 资源 pending 不妨碍 TMS 首管激活。真实 `actor.user_id` 与 JWT `sub` 的等价关系尚须脱敏 test 证据；不相等即保持拒绝。Webhook 2xx、actor 字段本身或普通成员身份均不授予 `tenant.*`。OMS `ops.*` 与 TMS `tenant.*` 仍由 DeepTutor Enterprise 应用层控制。

TMS 的目标应用 ID 来自与 JWT `azp` 精确匹配的本校 active client 登记，再与同一学校—应用的已验签 Webhook 投影核对；另一应用的停用不能覆盖该目标应用的管理资格，学校级兼容字段不得取代应用级投影。OMS 生命周期诊断/冻结由受信操作者身份携带目标应用 ID，并复核本校投影及 `ops.reconciliation.manage`。固定租户旧会话不携带应用身份时，只允许唯一学校—应用投影且其资格有效；出现多个应用时失败关闭，不任意选择一个。发布时先部署不再读取静态 ID 的后端，成功 rollout 后才从 test-cn 运行时 Secret 删除旧键。

## 运营、迁移及验证

新增不可变 DeepTutor PG 迁移，保留 0005–0007 历史 inbox/候选事实，新增学校映射与事件 generation/投影状态，不原位修改已应用迁移。旧 resolve 证明不得继续作为接校/开停依据；已有 `not_required` 固定租户保守保留。保留 Secret 独立性、重复 apply/verify、RLS/应用访问审计。

监测签名拒绝、同 ID 冲突、投影事务失败/发送端重试、缺少近期订阅投递及人工冻结；聚合快照不输出学校/事件 ID，错误不记录敏感载荷。静默学校阈值只用于告警，不自动改资格。inbox/event ID、actor 终态和控制命令默认长期保留、不自动删除；容量达到阈值先告警，冷归档须另设计等效幂等索引，不得直接清空事实。因为缺少来源版本/快照，监控仅能发现**可观察到的**故障，不能证明没有漏送或乱序。当前人工冻结/诊断/解除为 Enterprise 内部授权服务，正式 OMS 身份适配器与 UI 归管理授权/OMS change；不让 OMS 直接冒充 EduPlus2 生命周期权威。

隔离合成双学校测试覆盖重复、乱序、重订、跨应用、同外部 ID 竞争、学校码变化、失败重试、PG onboarding、actor、管理入口与单服务额度；目标 test 实际联调须分别证明 204/inbox、学校自动映射/PG 初始化、停复用与本人一次性激活。AI 资源 ready、各校会话/HTTP/WS/下载/后台、短 TTL URL 及额度调用属于 B1/B2/OMS/TMS 的正式集成验收，不能反向阻断本 Webhook 的数据库链路，也不能凭 Webhook 本地测试宣称它们完成。只读核对真实证据，不手工补学校/订阅行。不修改 EduPlus2/Keycloak/OpenFGA。上游中立 seam 须审查认证、会话 owner 与审计关联。
