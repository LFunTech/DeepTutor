# 10. 用户数据同步与 Webhook 方案

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

Webhook 用于应用安装、租户授权、client 配置变更、secret 轮换、用户/组织/权限变化等状态同步，不是 TMS/OMS 每次登录或第三方 `POST /api/v1/auth/eduplus2/exchange` 的主链路。普通第三方调用仍必须实时验签 EduPlus2 user JWT，并查 active client/app 注册状态；即使暂未接入 Webhook，也不能放松 token 校验或使用未审计的手工配置绕过注册流程。

安全要求：

1. 校验 `X-EduPlus-Signature`。
2. 校验 timestamp 防重放。
3. 使用原始 body 计算签名。
4. 不记录敏感 token。
5. 完成持久化接收后 2xx 响应，处理异步化；重复事件读取既有幂等状态。

## Webhook 幂等

存储：PostgreSQL webhook_events 表；验证签名和事件来源后通过 registry 映射内部 tenant，事务保存事件后才返回 2xx。PG 失败返回可重试错误，不先响应后把事件放进进程内队列。

幂等 key：

```text
tenant_id + event_id
```

处理状态：

```text
received
processing
succeeded
failed
ignored
```

## Webhook 处理策略

| 事件类别 | 建议行为 |
| --- | --- |
| 租户开通/停用 | 仅更新经验证的 external_eligibility/来源版本，再重算准入；外部停用拒绝新登录/turn/派发并撤权，外部恢复不能覆盖 local_enabled=false |
| 用户/组织变化 | 标记对应租户需要重新同步 |
| 权限变化 | 清理权限 cache / grants cache |
| 应用订阅变化 | 仅更新外部资格/订阅能力快照，与平台分配及租户开关取交集，不直接覆盖本地功能开关 |

即使有 Webhook，也不能完全依赖事件补齐状态；仍需周期性完整对账。事件和对账都遵守 [03 的独立状态来源](03-tenant-scope-schema.md#租户状态的独立来源)：各来源幂等/版本比较，乱序或顺序不可验证时重新获取权威状态，不能用快照整行覆盖本地暂停或 provisioning 状态。验收“本地暂停后外部 active”“外部停订后本地恢复”“订阅恢复但本地功能仍关闭”及重复/乱序事件。

## 数据最小化

- 不同步 DeepTutor 不需要的敏感字段。
- 字段缺失时做防御式处理。
- 日志中脱敏手机号、身份证号、token、签名、handoff code。
- 用户数据缓存按租户隔离。

## 外部契约验证

上述字段、事件类别及权限映射是对接清单，实施 B1/B2 时必须以目标 EduPlus2 实际文档、注册配置和契约测试确认为准；无法获取必要资料时不得假定端点/事件存在或放松校验。
