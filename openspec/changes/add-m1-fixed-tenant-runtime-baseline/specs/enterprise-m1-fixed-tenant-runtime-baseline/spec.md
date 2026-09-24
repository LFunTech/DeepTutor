## Purpose

定义 DeepTutor M1 固定租户运行基线：以固定 tenant binding、PG-only、ObjectStore/Secret/Settings provider、LightRAG Server API binding、EduPlus2 exchange、企业 HTTP/WS/SDK 入口、runtime smoke 和脱敏 evidence 为边界，提供可被独立 G1 发布流水线调用的运行契约。该能力不定义 Woodpecker/K8s 发布拓扑，不交付 B2 多租户/TMS、C1/C2 OMS 或 H 高可用。

## ADDED Requirements

### Requirement: 运行基线必须声明固定租户 runtime 边界

系统 SHALL 在 M1 runtime 中绑定一个明确固定 tenant、授权主体、provider binding 和 smoke scope。Runtime 清单 MUST 覆盖应用 PostgreSQL、S3-compatible ObjectStore、Secret/Settings provider、LightRAG Server API binding、EduPlus2 exchange、readiness、audit/export 和单执行限制摘要。Runtime 边界 MUST NOT 被用于推导 Woodpecker agent/backend、K8s namespace/Ingress/TLS、SecretStore、发布锁、回退或 evidence 存储方案。

#### Scenario: 生成 runtime readiness 摘要
- **WHEN** 固定租户 runtime 执行 readiness 或 smoke plan
- **THEN** 输出 runtime mode、tenant/client/owner 短 hash、schema version、provider binding 摘要、Secret ref kind、ObjectStore endpoint 摘要、LightRAG binding 摘要和禁用本地 fallback 状态
- **AND** 不输出 JWT、`dt_token`、client secret、模型 key、完整 profile、用户隐私或目标发布环境明文

#### Scenario: 必需 runtime 依赖未配置
- **WHEN** production runtime 缺少应用 PG、ObjectStore、Secret provider、LightRAG binding 或 EduPlus2 exchange 所需配置
- **THEN** 启动或 readiness fail closed，不创建本地权威状态、不回退 SQLite、不继续派发模型或后台任务

### Requirement: 第三方资源提交必须采用服务端授权的 ObjectStore 绑定

系统 SHALL 为第三方应用提供受控资源上传契约：调用方先向 DeepTutor 申请 pre-signed upload URL，DeepTutor 生成绑定固定 tenant、owner、session/purpose 的 `resource_id` 和内部 ObjectStore key；调用方直传 S3-compatible ObjectStore 后，在提交 turn 时携带 prompt 与 `resource_id`/受控 resource key 清单。DeepTutor MUST 在模型、RAG 或后续多模态 adapter 使用资源前，从 ObjectStore 校验对象存在性、大小、MIME、checksum/hash、owner/tenant 绑定、资源状态和过期策略。生产 API MUST NOT 让调用方直接提交任意外部 URL、长期下载地址、大 base64 payload 或未登记对象路径给模型。

#### Scenario: 创建上传意图并直传对象
- **WHEN** 第三方应用声明资源 `modality`、`mime_type`、`size_bytes`、`sha256`、`purpose` 和业务关联来申请上传
- **THEN** DeepTutor 返回短 TTL 的 pre-signed upload URL、必须携带的 headers/policy、`resource_id`、过期时间和限制摘要；ObjectStore key 由 DeepTutor 生成并绑定当前 owner/tenant/session，调用方不得自选任意 key 前缀或 public-read ACL

#### Scenario: 通过 HTTP 或 WebSocket 提交 prompt 与资源清单
- **WHEN** 调用方完成上传并通过 HTTP turn API 或 WebSocket `start_turn` 提交 `prompt + resource_ids`
- **THEN** DeepTutor 对每个资源执行 ObjectStore `HEAD`/metadata 校验，确认资源属于当前授权主体且处于可用状态后，才通过 ObjectStore abstraction 读取资源并交给模型/RAG adapter；audit/evidence 只记录 `resource_id` 短 hash、mime、size、sha256 摘要、purpose 和状态，不记录 raw payload、signed URL、Secret 或用户私密正文

#### Scenario: WebSocket 不承载资源上传 payload
- **WHEN** WebSocket client 发送 `start_turn` 或其他命令并试图包含 raw binary、未登记 URL、大 base64 payload、调用方自选 ObjectStore key 或 pre-signed upload URL
- **THEN** 系统拒绝该命令或忽略 legacy payload 并返回稳定脱敏错误；WebSocket 只接受 DeepTutor 已发行且已完成上传/校验的资源引用，不通过长连接转发上传内容

#### Scenario: 资源绑定异常
- **WHEN** 资源未上传、上传 URL 过期、checksum/hash mismatch、MIME 或大小超限、资源 key 非 DeepTutor 发行、跨 owner/tenant/session 引用、资源已删除/隔离或 ObjectStore 权限不足
- **THEN** 系统返回稳定脱敏错误并 fail closed，不读取或转交该资源，不泄露对象是否属于其他用户或租户

