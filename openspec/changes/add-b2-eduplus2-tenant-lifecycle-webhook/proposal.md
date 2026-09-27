# EduPlus2 订阅 Webhook 接收与学校生命周期在线核验

> **2026-09-27 用户已批准按本重订版实施**：此前批准的是“单调来源版本 + 带版本快照”的事件投影方案。现有 EduPlus2 事件没有单调订阅版本，online resolve 的 `version` 是不可排序的 SHA-256；本版改为“签名事件持久接收 + 在线核验当前状态 + 保守禁用”。证据见 [外部契约核对](external-contract-audit-2026-09-27.md)。**只改 DeepTutor**，不修改、配置、迁移或部署 EduPlus2、Keycloak、OpenFGA。批准实施不等于批准发布、真实学校写入、重试或归档。

> **已完成的前置切片保留**：2026-09-26 test-cn Webhook URL 的 8 类签名 mock demo 均返回 204。mock 不写状态；已签名真实事件目前仍返回 503。2026-09-27 首校订阅在 EduPlus2 成功、Webhook 503，DeepTutor test PG 未同步学校。上述事实不构成真实事件或首位管理员验收。

> **2026-09-27 后续用户决策**：`subscription.created.subscription.id` 已在事件中提供；候选所属订阅是否仍为当前订阅由 EduPlus2 侧负责，DeepTutor 暂不独立比对当前订阅 ID。该发送端保证尚非本仓库已验证事实，不得据此声称真实联调或首位管理员激活已通过。

## Why

EduPlus2 是学校及其应用订阅生命周期权威；DeepTutor 需要可靠收到变化、核验**当前**学校—应用状态，再决定本产品租户级准入。现有撤销处理器只能设置撤销，不能处理恢复。按事件到达时间、投递时间或不可排序哈希直接更新状态，会在乱序/重订时误开通或误停用。OMS 额度耗尽不属于学校生命周期。

## What Changes

- 在 DeepTutor 企业扩展内完成独立 `POST /api/v1/eduplus2/webhooks`：三段式 HMAC、时间窗、大小/schema、目标应用和事件白名单；真实事件的**安全最小投影**与去重/冲突证据在 PG 事务提交后才 2xx。2xx 仅表示可靠接收，不表示学校已激活、对账已完成或管理员已授权；持久化失败返回可重试 5xx。原始 OAuth Secret、签名、原始 body 不入库/日志。签名 mock 继续只做投递 demo。
- 对 `subscription.created|suspended|reactivated|terminated|expired|renewed|expiring|plan_changed` 均将事件作为**失效与对账触发器**，不以其 payload 状态或时间戳直接决定当前资格。按稳定学校/应用和已验证的 client 候选调用 EduPlus2 已有 online resolve：仅 `verified=true`、当前 client/学校/应用/订阅均有效且与 DeepTutor 已验证学校绑定一致时允许；对已绑定目标的明确不活跃答复禁用；故障、过期、矛盾或未知目标保持 `unknown/pending` 并拒绝新业务准入。现有 resolve 停用时不给完整绑定，不得用其为未知学校创建绑定或把哈希当来源版本。
- PG 保存 inbox、本地处理代次、待核对/失败与最近**在线核验**结果；同一事件 ID 的规范化**业务投影**相同则幂等，不同则冲突并告警。投递时间或 OAuth Secret 在合法重试时变化，不单独构成业务冲突。按学校—应用串行对账与代次栅栏防止本地旧查询结果覆盖新触发；定时重查弥补漏送，在线证明过期即 fail closed。内部学校创建与稳定绑定归 `add-b1-b2-trusted-school-integration`／`add-enterprise-management-authorization`，Webhook 不凭学校码或签名消息自行授予学校/运营权限。
- 已验签真实 `subscription.created.actor.type=user`、非空 `actor.user_id` 可随 inbox 保存为**尚未授权的来源事实**；仅在目标应用/学校绑定核验后交付本产品管理授权服务的待核验候选。事件 `subscription.id` 用于审计、幂等和冲突检测，不作为 DeepTutor 的“当前订阅 ID”比对门禁；旧事件有效性由 EduPlus2 发送端负责。首位激活仍须核对当前学校—应用有效、候选本人 TMS 登录的 issuer/sub/学校、学校绑定版本及本地一次性栅栏，不能仅凭 Webhook 2xx 或学校成员身份赋权。OMS 不管理学校账号。
- 全入口租户级新业务准入取 `当前外部资格 ∧ 本地 enabled ∧ 资源 ready ∧ 其他独立策略`；历史和必要管理/审计路径按各自权限保留。OMS 服务授权、供给和额度只决定对应服务新调用，不改写外部资格、会话或生命周期事件。旧 `revocations` 入口保持独立，不接恢复事件。

## Capabilities

### New Capabilities

- `enterprise-eduplus2-tenant-lifecycle`：签名通知持久接收、当前状态在线核验、失联保守禁用、对账和租户级准入。

### Modified Capabilities

无；学校绑定及首位管理员授权仍由其各自已批准的 change 持有。本版通过审阅后须同步其交接文字，不能以本版代替关联提案的独立批准。

## Impact and Release Gate

只改本仓库 `extensions/enterprise/` 的 API、EduPlus2 适配、版本化 PG migration、测试与必要的**上游中立** core 准入 seam。先用隔离合成双学校验证重放、乱序、停用/恢复、client 轮换、外部故障、首位 actor 与额度隔离；再对已交付既存接口做目标环境脱敏只读 smoke。没有可信在线状态或学校绑定时可以可靠接收并待核对，但不得开放学校业务；首位管理员还须真实事件、可信本人同校登录和一次性本地授权验收，不再以 DeepTutor 独立查询当前订阅 ID 为放行条件。test 首校不得靠手工补数或仅发布现有代码宣称接入完成。真实学校数据处理、test 发布/重试、生产发布、提交、推送与归档各须按其独立授权和证据门禁执行。
