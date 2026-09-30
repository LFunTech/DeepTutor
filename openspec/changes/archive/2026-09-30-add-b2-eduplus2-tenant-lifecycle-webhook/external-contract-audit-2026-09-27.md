# 真实订阅 Webhook 权威契约核对（2026-09-27）

## 当前合同与非 mock 证据（2026-09-27 追加）

- 只读逐页核对 EduPlus2 的 [事件目录](https://eduplus-test.f123.pub/docs/webhook/event-types/)及八个 `subscription.*` 子页：共同示例均携带 `event_id`、学校 `tenant.id`/`tenant.tenant_type`、`app.id`/`app.client_id`、`subscription.id`/`subscription.status`。文档中的示例状态分别为：`created=active`、`reactivated=active`、`suspended=suspended`、`terminated=terminated`、`plan_changed=active`、`renewed=active`、`expiring=active`、`expired=expired`。这只是**公开字段合同**；目标环境实际验证了 created/terminated/suspended/reactivated，另外四类未获外部端到端证据。
- [事件目录的 actor 字段说明](https://eduplus-test.f123.pub/docs/webhook/event-types/#actor-%E5%AD%97%E6%AE%B5)明确 `actor.user_id` 是 Keycloak User ID，可为 null，`actor.type` 可区分用户操作与系统任务；这支持候选主体的身份类型选择，**不证明该主体具备学校管理员角色**，也不替代实际登录令牌 `iss/sub/tid/azp` 精确匹配。`subscription.created` 的 [字段页](https://eduplus-test.f123.pub/docs/webhook/event-types/subscription-created/)仍未把 actor 设为必填。
- [Webhook 概述](https://eduplus-test.f123.pub/docs/webhook/)明确 2xx 视为投递成功；网络故障、5xx 和 429 自动指数退避重试，其他 4xx 不重试；[签名页](https://eduplus-test.f123.pub/docs/webhook/signature-verification/)要求 `timestamp.event.raw-body` HMAC-SHA256 与时间窗。DeepTutor 因而对可重试事务故障返回 503，对无效签名/结构返回 401/422；不把 204 解释为 AI 资源或人员权限就绪。
- `rc.53`/Woodpecker #64 部署后，test-cn 入口于 21:27:50、21:28:13（北京时间）收到两次非 mock 调用，分别返回 204。PG 只读事务核对同一学校/应用的 `subscription.terminated` 为 `denied`、随后 `subscription.created` 为 `verified/active`；学校绑定 `verified`、PG onboarding 完成、目标应用 client `active`、当前投影 `allowed`。created 的订阅 ID 为正数、client 非空、`actor.type=user` 且 subject 非空，形成 **1 条 `pending_verification` 候选**。不记录实际学校 ID、订阅 ID、client、actor subject、请求体、签名或密钥。
- 前一轮 503 发生在此版本部署前。部署后的运营后台重试详情曾显示 `TenantApp` 初始化状态为 `failed` 而**跳过分发**，当时 test-cn 没有收到新真实请求；不能把该旧投递结果当成 `rc.53` 的接收失败。后续独立测试学校的真实 `subscription.suspended`/`subscription.reactivated` 均成功回调，PG 资格按 `allowed→denied→allowed` 变化，见 `implementation-evidence.md`；八类中仍有四类未获得实际投递证据，也未验证真实本人 JWT 匹配、漏送/乱序最终态。来源无单调版本/受信快照的残余风险保持不变。

> **后续用户决策再次改变权威边界**：已验签、目标应用匹配的 Webhook 业务数据直接用于学校接入和生命周期，不再用 online resolve 二次核验；本文件此前对在线方案的论证仅为历史背景。无来源版本、漏送和迟到风险并未因此消失，见最新 proposal/design/spec/tasks。

> 本页保留重订前的只读合同与已部署 test 环境快照。用户随后已批准 DeepTutor-only 重订版，本地实现进度见 `implementation-evidence.md`；下文“尚待审阅/实施”“真实事件继续 503”描述的是核对当时及尚未更新的 test 部署，不代表当前工作区没有实现代码。

> 后续用户决策进一步将 `subscription.created` 事件所属订阅的当前性与迟到旧事件处理归 EduPlus2 侧；本页当时提出的“DeepTutor 必须另查当前订阅 ID 才能激活”已不再是现行实施门禁。文档保留当时接口能力的事实核对；现行授权规则见本 change 的 proposal/design/spec/tasks 与管理授权 change。该发送端保证尚未由本仓库真实联调证实。

以下历史核对段落仅涉及已发布文档、只读发送端实现和当时的接收路径，不含真实学校 ID、OAuth 凭据、Webhook Secret、请求体或签名；当时未触碰 test 学校数据。此后用户批准在 EduPlus2 test 对指定学校执行订阅及停复，结果见本文件顶部和 `implementation-evidence.md`。全程未修改 EduPlus2 仓库。

| 所需保证 | 当前可核实事实 | 结论 |
| --- | --- | --- |
| 真实性与投递 | [Webhook 文档](https://eduplus-test.f123.pub/docs/webhook/)约定三段式 `timestamp.event.raw-body` HMAC、2xx 确认与 5xx 重试；test-cn 控制台 8/8 签名 mock 已返回 204。 | URL/签名 demo 已验证，**不证明**真实事件可以 2xx。 |
| 稳定目标与状态 | [subscription.created 字段文档](https://eduplus-test.f123.pub/docs/webhook/event-types/subscription-created/)及只读 `SubscriptionWebhookRequest` 显示学校、应用、订阅 ID 与订阅状态；`subscription.created` 还可能携带 OAuth `client_secret`，`actor` 为可选。 | 必须精确匹配目标应用、学校和订阅；原始 body/Secret 不得入库或日志，`actor` 不可直接授予角色。 |
| 单调事件版本 | 只读 `SubscriptionWebhookRequest.SubscriptionInfo` 只有 `id/status/type/statusReason/startsAt/expiresAt/subscribedAt`，没有订阅变更版本或 `updatedAt`；顶层 `timestamp` 是投递构造时的 Unix 秒，不是订阅事务版本。 | `event_id` 可去重，但不能判断两个**不同**事件的先后；不能用投递时间/到达时间替代来源版本。 |
| 在线状态与可对账版本 | 只读 `OAuthClientResolveService` 的 `version` 是客户端、应用、学校、订阅快照的 SHA-256，**不可排序**；停用时返回 `verified=false` 和原因，不提供同一学校/订阅的完整带版本快照。`/v1/app-subscriptions/check` 只返回 `allowed/subscribed/active/status`，不提供订阅 ID 或版本，且需符合调用方 JWT 限制。 | 现有接口可供部分在线准入核验，不能充当本提案的单调快照/漏送对账合同。 |
| 本系统落地 | 当前 `/api/v1/eduplus2/webhooks` 对已验签非 mock 事件固定返回 503；test PG 尚无 lifecycle inbox 或本次学校绑定。现有 `external_eligibility=not_required` 是旧固定租户状态。 | 不得把当前已启用的 EduPlus2 学校当作 DeepTutor 已接入，也不得手工补表或重试后期待自动成功。 |

## 实施门禁

此前获批的设计要求“先比较单调来源版本，再在一个事务内更新外部资格和 inbox；同版本冲突拒绝；受控快照对账”。从上述字段无法证明这个不变量。仅有 HMAC 证明**消息来自配置的发送端**，不证明**它是当前状态**；若按事件时间/到达顺序处理，旧 `suspended` 与新 `reactivated` 乱序时可能错误开通或停用。若不具备可验证的当前订阅与稳定学校/应用绑定，旧 `created.actor` 也不能可靠成为首位管理员候选事实。

因此此前的 1.1、1.2、2.1–3.2 未完成，真实事件继续返回 503；不发布“仅改版本号”的新 test 镜像，也不对首校手工补数、点击重试或声称数据库已同步。2026-09-27 已据此提出 DeepTutor-only 重订草案，尚待审阅和实施；其可靠入队 2xx 不等于学校资格或首位管理员已确认。

按原设计继续，需要由 EduPlus2 团队**交付并确认**（本仓库不能修改其代码）：

1. 对同一学校—应用订阅聚合跨暂停、恢复、到期、终止及重订可比较的单调版本；明确事件 ID、版本、时间、状态与订阅 ID 的一致性及同版本冲突语义。
2. 可由 DeepTutor 服务凭证调用的当前状态/版本快照或等效对账接口，包括停用/终止的 tombstone、稳定学校 ID、应用 ID、订阅 ID 和版本；确认权限、失败、限流和恢复时效。
3. 八类 `subscription.*` 的租户级资格映射、启用/恢复与本地隔离的交集；`subscription.created.actor` 的用户身份类型及系统/null 情况；重试、乱序、保留期和密钥轮换约定。

DeepTutor-only 重订草案选择把事件作为通知，以已验证绑定 + online resolve 当前态核验、持久重试和保守禁用代替“版本化事件投影”；但现有 resolve 在停用时缺少完整目标快照，且不返回当前订阅 ID。前者只可对**事先已绑定**的 client 保守禁用；后者使旧 created actor 的首位激活保持待核验。不能把 SHA-256、投递时间或人工学校授权当作缺失的权威版本。

核对点：本仓库 `extensions/enterprise/src/deeptutor_enterprise/api/application.py`、`eduplus2/client.py`、`eduplus2/service.py`；EduPlus2 仓库**只读** `backend/src/main/java/com/eduplus/dto/webhook/SubscriptionWebhookRequest.java`、`module/openapi/oauthclient/OAuthClientResolveService.java`、`module/registry/controller/AppSubscriptionCheckController.java`。测试与 test 数据库证据见 `implementation-evidence.md`。

## 同日补充：公开文档与真实投递的证据边界

再次只读获取官方 [`subscription.created` 文档](https://eduplus-test.f123.pub/docs/webhook/event-types/subscription-created/)：示例有 `subscription.id`、`actor.type=user` 与 `actor.user_id`，但字段说明表未声明 `actor.user_id` 必填，也未明确它与登录令牌 `sub` 的等价关系。故本系统只保存待核验候选，不能依据文档示例自动创建 TMS 管理员。`rc.50` 的真实重试在接收开关处返回 503，**尚未**产生可供核对的脱敏真实 payload 投影或在线解析/身份匹配证据；任务 1.1、2.2a 和 3.1 仍未验收。
