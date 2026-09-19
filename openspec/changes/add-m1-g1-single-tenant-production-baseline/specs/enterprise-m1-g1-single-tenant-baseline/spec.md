## Purpose

定义 DeepTutor M1/G1 单租户 Kubernetes 生产基线：以固定租户为发布边界，确保 PG-only、ObjectStore/Secret/Settings provider、LightRAG Server API binding、EduPlus2 exchange、企业 HTTP/WS 入口、Woodpecker 流水线、迁移、smoke、回退和证据归档形成可验收的生产闭环。该能力不交付 B1/B2 多租户/TMS、C1/C2 OMS 或 H 高可用。

## ADDED Requirements

### Requirement: 生产基线必须声明固定租户运行边界与目标部署发布契约

系统 SHALL 提供 M1/G1 固定租户 Kubernetes 部署源或等价发布清单，覆盖 enterprise backend、frontend、应用 PostgreSQL、S3-compatible ObjectStore、Secret/Settings provider、LightRAG Server API binding、Ingress/TLS、readiness/liveness 和单执行限制。发布清单 MUST 使用镜像 digest、非敏感配置和 Secret ref，不得依赖 mutable tag、手工临时环境变量或明文 Secret。部署和流水线拓扑 MUST 来自目标部署契约；“单租户/多租户”只限定 runtime tenant binding、权限边界和 smoke scope，不得被用来推导 Woodpecker agent/backend、K8s namespace/Ingress/TLS、SecretStore、发布锁、回退或 evidence 存储方案。

#### Scenario: 目标部署契约未登记
- **WHEN** A3/G1 准备新增 K8s 部署源或 Woodpecker pipeline
- **THEN** 先记录目标 Woodpecker server/agent 版本、agent backend、受保护 ref、审批/Secret 边界、registry、K8s namespace、Ingress/TLS、SecretStore/RBAC、NetworkPolicy、发布锁、回退策略和 evidence 存放位置；未登记或未验证这些契约时，A3.1/A3.2 不得标记完成

#### Scenario: 生成 G1 候选发布清单
- **WHEN** 构建 G1 候选版本
- **THEN** evidence 中记录源码 SHA、企业包版本、前后端镜像 digest、schema version、runtime mode、Secret ref、ObjectStore endpoint 摘要、LightRAG service binding 摘要和 Ingress/TLS host，且不包含 JWT、client secret、模型 key 或用户隐私

#### Scenario: 必需依赖未配置
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

系统 SHALL 在 M1/G1 production runtime 中使用 PostgreSQL 作为业务状态权威，S3-compatible ObjectStore 作为持久文件权威，Secret provider 作为凭证权威。SQLite、PocketBase、本地 `data/`、本地 settings/grants/persona/skill/notebook 文件不得成为运行态业务权威或缓存替代。

#### Scenario: 检测到 SQLite 或本地权威路径
- **WHEN** production readiness inventory 发现 SQLite DSN、PocketBase、本地 authority provider、未分类 `data/` 写入或本地 settings/grants 权威
- **THEN** readiness 返回未就绪并输出脱敏错误 code，禁止对外宣称 G1 可用

#### Scenario: Pod 清空本地 data 后重建
- **WHEN** backend Pod 以空本地 `data/` 重建
- **THEN** 已提交的身份、会话、turn、audit、对象 metadata 和授权状态仍从 PG/ObjectStore/Secret provider 恢复，本地 scratch/projection 缺失不造成业务数据丢失

### Requirement: 迁移和固定租户 bootstrap 必须由独立发布步骤执行

系统 SHALL 使用独立迁移/初始化 Job 执行应用 PG schema migration、固定租户 bootstrap、默认 policy/profile 初始化和版本验证。应用 Deployment 的普通 startup/lifespan MUST 只校验版本和 readiness，不得在 Pod 启动时抢跑非幂等迁移。

#### Scenario: 重复执行迁移 Job
- **WHEN** 同一 G1 候选版本的 migration Job 被重复触发
- **THEN** Job 在迁移锁和 schema_history 校验下幂等完成或明确报告已应用，不重复创建 tenant/user/policy，不覆盖已有 Secret 或密码

#### Scenario: 迁移漂移或失败
- **WHEN** schema_history 漂移、迁移失败、权限不足、锁竞争或超时发生
- **THEN** pipeline 阻断部署并保存脱敏失败证据，不能继续 rollout、不能自动降库、不能用 `|| true` 放行

### Requirement: Woodpecker 必须完成构建、部署、smoke 与回退闭环

系统 SHALL 提供 Woodpecker pipeline 或等价自动交付流程，从受信提交构建一次、推送镜像、部署 by digest、执行迁移、部署到目标 K8s、运行业务 smoke、归档 evidence，并在 rollout/smoke 失败时执行受控回退或进入维护状态。PR、未批准 tag、过期批准、环境不匹配、旧构建覆盖和 Secret 越权 MUST 被拒绝。

#### Scenario: 受信提交部署到测试 K8s
- **WHEN** G1 pipeline 在受信分支或批准 tag 上运行
- **THEN** pipeline 完成 build/push/migrate/deploy/smoke/evidence 阶段，所有阶段记录 exit code、digest、release id、run id 和脱敏摘要

