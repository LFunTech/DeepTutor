# EduPlus2 生命周期 Webhook 实施证据

> 2026-09-26：用户要求先完成 Webhook URL demo，再推进发送端配置；本地忽略的 `.secrets/.test-secrets` 已有 `DT_EDUPLUS2_WEBHOOK_SECRET` 与 `DT_EDUPLUS2_WEBHOOK_SECRET_REF` 键。本文件不记录值、签名、请求体或真实租户资料。

## 0.1 已完成：签名 demo 接收（非生命周期生效）

- EduPlus2 [Webhook 概述](https://eduplus-test.f123.pub/docs/webhook/) 与[签名验证](https://eduplus-test.f123.pub/docs/webhook/signature-verification/)定义 `X-EduPlus-Signature`、`X-EduPlus-Timestamp`、`X-EduPlus-Event` 和 `timestamp.event.raw-body` HMAC-SHA256；[事件目录](https://eduplus-test.f123.pub/docs/webhook/event-types/)使用 `subscription.*`。只读核对同级 EduPlus2 发送端 `DeveloperWebhookServiceImpl::sendTestEvent`：控制台 demo 用现行 DTO、`mock_` event ID、`X-EduPlus-Mock: true`，以该 Webhook 自身 secret 签名，并记录外部投递结果。没有修改发送端仓库。
- 企业组合新增 `POST /api/v1/eduplus2/webhooks` 匿名传输入口，但**业务上仍要求 HMAC**；从 `DT_EDUPLUS2_WEBHOOK_SECRET_REF`/`DT_EDUPLUS2_WEBHOOK_SECRET` 装配独立 secret，不复用旧 revocation 的两段式签名。原始 body 上限 128 KiB，校验 5 分钟时效、签名格式/常数时间比较、header/body event 一致；仅签名通过且有 mock 标记与 `mock_` ID 时返回 204。mock 不写租户资格、撤销或 inbox；未配置 secret、错误签名/时效、超限均拒绝。
- 当前真实事件即使签名有效也返回可重试 503，避免尚无权威版本/绑定/对账时错误 2xx 确认。此路径**不能作为已完成的正式 lifecycle receiver**；旧 `/api/v1/auth/eduplus2/revocations` 仍属不同契约，恢复事件不会进入它。
- TDD：新增测试先见 401（尚未公开路由），实现后签名 mock 204、伪签名/过期 401、事件不一致 422、超限 413、无 secret/真实事件 503，确认租户状态与旧撤销表不变。企业全量 `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short`：**317 passed，3 skipped**；Ruff check 与 `openspec validate add-b2-eduplus2-tenant-lifecycle-webhook --strict` 通过。

## 0.2 已完成：真实 EduPlus2 控制台 URL demo

此前仅有隔离合成数据测试，尚未部署和外部投递；以下段落按时间保留发布前的诊断与修复过程。外部 demo 必须在测试 URL 指向已部署版本后，由有权账号触发并核对每个订阅事件 2xx 与外部记录；不得把本地 ASGI 204 冒充外部 URL 已验证。

2026-09-26 后续只读核对：`.secrets/.test-secrets` 的 `DT_EDUPLUS2_WEBHOOK_SECRET_REF` 可经 `resolve_secret` 解析到同文件的非空密钥，文件权限为 `0600`。`test` K8s 的 `deeptutor-test-cn/deeptutor-backend` 仍使用既有镜像 digest，公开测试域名上的无签名 POST 仍返回 401；该部署注入的 `DT_EDUPLUS2_WEBHOOK_SECRET` 与本地测试文件**不一致**（仅比较是否相等，未输出明文或摘要）。因此当前不能把该域名交给 EduPlus2 做新接收器 demo：须先经受控测试发布把接收器版本部署到目标环境，并核对/同步该 Webhook 对应的测试 secret；不可通过直接修改共享 K8s Secret 或伪造本地 204 跳过发布与联调门禁。

用户随后明确要求先更新测试环境密钥、再走 Woodpecker 测试发布。已在 `test` 集群 `deeptutor-test-cn/deeptutor-runtime-secrets` 中仅替换 `DT_EDUPLUS2_WEBHOOK_SECRET`；回读只验证与本地值相等、其余 Secret 数据字段不变，未输出值或摘要。此操作不使运行中的旧 Pod 自动加载新密钥，也不等于外部 demo 通过。上段“不一致”是更新**前**的诊断事实。

Woodpecker 已新增仅 `tag` 事件可用的仓库 Secret `dt_test_cn_eduplus2_webhook_secret`（从本地忽略文件读取，不进入 Git）；仅 `test-cn` Secret preflight 与 deploy 两个步骤接收它，前者按环境契约检查是否存在，后者在发布前以 `sync-test-webhook-secret.py` 幂等核对/更新 K8s 运行时 Secret 的单一字段。相应的 Woodpecker preflight 元数据 Secret 也已更新。合成测试覆盖跨环境拒绝、缺失密钥拒绝、保留其他字段、无日志明文及重复运行。

2026-09-26 受控测试发布：提交 `92b69271` 与 `e13c16b9` 已推送；`deploy/test-cn/v1.4.0-rc.47` 对应 Woodpecker #58 **success**，测试命名空间后端新镜像 digest 为 `sha256:cb8e5eb10f730d010311c0362f8f37a3156c9c2fc786096482f3d04d1bf1de95`，Deployment 1/1 Ready。Secret preflight 与部署前单字段同步通过。此前 #57 在完成迁移及 rollout 后，证据扫描将预检元数据里的 Secret **字段名**误判为 `dt_token` 而失败；`e13c16b9` 用不含该字段名的脱敏权限摘要并加回归测试，#58 的最终证据扫描通过。此故障没有密钥值泄漏证据。

同日以有权账号在 EduPlus2 开发者控制台 `智能体基座`（应用 51）创建仅测试用途的 `DeepTutor test-cn` 环境，将 API Base URL 指向 `https://llm-agent-test.f123.pub`，将已存在且**保持禁用**的 `租户订阅回调` Path 调整为 `/api/v1/eduplus2/webhooks`，仅订阅 8 类 `subscription.*` 事件。控制台对该测试环境执行一次 Webhook demo，提示 **8/8 全部成功**；其调用历史有 8 条 `已投递` 记录，均为 HTTP **204**，时间 2026-09-26 18:12:27（Asia/Shanghai），耗时 8–130 ms。未启用正式 Webhook、未使用真实租户数据，也未在此保存请求体、签名或 Secret。另在公网 URL 用隔离合成数据验证签名 mock 204、伪签名 401、已签名非 mock 503。此项只完成接收 URL 的外部 mock 联调，真实事件仍 fail closed。

## 正式生命周期仍缺

发送端当前 `SubscriptionWebhookRequest` 有 `event_id`/时间戳/订阅状态，但未见可比较的单调订阅版本；此前暂拟的 `tenant.enabled|suspended|resumed` 不是现行发送事件。需与 EduPlus2 确认 `subscription.*` 对目标租户资格的映射、应用绑定、版本/乱序、权威快照与恢复时序，再新增 PG inbox/状态版本迁移、真实事件事务处理与全入口准入。无版本时不能按到达顺序猜测。mock 接收不改变 OMS 4.1 未完成状态。
