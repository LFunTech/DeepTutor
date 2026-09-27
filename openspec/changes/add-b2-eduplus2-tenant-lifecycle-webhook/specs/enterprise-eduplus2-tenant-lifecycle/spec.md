## Purpose

EduPlus2 提供学校及应用订阅生命周期权威；DeepTutor 企业扩展可靠接收签名通知，以受信在线状态证明决定本产品租户级准入。OMS 仅查询脱敏状态，不写开停；逐服务额度属于独立门禁。

## ADDED Requirements

### Requirement: 真实 Webhook 必须先安全持久接收再确认

系统 SHALL 验证 `timestamp.event.raw-body` HMAC、时间窗、大小和事件/header 一致；对真实事件另严格校验目标应用和学校/应用/订阅 ID 结构，仅对明确支持的真实 `subscription.*` 事件在 PG inbox 提交后返回 2xx。inbox SHALL 只保留必要脱敏投影、以独立稳定密钥计算的业务投影摘要和处理/重试状态，MUST NOT 保存或记录原始 body、OAuth client secret、bearer token、签名或 Webhook Secret。相同 event ID 与相同**规范化业务投影**幂等；同 ID 的学校/应用/订阅/状态/created actor 等关键事实不同则冲突并告警；合法重投时变化的投递时间、签名或 Secret 不构成业务冲突。2xx SHALL 只代表**可靠接收**，不代表学校已激活、对账已完成或管理员已授权。PG 不可用时 MUST 返回可重试 5xx。已验签 mock demo 只需符合既有 mock 结构，MUST NOT 写入 inbox 或改变业务状态。

#### Scenario: 已签名真实事件入队但在线状态暂不可用
- **WHEN** 真实 `subscription.created` 验签、目标校验及 inbox 提交成功，在线核验暂时超时
- **THEN** 接收器可返回 2xx 表示已持久接收，处理状态保持待重试；学校新业务准入仍被拒绝，不创建可用管理员权限

#### Scenario: 重复 ID 与冲突业务事实
- **WHEN** 已接收 event ID 再次投递相同业务事实但投递时间变化，或相同 ID 携带不同订阅/状态/created actor
- **THEN** 前者幂等确认；后者拒绝并告警，不覆盖既存事实或状态

#### Scenario: 控制台 mock 与伪造真实事件
- **WHEN** 请求是已验签且匹配 `mock_` ID 的控制台 demo，或签名无效/过期/错误应用的请求
- **THEN** demo 仅确认可达性而不写业务状态；无效请求拒绝且不入可处理队列

### Requirement: 事件是失效通知而非可排序的状态版本

系统 SHALL NOT 使用事件到达时间、投递 `timestamp`、事件 ID、online resolve 的不透明哈希或 Webhook payload 状态作为单调来源版本或直接开通资格。合法真实订阅事件 SHALL 使已绑定目标的旧允许证明失效并触发当前状态在线核验；本地 generation 仅防本系统并发旧查询覆写新通知。未知/未绑定学校 SHALL 保持待绑定和 fail closed，不能由学校码、URL 或单条 Webhook 自行推断内部学校。

#### Scenario: 较旧停用事件晚于恢复到达
- **WHEN** 旧 `subscription.suspended` 在当前学校—应用已恢复后才投递
- **THEN** 系统不按事件时间直接停用或恢复，而使旧证明失效并查询当前受信状态；查询失败时保持拒绝，不把旧 payload 当成最终状态

#### Scenario: 首校通知尚无受控绑定
- **WHEN** 目标应用正确的真实 `subscription.created` 到达，但稳定外部学校 ID 尚无已验证内部绑定
- **THEN** 最小事件事实可入待绑定队列；不得创建可用内部学校、将 `external_eligibility` 标为 allowed 或授权 TMS/OMS

### Requirement: 租户资格必须来自当前受信在线证明

