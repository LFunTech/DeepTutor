# 10. 用户数据同步与 Webhook 方案

> **2026-09-27 新权威边界（本地实施中）**：学校接入及订阅生命周期只采信目标应用的已验签真实 Webhook，取消 online resolve 二次核验与周期证明 TTL；EduPlus2 OIDC/JWKS 仍负责用户认证，DeepTutor Enterprise 自行决定权限。当前工作区已有接收事务内自动建校/PG onboarding、投影、TMS 本人激活入口和隔离合成测试；多学校 **AI 运行时**由 B1/B2、OMS/TMS 另行实施，不是 Webhook 数据库链路的前置。已部署 test-cn 旧镜像的真实投递仍为 503；下文旧在线核验切片仅是历史现状，见 `add-b2-eduplus2-tenant-lifecycle-webhook` 最新 proposal/design/spec/tasks。

## 阶段边界

外部契约和注册准备从 A1 并行；B1 完成首租户登录业务态、必要事件与撤权闭环，但首个指定租户对接可先不依赖 Webhook，使用实时校验、手动/受控同步和短期缓存失效完成闭环；B2 完成多租户必要关系、Webhook 重试和周期对账，不推迟到运营后台。M1 发布没有 EduPlus2 同步依赖；C1 提供基本操作审计，C2 完善同步状态、授权重试与审计视图。所有缓存/幂等状态使用现有 PG，不开发 SQLite/JSON 同步过渡后端。

### 当前实现状态（2026-09-17）

当前 repo 的 EduPlus2 切片已提供可选 profile/permission client、snapshot、签名 revocation webhook 基础入口和审计事件，但**实时撤权传播不是当前 gate**。如果没有 webhook 或事件对账 SLA，外部用户合法性窗口由前置应用的打开/refresh/周期校验策略负责；DeepTutor 仅保证自身 exchange/resolve、短期 `dt_token`、owner/resource guard 和可选 profile/permission/webhook 路径 fail closed。

未来若需要“实时撤权传播”或乱序/部分失败恢复/周期对账 SLA，应另立 proposal；不要把当前可选 webhook 基础入口解释为完整 B2 多租户同步闭环。

## 实现归属

同步、Webhook、权限事件处理和外部 API client 均位于独立企业包，接收路由由企业应用装配，持久化走同一 PG provider；不为放在包外另建临时网关或第二套状态。job/重试必须携带可信内部 scope 并在执行时重验，事件失效需覆盖应用、RAG Gateway 的凭证/缓存和后续派发，详见 [13](13-deployment-and-upstream-sync.md) 与 [06](06-postgresql-native-store-plan.md)。

## 目标

DeepTutor 需要从 EduPlus2 获取当前登录用户业务态，以及必要的组织/班级/学生关系，用于：

- 判断用户身份类型和功能模式。
- 支持教师查看所教班级/学生。
- 支持家长关联学生。
- 支持租户管理员管理本校资源。
- 降低高频交互时对 EduPlus2 API 的实时依赖。

参考：

- Me Profile API：<https://eduplus-test.f123.pub/docs/user-data/me-profile-api/>
- 组织与用户数据对接：<https://eduplus-test.f123.pub/docs/user-data/org-sync-guide/>
- Webhook：<https://eduplus-test.f123.pub/docs/webhook/>

## `/api/v1/me/profile` 使用

登录后调用 EduPlus2：

```text
GET /api/v1/me/profile
Authorization: Bearer {eduplus_access_token}
```

DeepTutor 使用字段：

| 字段 | 用途 |
| --- | --- |
| `tenant_id` | 按实际 API 契约校验外部 token `tid`，再映射内部租户 |
| `eduplus_user_id` | 校验外部 token `eui`，映射内部 user_id，不重写资源所有权 |
| `active_identity_type` | 功能模式和 role 初判 |
| `identity_types` | 多身份切换或提示 |
| `school_code` | 展示、租户调试、审计 |
| `organization` | 组织上下文 |
| `classes` | 教师/学生班级关系 |
| `linked_students` | 家长关联学生 |

## Profile 缓存

生产使用 PG `eduplus_profile_cache`；主键/索引包含内部 tenant_id、user_id、外部 eit、azp，避免不同租户相同 eui 撞缓存。

缓存策略：

- TTL：5-30 分钟，按业务时效要求配置。
- 登录时强制刷新。
- Webhook 或用户主动切换身份时清理。
- 不缓存 access token / refresh token 明文。

## 组织数据同步模式

EduPlus2 文档提供两类模式：

| 模式 | 说明 | DeepTutor 建议 |
| --- | --- | --- |
| 实时查询 | 每次业务请求调用 EduPlus2 API | 低频管理后台可用 |
| 本地缓存 + 周期性全量对账 | 本地库保存副本，定期完整遍历 | 推荐用于课堂/聊天等高频能力 |

