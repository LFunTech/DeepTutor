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

## 2026-09-27 test 应用提审前只读核对

- 在 EduPlus2 test 开发者控制台核对 `智能体基座` 应用 51：状态仍为**草稿**；点击“提交审核”只打开前置检查，显示 **8/12 通过**、确认提交禁用。缺少至少一个**已启用应用入口**，Webhook 配置、HTTPS、事件订阅三项因既有 `租户订阅回调` **已禁用**而未通过。应用入口列表当前为空；开发者明确要求将来分别登记 OMS 与 TMS 两个入口。本轮未创建入口、未启用 Webhook、未提交申请或执行运营审批。
- 唯一配置环境 `DeepTutor test-cn` 的 Base URL 为 `https://llm-agent-test.f123.pub`，环境状态“配置中”、尚无最后验证时间。对该公开 Base URL 做无凭据只读 HTTP 核对：`/tms`、`/oms` 与 `/tms/demo-school` 均为 **404**；`GET /api/v1/eduplus2/webhooks` 为 **405**（该接收器仅支持 POST）。不能将当前不存在的管理路由登记为可用 handoff 入口，也不能为通过提审而启用真实事件仍返回 503 的 Webhook。先交付真实入口/回调和正式事件处理，再配置两入口及激活 Webhook，复核 12/12 后提交并由有权运营人员独立审批。

## 2026-09-27 两条入口草稿登记

- 用户明确接受当前 `/oms`、`/tms` 的 404，要求先登记入口并申请审批；这只豁免入口路由的当前可用性，不代表真实 Webhook 503 已解决。
- EduPlus2 test 应用 51 已登记两条 **草稿** PC 网页入口：`oms`，名称“平台智能体运营后台”，路径 `/oms`，适配“管理人员”；`tms`，名称“学校智能体管理后台”，路径 `/tms`，适配“教职工、管理人员”。两条描述均声明实际权限由智能体基座校验，未把入口身份类型当作授权凭据。
- 控制台确认“启用后入口将立即对用户可见”。在用户进一步确认启用与当前 503 风险前，入口仍为草稿，现有 Webhook 仍禁用，应用尚未提交或审批；不能把登记草稿写成正式 handoff 可用。

## 2026-09-27 test 应用已提交审核（非获批）

- 用户在获知入口立即可见及真实事件 503 风险后明确要求继续至成功提交审核。回读控制台时，两条入口 `oms`/`tms` 均显示“已启用”；没有把该状态解释为目标路由已可用。
- 首次尝试启用 `租户订阅回调` 被控制台拒绝：最后一次 8/8 成功 demo 记录为 `staging`，首次启用必须先在 `production` 环境测试或完成 MQ 预检。为满足 **EduPlus2 测试控制台内部**的审核前置条件，另建“DeepTutor test-cn 提审槽位”（环境类型“生产环境”），描述明确写明实际指向现有 test-cn、非真实生产发布；其 Base URL、API Base URL、OAuth 回调均复用现有 test-cn 测试配置。该槽位没有部署新服务，也不构成生产验收。
- 在上述槽位对 `https://llm-agent-test.f123.pub/api/v1/eduplus2/webhooks` 再次执行控制台签名 mock demo，显示 **8/8 个事件全部成功**。随后启用既有 Webhook，控制台状态为“活跃”；该验证只覆盖 mock，真实事件仍按当前代码返回可重试 503。控制台提示首次启用后此 Webhook 不能删除；可停止，但不应把启用等同生命周期业务完成。
- 应用“提交审核前检查”显示 **12/12 通过**。直接提交应用时，控制台要求先创建草稿版本。创建 `v0.1.0`，发布说明明确披露 `/oms`/`/tms` 当前 404、真实事件当前 503、审核槽位非真实生产，然后从该版本执行“提交审核”。控制台显示**“提交审核成功”**，版本状态为**“待审核”**（创建时间 2026-09-27 14:25:16，控制台当地时间）；尚未由运营后台审批或发布，应用页顶部仍显示“草稿”。

## 2026-09-27 首校订阅后的只读数据库核对