系统 SHALL 以现有已验证的 client↔稳定学校 ID↔应用 ID 绑定核验 EduPlus2 online resolve；只有响应 `verified=true` 且 client、学校、应用、租户状态、订阅状态均符合合同，并且本地学校绑定仍有效时才可产生有时效的外部 `allowed` 证明。已绑定 client 的明确不活跃响应，在**无其他当前有效 client 证明**时 SHALL 使该目标不可用；未知 client 的拒绝响应不得创建绑定。失败、超时、矛盾、证明过期或学校绑定撤权时新业务准入 MUST fail closed；多个历史/当前 client 须防止旧 client 的失败覆盖当前有效证明。外部恢复 MUST NOT 覆盖本地隔离。

#### Scenario: 在线解析超时或证明过期
- **WHEN** 学校—应用的受信核验无法在有效期内完成
- **THEN** 新业务准入拒绝并安排重试/告警；不得沿用过期的 allowed、OMS 额度或旧事件状态

#### Scenario: 已绑定学校恢复但本地隔离
- **WHEN** 在线核验确认订阅当前有效，而本地恢复隔离仍存在
- **THEN** 外部资格可记录为 allowed，但新业务仍被本地隔离拒绝

### Requirement: 首位管理员 actor 仅为待核验身份事实

系统 SHALL 只从真实非 mock、已验签且目标应用正确的 `subscription.created` 中，随安全 inbox 可靠保存 `actor.type=user` 且非空的 `actor.user_id` 作为 Keycloak `sub` 的**未绑定来源事实**；仅在稳定学校绑定核验后才交付管理授权服务的待核验候选。MUST NOT 从 system/null、其他事件、重放或错误目标创建可用管理员。Webhook 接收器 SHALL NOT 授予 `tenant.*` 权限。`add-enterprise-management-authorization` 的一次性激活 SHALL 另验证该事件的订阅 ID 是当前学校—应用订阅、候选本人可信 TMS 登录的 issuer/sub/学校、已验证学校绑定与本地版本栅栏。现有 online resolve 不含当前订阅 ID，未取得可用的既存受权只读证明时 MUST 保持 `pending_verification`，不得凭 Webhook 2xx 或人工填库激活。

#### Scenario: 旧 created 在重新订阅后才送达
- **WHEN** 旧订阅的 `subscription.created.actor` 真实有效，但当前学校—应用已是另一订阅
- **THEN** 旧 actor 不得成为可用首位管理员，即使当前 online resolve 返回有效

#### Scenario: actor 缺失或系统触发
- **WHEN** 真实 created 的 actor 为 null/system
- **THEN** 生命周期通知可可靠接收并对账，但首位管理员状态保持待核验，不授予 `tenant.*`

### Requirement: 全入口租户准入与逐服务额度相互独立

系统 SHALL 对新登录、token exchange、新 HTTP/WS turn、下载授权和后台派发检查当前外部资格、本地 enabled、资源 ready 及独立策略的交集；历史会话、审计与必要管理只读按各自权限保留。外部资格未知/暂停与 OMS 单服务额度不足 SHALL 使用不同稳定错误码和后端 display descriptor。OMS 的服务授权、供给和额度不足 MUST NOT 改写外部资格、本地开停、撤销状态或既有会话，也 MUST NOT 生成订阅 lifecycle 事件。

#### Scenario: 单服务额度耗尽
- **WHEN** 学校 lifecycle 有效而图像服务额度耗尽
- **THEN** 登录、管理、历史及其他获授权服务仍可用；仅图像服务新调用返回额度错误，不产生 `subscription.suspended` 或会话撤销

#### Scenario: 额度补充但学校仍暂停
- **WHEN** OMS 补充额度而当前外部学校资格仍不可用
- **THEN** 租户级新业务继续拒绝，额度不得覆盖学校停用

### Requirement: 漏送与处理失败必须对账

系统 SHALL 对已绑定学校—应用提供持久重试、启动/周期在线复核、处理指标和可审计失败；事件丢失、worker 中断或 online resolve 故障不得使过期 allowed 长期有效。对账结果 SHALL 受本地 generation 栅栏与学校绑定版本约束，不能覆盖较新失效通知或本地隔离。

#### Scenario: 丢失停用通知
- **WHEN** 停用 Webhook 未送达，但既有 allowed 证明到期或周期核验发现当前订阅不活跃
- **THEN** 新业务准入被拒绝、资格状态和审计更新，并触发运营告警