#### Scenario: Provider 不支持请求的媒体类型
- **WHEN** prompt 引用图片、音频或视频资源，而当前模型 profile/provider adapter 未声明支持该 `modality`
- **THEN** 系统在模型调用前拒绝该 turn 或选择已配置的兼容处理链路；不得静默忽略资源、把多模态请求降级为纯文本成功，或把内部 ObjectStore key 暴露给 provider/调用方

### Requirement: 生产运行必须 PG-only 且禁止本地 data 权威 fallback

系统 SHALL 在 M1 production runtime 中使用 PostgreSQL 作为业务状态权威，S3-compatible ObjectStore 作为持久文件权威，Secret provider 作为凭证权威。SQLite、PocketBase、本地 `data/`、本地 settings/grants/persona/skill/notebook 文件不得成为运行态业务权威或缓存替代。

#### Scenario: 检测到 SQLite 或本地权威路径
- **WHEN** production readiness inventory 发现 SQLite DSN、PocketBase、本地 authority provider、未分类 `data/` 写入或本地 settings/grants 权威
- **THEN** readiness 返回未就绪并输出脱敏错误 code，禁止对外宣称 M1 runtime 可用

#### Scenario: 本地 data 缺失后恢复
- **WHEN** runtime 以空本地 `data/` 或无本地 authority provider 启动
- **THEN** 已提交的身份、会话、turn、audit、对象 metadata 和授权状态仍从 PG/ObjectStore/Secret provider 恢复，本地 scratch/projection 缺失不造成业务数据丢失

### Requirement: 固定租户初始化必须可由受控发布步骤调用且普通启动不抢跑

系统 SHALL 提供幂等的应用 PG schema migration、固定租户 bootstrap、默认 policy/profile 初始化和版本验证入口。应用普通 startup/lifespan MUST 只校验版本和 readiness，不得在进程启动时抢跑非幂等迁移。具体 Woodpecker/K8s Job 编排不属于本能力。

#### Scenario: 重复执行固定租户初始化
- **WHEN** 同一 runtime 候选版本的初始化入口被重复触发
- **THEN** 在迁移锁和 schema_history 校验下幂等完成或明确报告已应用，不重复创建 tenant/user/policy，不覆盖已有 Secret 或密码

#### Scenario: 迁移漂移或失败
- **WHEN** schema_history 漂移、迁移失败、权限不足、锁竞争或超时发生
- **THEN** runtime readiness 或调用方发布步骤阻断后续启动/rollout，并保存脱敏失败证据；不能自动降库、不能用 `|| true` 放行、不能回退 SQLite/local 文件权威

### Requirement: Runtime smoke 必须覆盖真实 HTTP/WS/EduPlus2/ObjectStore/LightRAG/audit 路径

系统 SHALL 提供可重复的固定租户 runtime smoke harness，覆盖 auth/status、EduPlus2 user JWT exchange、HTTP bearer 调用、WebSocket `/api/v1/ws` 认证与 `start_turn`、`auth_refresh`、session history/owner guard、ObjectStore 写读删或授权下载、`start_turn` 资源引用、audit query/export、必要负例和脱敏检查。目标环境具备 LightRAG 样本语料时，smoke SHOULD 覆盖 KB 导入/ready/检索/授权引用；若缺失该依赖，smoke MUST 输出未验证原因和影响。

#### Scenario: WebSocket 完成真实对话
- **WHEN** smoke 持有有效 `dt_token` 并连接 `/api/v1/ws`
- **THEN** smoke 发送 `start_turn` 并接收可归档的 progress/content/done 摘要，随后在 token 临期或刷新场景发送 `auth_refresh` 并收到同一身份的成功确认

#### Scenario: 权限和依赖负例
- **WHEN** smoke 使用过期/撤销 token、跨 owner session、伪造 tenant、ObjectStore 权限不足、LightRAG unavailable 或未授权 KB
- **THEN** 系统返回稳定脱敏错误并 fail closed，不泄露资源存在性、token、Secret 或其他用户内容

### Requirement: M1 runtime 不得声明 B/C/H 或 G1 发布能力已完成

系统 SHALL 在文档、页面、smoke 输出和 runtime evidence 中区分 M1 固定租户运行基线、B2 多租户/TMS、C1/C2 OMS、H 高可用和 G1 发布流水线。M1 runtime MAY 保留后续扩展所需 schema/API/证据输入，但 SHALL NOT 暴露未授权 TMS/OMS、多租户自助治理、生产 Handoff/OIDC callback、实时撤权 SLA、多执行者/HA、Woodpecker/K8s 发布或生产上线结论。

#### Scenario: 访问未交付管理入口
- **WHEN** 用户访问未纳入 M1 的 `/tms`、`/api/v1/tms/*`、`/oms` 或 `/api/v1/oms/*`
- **THEN** 系统返回明确不可用或未授权响应，不回落旧 admin、本地管理或隐藏入口

#### Scenario: 试图把 runtime evidence 作为发布完成证据
- **WHEN** 文档、页面、pipeline 或人工流程尝试把固定租户 runtime smoke 直接声明为 Woodpecker/K8s 发布成功、生产上线或 G1 完整通过
- **THEN** 系统或 evidence 模板 MUST 标记为越界声明，并指向独立 G1 发布流水线 proposal 的目标环境验证要求