- 随后的 EduPlus2 test 运营页面显示应用“已通过”，一所学校授权状态“已启用”。授权操作结果为**部分成功**：订阅创建/恢复、OAuth Client、两条入口权限初始化、生命周期事件发布到 RabbitMQ 成功，但 Webhook 回调收到 **HTTP 503 `Lifecycle receiver unavailable`**。此处不记录学校名、外部 ID、OAuth Client ID、请求体或签名，也未点击“重试 Webhook”。
- 对 `deeptutor-test-cn/deeptutor-backend` 所连 PostgreSQL 使用迁移 DSN 开启 **`BEGIN READ ONLY`** 核对；该角色是所查三张表的 owner，RLS 虽启用但未 `FORCE`，因此这些计数不是缺少 tenant GUC 所致的空结果。`enterprise.tenants` 只有 1 行，`external_eligibility=not_required`、`external_tid IS NULL`；`eduplus2.external_client_registrations` 只有 1 行，来源 `env_allowlist`，创建于此次订阅之前。本次订阅时间之后新建/更新的 registration 为 **0**，`eduplus2.audit_events` 为 **0**。全库无名称含 `webhook`、`subscription`、`inbox`、`school` 的业务表；已部署 `eduplus2` schema history 仅至 `0004_audit_export_jobs`。这不是已同步首校的数据库证据。
- 已部署后端仍为 test-cn runtime digest `sha256:cb8e5eb10f730d010311c0362f8f37a3156c9c2fc786096482f3d04d1bf1de95`，Deployment **1/1 Ready**。现行接收代码只对验签的 mock 返回 204，真实事件明确返回 503，因此 DeepTutor 数据库保持不变是当前 fail-closed 设计的预期结果，**但不满足“订阅学校已在本系统完成接入”的业务目标**。禁止手工补学校/订阅行或将外部“已启用”当作本系统可用。

## 2026-09-27 权威版本与快照门禁复核

已把官方字段、发送端只读实现、本系统 online resolve 与 test PG 证据逐项整理在[外部契约核对](external-contract-audit-2026-09-27.md)。事件无单调订阅版本；online resolve 返回不可排序的快照哈希，停用响应也不提供可绑定的完整快照；现有 check 接口无版本/订阅 ID。故不能按**此前批准的来源版本设计**安全实现乱序处理或对账。当时提出的 DeepTutor-only“持久通知 + 在线当前态核验”草案**在该核对节点尚未获审阅/实施**；此后用户已批准重订版，实施进度见下文。新版任务 1.1 的目标环境既存接口适用性仍未验证。没有修改 EduPlus2、执行 test 数据写入/重试或部署。

本地重新执行 `test_application.py -k signed_webhook_demo_only_checks_delivery_without_state_change`：**1 passed，30 deselected**。该回归仅证明现行 mock 204、伪签名/过期拒绝、真实事件 503、租户状态和撤销表不变，不是正式 lifecycle 验收。

## 2026-09-27 重订版的本地实施进度（非 test 发布）

用户已单独批准重订版实施，仅在 DeepTutor 工作区使用隔离合成数据推进。新增 `eduplus2/0005_lifecycle_inbox.sql`、`lifecycle.py` 及企业组合接线：真实事件的白名单投影、目标应用校验、独立稳定 HMAC 业务摘要、事件 ID 幂等/冲突、事务性 inbox；同一事务使已验证学校旧允许状态失效。`204` 仅表示安全入队，存储失败返回 `503`。mock 不入队。OAuth Secret、原始 body、签名未加入持久字段。接收器运行开关 `DT_EDUPLUS2_LIFECYCLE_RECEIVER_ENABLED` **默认关闭**；本地合成测试临时启用，不代表 test-cn 已部署或真实事件已被确认。

已增加已验证学校—应用的 online resolve 对账、PG advisory lock 串行、本地 generation/绑定版本栅栏、证明 TTL、未知重试退避、重启与周期扫描，以及无 Webhook 时从既有已验证 registration 发现目标。现有会话及新登录在启用接收器后复核短时证明；原固定租户 `not_required` 且无外部学校绑定的路径仍保持兼容。`created.actor` 仅在学校绑定后落入 `pending_verification` 候选表；**没有**创建 TMS principal、assignment 或激活角色。按用户后续决策，本产品不再以独立取得当前订阅 ID 为首位激活门禁；候选仍须真实事件、可信本人同校登录、学校当前有效与一次性本地授权验收，故写入口继续关闭。

本地针对入队、重投/冲突与脱敏告警、Secret 轮换/独立性、过期证明、停用与恢复门禁、在线拒绝/超时/矛盾、重启重试、漏送扫描、并发锁、generation、超量 client、双学校隔离及 actor 待核验编写合成测试。新增 lifecycle 表已启用 `FORCE ROW LEVEL SECURITY`，隔离 PG 中验证 owner 无租户 GUC 不可旁路；版本化迁移的计划、重复执行、schema/index 漂移阻断和失败回滚均有测试。`PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short` 完整执行 **451 passed，3 skipped**；随后针对最新补充的入口/双学校用例执行 **4 passed**，相关应用/生命周期/迁移集合 **98 passed，1 skipped**。Ruff、`git diff --check` 与 OpenSpec strict validation 通过。未在目标 test 环境应用迁移、开启正式接收、重投首校事件或读取/写入真实学校业务数据。