DeepTutor 推荐本地缓存模式，因为 agent turn 频繁调用外部 API 会增加延迟和失败点。

## 缓存存储

PostgreSQL 租户级表承载主数据必要副本，internal tenant_id 外键/RLS，外部记录 ID 用于映射与幂等。不新增 tenant-local SQLite。

建议表：

```text
eduplus_users
eduplus_orgs
eduplus_classes
eduplus_students
eduplus_parents
eduplus_teacher_class_relations
eduplus_student_class_relations
eduplus_parent_student_relations
sync_batches
```

字段保留原则：

- 只存业务必要字段。
- 遵循 EduPlus2 DataAccessPolicy，字段可能缺失，不可假设必定存在。
- 使用 `eduplus_user_id` / EduPlus record `id` 做幂等键。

## 同步任务

建议：

```text
extensions/enterprise/src/deeptutor_enterprise/integrations/eduplus2/sync.py
```

职责：

1. 使用应用凭证获取或刷新访问 token。
2. 按 EduPlus2 文档分页/游标遍历用户与主数据。
3. 每轮同步生成 `sync_batch_id`。
4. 完整遍历成功后，再处理本地存在但本轮未返回的记录。
5. 记录同步开始、结束、失败原因。

注意：EduPlus2 主数据端点不一定提供增量变更流，需要周期性完整对账。

## Webhook 入口

新增：

```text
POST /api/v1/eduplus2/webhooks
```

当前企业组合已提供此路径的**已验签控制台 mock 接收**：读取 `DT_EDUPLUS2_WEBHOOK_SECRET_REF`（或本地兜底 `DT_EDUPLUS2_WEBHOOK_SECRET`），按 EduPlus2 的 `timestamp.event.raw-body` 三段式 HMAC-SHA256 校验 `X-EduPlus-*` 头；仅 `X-EduPlus-Mock: true` 且 `event_id=mock_...` 的 demo 请求返回 204，不修改租户状态。2026-09-26 已在 `test-cn` HTTPS URL 由 EduPlus2 `智能体基座` 控制台实际执行 8 类订阅事件 demo，发送端投递记录均为 HTTP 204；此证据只覆盖 mock URL 联调。

`rc.50` 在 test-cn 发布的是此前“通知 + 在线核验”切片，但正式接收器未配置启用；真实订阅重试返回 503，目标 inbox 和学校绑定仍为空。**当前工作区尚未发布的新代码**改为 Webhook 事务内原子写 inbox、稳定学校绑定、目标应用 client、PG onboarding 标记、生命周期投影与最小 actor 候选，不再依赖 online resolve 或证明 TTL。学校初始仍为 `local_enabled=false`、AI 资源 `pending`，但本人可凭已验签 OIDC JWT 经 TMS 引导入口完成首位管理员激活；真实 `actor.user_id` 与 JWT `sub` 等价性仍待 test 脱敏证据。不因 PG onboarding 或 204 开放 AI 新调用。Secret 不写入本文或日志，详情见对应 OpenSpec `implementation-evidence.md`。

`.secrets/.test-secrets` 仅是本地测试输入，不会自动同步至测试 K8s。`test-cn` 受保护 tag 发布步骤从 Woodpecker 仓库 Secret `dt_test_cn_eduplus2_webhook_secret` 注入密钥，仅同步目标命名空间运行时 Secret 的 `DT_EDUPLUS2_WEBHOOK_SECRET` 字段后才继续部署；后端通过已有 `envFrom` 和 `DT_EDUPLUS2_WEBHOOK_SECRET_REF`/同名变量读取。应核对 Woodpecker、K8s 与 EduPlus2 对应 Webhook 使用同一密钥；不能靠本地文件存在便认定公网 URL 可验签。

正式接收另需由**本系统**发布契约配置 `DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY_REF`（独立稳定密钥，不与 Webhook Secret 共用）、`DT_EDUPLUS2_OIDC_ISSUER` 和 `DT_EDUPLUS2_LIFECYCLE_RECEIVER_ENABLED=true`。目标应用 ID 从已验签 Webhook body 的 `app.id` 取得并按学校—应用持久化，不再配置静态应用 ID；TMS 将已验签 JWT 的 `azp` 与该投影对应的 active client 绑定，不能仅凭 body 或 URL 选择应用。轮换时可选 `DT_EDUPLUS2_WEBHOOK_PREVIOUS_SECRET_REF` 和 Unix 秒截止 `DT_EDUPLUS2_WEBHOOK_PREVIOUS_UNTIL`。Webhook 生命周期接收不需要 `DT_EDUPLUS2_LIFECYCLE_PROOF_TTL_SECONDS` 或 online resolve；其余 OAuth 用途可能仍需独立 provider 配置。目标环境合约、迁移、资源与全入口门禁未验收前，接收开关必须保持关闭；不能把新增密钥硬编码到 Git 或仅因签名正确就开通业务。