#### Scenario: rollout 或 smoke 失败
- **WHEN** 应用 rollout 超时、readiness fail、业务 smoke 失败或 pipeline agent 中断
- **THEN** release 状态标记失败，系统对账实际部署状态；如上一应用与当前 schema/对象格式兼容则受控回退并重跑 smoke，否则进入维护/前向修复流程

### Requirement: G1 smoke 必须覆盖真实 HTTP/WS/EduPlus2/ObjectStore/LightRAG/audit 路径

系统 SHALL 提供可重复的 G1 smoke harness，经真实 Ingress/TLS 路径覆盖 frontend/backend 可达、auth/status、EduPlus2 user JWT exchange、HTTP bearer 调用、WebSocket `/api/v1/ws` 认证与 `start_turn`、`auth_refresh`、session history/owner guard、ObjectStore 写读删或授权下载、`start_turn` 资源引用、audit query/export、必要负例和脱敏检查。目标环境具备 LightRAG 样本语料时，smoke MUST 覆盖 KB 导入/ready/检索/授权引用；若缺失该依赖，G1 MUST 记录为阻断或未完成项，不得声明完整生产上线。

#### Scenario: WebSocket 完成真实对话
- **WHEN** smoke 持有有效 `dt_token` 并连接 `/api/v1/ws`
- **THEN** smoke 发送 `start_turn` 并接收可归档的 progress/content/done 摘要，随后在 token 临期或刷新场景发送 `auth_refresh` 并收到同一身份的成功确认

#### Scenario: 权限和依赖负例
- **WHEN** smoke 使用过期/撤销 token、跨 owner session、伪造 tenant、ObjectStore 权限不足、LightRAG unavailable 或未授权 KB
- **THEN** 系统返回稳定脱敏错误并 fail closed，不泄露资源存在性、token、Secret 或其他用户内容

### Requirement: 回退必须按兼容发布组合执行并留证

系统 SHALL 将回退视为应用镜像、非敏感配置、schema 兼容性、ObjectStore binding、LightRAG binding 和 feature gate 的组合操作。应用回退不得假设数据库可自动降级；无安全回退版本时 MUST 进入维护/停止写入，并要求人工批准前向修复或成套恢复。

#### Scenario: 兼容应用回退
- **WHEN** 新版本 rollout 或 smoke 失败且上一应用版本兼容当前 schema/object/binding
- **THEN** pipeline 使用上一 release 的镜像 digest 和配置 ref 回退，重跑 smoke，并在 evidence 中记录失败原因、回退步骤、结果和仍需跟进项

#### Scenario: 不兼容回退
- **WHEN** 当前迁移或对象格式不允许旧应用安全写入
- **THEN** 系统保持维护状态或停止相关写入，不自动降库，不回退到 SQLite/local 文件权威，并记录前向修复或成套恢复决策需求

### Requirement: G1 evidence 必须可追溯且脱敏

系统 SHALL 为每个 G1 候选和发布保存 release evidence，至少包含源码 SHA、upstream 兼容审查、镜像 digest、schema version、迁移结果、部署状态、smoke run ID、审批/操作者、Secret ref、错误/回退记录、未验证项和后续风险。Evidence MUST 脱敏，禁止保存 JWT、DeepTutor `dt_token`、client secret、模型 key、完整 profile、用户隐私或原始业务正文。

#### Scenario: 生成 release evidence
- **WHEN** pipeline 完成或失败
- **THEN** evidence 可用于从发布结果追溯到源码、制品、迁移、环境、smoke、审批和回退状态，且 secret leakage scan 对 evidence 和日志无命中

#### Scenario: 未验证项存在
- **WHEN** LightRAG 样本检索、生产 Ingress、真实 EduPlus2 token、回退演练或 upstream 兼容检查未执行
- **THEN** evidence 明确记录未验证原因和影响；G1 结论不得越权声明这些范围已通过

### Requirement: M1/G1 不得声明 B/C/H 后续能力已完成

系统 SHALL 在文档、页面、pipeline 输出和 release evidence 中区分 M1/G1 单租户生产基线与 B1/B2 多租户/TMS、C1/C2 OMS、H 高可用能力。M1/G1 MAY 保留后续扩展所需 schema/API/证据输入，但 SHALL NOT 暴露未授权 TMS/OMS、多租户自助治理、生产 Handoff/OIDC callback、实时撤权 SLA 或多执行者/HA。

#### Scenario: 访问未交付管理入口
- **WHEN** 用户访问未纳入 M1 的 `/tms`、`/api/v1/tms/*`、`/oms` 或 `/api/v1/oms/*`
- **THEN** 系统返回明确不可用或未授权响应，不回落旧 admin、本地管理或隐藏入口

#### Scenario: 启用多执行者配置
- **WHEN** 部署配置请求多个实际 backend 执行者、跨 Pod fanout 或 HA rollout
- **THEN** G1 readiness 或 pipeline 阻断该配置，除非存在适用版本/拓扑的 G-H 通过证据
