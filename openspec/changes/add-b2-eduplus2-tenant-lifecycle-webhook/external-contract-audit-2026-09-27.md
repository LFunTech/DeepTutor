# 真实订阅 Webhook 权威契约核对（2026-09-27）

> 本页保留重订前的只读合同与已部署 test 环境快照。用户随后已批准 DeepTutor-only 重订版，本地实现进度见 `implementation-evidence.md`；下文“尚待审阅/实施”“真实事件继续 503”描述的是核对当时及尚未更新的 test 部署，不代表当前工作区没有实现代码。

> 后续用户决策进一步将 `subscription.created` 事件所属订阅的当前性与迟到旧事件处理归 EduPlus2 侧；本页当时提出的“DeepTutor 必须另查当前订阅 ID 才能激活”已不再是现行实施门禁。文档保留当时接口能力的事实核对；现行授权规则见本 change 的 proposal/design/spec/tasks 与管理授权 change。该发送端保证尚未由本仓库真实联调证实。

本记录仅核对已发布文档、只读发送端实现和本仓库接收路径，不含真实学校 ID、OAuth 凭据、Webhook Secret、请求体或签名；未修改 EduPlus2 仓库，也未触碰 test 学校数据。本记录是旧版来源版本设计的**缺口证据**及新版任务 1.1 的输入，不是目标环境现有接口适用性或正式接收器验收。

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