本节当前已实现的 Webhook 只处理八类应用订阅 `subscription.*` 通知；应用安装、client 配置、用户/组织/权限变化若要同步，仍需各自独立合同和提案，不能假定此入口已覆盖。它不是 TMS/OMS 每次登录或第三方 `POST /api/v1/auth/eduplus2/exchange` 的主链路。普通第三方调用仍必须实时验签 EduPlus2 user JWT，并查 active client/app 注册状态；即使暂未接入 Webhook，也不能放松 token 校验或使用未审计的手工配置绕过注册流程。

安全要求：

1. 校验 `X-EduPlus-Signature`。
2. 校验 timestamp 防重放。
3. 使用原始 body 计算签名。
4. 不记录敏感 token。
5. inbox、学校映射和生命周期投影同事务提交后才 2xx；失败返回可重试 5xx，重复事件读取既有幂等状态。

## Webhook 幂等

> 以下描述当前工作区代码，尚未在 test-cn 发布或验证真实事件。

当前接收器将目标应用正确且已验签的真实事件最小业务事实写入 `eduplus2.lifecycle_inbox`；首次 `subscription.created` 直接按稳定 `tenant.id` 自动且幂等创建学校 PG 锚点/绑定/client/投影/onboarding 标记，非 created 的未知学校事件仅留脱敏 inbox 并以 `denied/school_not_bound` 终结，不凭其建校或遗留永久 pending。`school_code` 仅保存为显示信息，不作绑定/授权键。PG 事务内完成投影后才返回 204，失败返回可重试 5xx，不先响应后放进进程内队列。原始 body、OAuth Secret、签名不入库；稳定独立摘要密钥对不含投递时间的业务投影做 HMAC，同 ID 不同业务事实拒绝为 409。`webhook_school_controls` 保存与订阅投影独立的本地人工冻结；后续恢复事件不清除冻结。内部 OMS 程序服务要求 `ops.reconciliation.manage`、目标学校、expected_version、命令 ID 与审计；正式 OMS 身份/UI 入口仍归权限/OMS 提案。

幂等 key：

```text
部署收件箱 tenant_id + event_id
```

处理状态：

```text
pending_binding
pending_reconcile
verified
denied
retry
```

上述 `pending_*` 是历史兼容状态；当前同事务接收不会在返回 204 后留下待投影/待初始化任务。只读聚合指标监测签名拒绝、冲突、事务失败、静默学校、历史 pending 与冻结数；静默仅触发告警，不推断外部停订。inbox/event ID、actor 终态和冻结命令默认不自动删除，以维持幂等与审计；容量阈值触发冷归档设计/人工审阅，而不是直接清表。

## Webhook 处理策略

| 事件类别 | 建议行为 |
| --- | --- |
| 学校订阅八类 `subscription.*` | 已验签 payload 为学校接入/生命周期权威，按学校—应用本地接收顺序事务投影；无来源单调版本，漏送/迟到无法自动纠正。外部恢复不能覆盖 `local_enabled=false` 或资源 pending/隔离。 |
| 用户/组织变化 | 标记对应租户需要重新同步 |
| 权限变化 | 清理权限 cache / grants cache |
| 应用订阅变化 | 在已验证学校—应用—client 绑定下复核当前资格；OMS 逐服务额度是独立门禁，不生成生命周期事件。 |

上文“周期性完整对账”仅适用于**用户/组织等主数据同步**，不适用于本提案的学校订阅生命周期。订阅生命周期没有受信来源版本/快照可用于自动对账，本系统只按已持久接收顺序投影；漏送或迟到可能导致本地状态与 EduPlus2 最终状态不同，需告警和授权人工冻结/恢复，而不能偷偷调用 online resolve 改写 Webhook 权威或以快照覆盖本地 `local_enabled`/`provisioning_status`。验收“本地暂停后外部 active”“外部停订后本地恢复”“订阅恢复但本地功能仍关闭”及重复/乱序事件。

## 数据最小化

- 不同步 DeepTutor 不需要的敏感字段。
- 字段缺失时做防御式处理。
- 日志中脱敏手机号、身份证号、token、签名、handoff code。
- 用户数据缓存按租户隔离。

## 外部契约验证

上述字段、事件类别及权限映射是对接清单，实施 B1/B2 时必须以目标 EduPlus2 实际文档、注册配置和契约测试确认为准；无法获取必要资料时不得假定端点/事件存在或放松校验。