**剩余放行门禁**：B1 的正式稳定内部学校绑定及跨校应用授权/运行角色验证（新增 lifecycle 表的 FORCE RLS 不替代 B1 全系统隔离）；真实 actor 投递合同与本人 TMS 一次性引导；所有入口（尤其管理、下载和后台派发）的短时证明与逐服务额度负例；生产所需的候选/收件箱保留清理政策及可观测指标；目标环境只读契约与真实事件 smoke。未完成前本 change 不勾选完成，接收器开关继续关闭，不能把外部学校“已订阅”解释为本产品已接入。

后续代码审查修复（仍只在隔离合成环境）：新增不可变 `0006_lifecycle_binding_proof.sql`，令旧在线证明迁移时失效，并把新证明绑定到 `oms.school_bindings.version`，撤销后重新核验不得复用旧证明；迁移 catalog 校验覆盖新增约束。配置的 OIDC issuer 已传至 `created.actor` 待核验交接，不再依赖测试手动赋值。对账改为逐个核验全部已知 client，旧 client 超时不覆盖另一当前有效证明，明确相互矛盾目标仍拒绝；消除原 16 个历史 client 上限造成的永久 `unknown`。证明时间和准入过期判断均使用 PostgreSQL `clock_timestamp()`，不受应用节点时钟偏移延长。针对绑定重新核验、issuer 传递、旧 client 故障、17 个历史 client、数据库时钟域及迁移约束漂移补回归；迟到旧 `created`、system/null 与重复事件仍只产生待核验事实，不激活管理员。企业全量测试 **455 passed，3 skipped**。Ruff、`git diff --check`、OpenSpec strict validation 均通过。迁移任务 1.2 仅在隔离合成 PG 验收；此处修复不改变上述目标环境与管理/多入口门禁，仍不得启用正式接收或宣称 change 已完成。

上游兼容只读复核：本轮没有修改 DeepTutor core，新增代码仍在 `extensions/enterprise/`；`git merge-tree --write-tree HEAD upstream/main` 对当前分支报告 63 个既存合并冲突（未涉及本次 enterprise 扩展路径），因此不能声称当前分支已可无冲突合并 upstream/main。任务 3.2 的完整上游兼容和认证、HTTP/WS、session ownership、审计关联验收仍未完成；未在工作树执行实际 merge。

后续 TMS actor 交接局部切片：新增 `management/actor_handoff.py` 的内部只读候选发现，仅对短时有效的可信 TMS `(issuer,sub,school,binding_version)` 返回同校、同应用、当前 issuer 且在线证明未过期的 `pending_verification` 事件事实，不授予角色或开放 API。新增不可变 `eduplus2/0007_actor_candidate_terminal_state.sql`，让候选可进入 `consumed`/`revoked` 终态并记录 `resolved_at`，触发器阻止身份事实修改、终态回退和删除；这是数据库完整性栅栏，**不是**以 PG 权限代替 Enterprise 程序授权。合成测试覆盖错 issuer/sub/学校/绑定版本、身份失效、过期证明、receiver 关闭、绑定撤销、终态后重新对账不复活；迁移重复执行及触发器漂移也已覆盖。交接服务尚未接可信 TMS 登录与事务性本人激活，因此 2.2a 和管理授权 3.3 仍未勾选；真实 `created.actor` 合同尚未验收，正式写入口保持关闭。

对账可观测性局部切片：新增仅内部使用的聚合快照，按 DB 时钟区分当前允许证明、过期证明、未知/拒绝目标、待绑定/待对账/重试 inbox 与待核验 actor 数量；worker 每轮刷新进程内计数，不向公开健康检查或未授权 API 泄露学校/订阅标识。合成测试验证计数及 worker 接线。保留/清理政策、长期监控出口及目标环境告警未验收，故 2.4 仍未勾选。

以上新切片完成后重跑企业全量测试 **464 passed，3 skipped**；Ruff、`git diff --check`、Webhook 与管理授权两份 OpenSpec strict validation 均通过。该验证只在隔离合成环境，未替代 test-cn 真实事件与双学校放行证据。
