# M1/G1 单租户生产基线实施方案

## Why

DeepTutor 企业化路线已明确：M1 先交付单租户 Kubernetes（PostgreSQL + S3-compatible + LightRAG Server API + HugeGraph 作为 LightRAG 内部图后端），再进入 M2 多租户/TMS，最后 M3 统一 OMS。当前仓库已经归档多个基础切片：PG-only 迁移、企业身份/PG 会话、K8s 无状态资源外置、EduPlus2 API-only 联邦访问、前置应用契约与本地 demo。但这些切片仍是分散能力，并不等同于可上线的 M1/G1 生产基线。

G1 的关键缺口不是再做一个 demo，而是把“可构建、可迁移、可部署、可 smoke、可回退、可追溯”的单租户生产路径打通，并用真实 Kubernetes/Woodpecker/外置依赖证据证明：

- production runtime 不再回退 SQLite、本地 `data/` 权威或手工临时配置；
- DeepTutor core 与企业扩展包以可维护方式组合，继续满足 upstream mergeability；
- 应用 PG、ObjectStore、Secret、LightRAG 服务 binding、EduPlus2 exchange、WebSocket turn 以及第三方资源上传/引用链路在同一发布清单内可验收；
- 迁移失败、依赖不可用、授权异常、WebSocket/token 续签失败、rollout/smoke 失败时 fail closed；
- 首次上线和后续发布都有构建、镜像 digest、迁移、部署、smoke、回退和审计证据。

因此本 proposal 规划 **M1/G1 单租户生产基线**：以固定租户部署为边界，完成 Kubernetes 部署源、运行配置契约、Woodpecker 流水线、迁移/发布 runbook、业务 smoke 和证据模板。它不新增多租户/TMS/OMS 功能，也不把 EduPlus2 前置 demo 声称为生产登录能力。

## What Changes

- 新增 M1/G1 单租户生产基线 OpenSpec 能力：`enterprise-m1-g1-single-tenant-baseline`。
- 形成目标部署拓扑与发布清单：enterprise backend、frontend、应用 PostgreSQL、S3-compatible ObjectStore、Secret provider、LightRAG Server API binding、Ingress/TLS、readiness/liveness、单执行限制；部署/流水线拓扑必须来自目标环境契约，不能从“单租户/多租户”状态直接推导。
- 固化 runtime 配置契约：生产模式、固定内部 tenant、PG-only、ObjectStore/Secret/Settings provider、EduPlus2 exchange、LightRAG service binding、模型 profile、audit/export、禁用本地权威 fallback。
- 固化第三方资源提交契约：第三方应用先向 DeepTutor 申请受控 pre-signed upload URL，由 DeepTutor 生成 ObjectStore key/resource binding；第三方直传 S3-compatible ObjectStore 后，在 HTTP 或 WebSocket `start_turn` 提交 turn 时只提交 prompt + server-issued resource id/key 清单，DeepTutor 再经 ObjectStore 读取、校验并转交模型/RAG adapter。生产入口不得依赖调用方提供的任意外部 URL、长期可用下载地址或大 base64 payload。
- 更新 EduPlus2 前置应用 demo 与 smoke：demo 的真实 `/api/v1/ws` 对话测试区域必须内嵌 local/test 可执行的文件选择 → upload intent → pre-signed PUT → complete → `resource_ids` 自动填充演示，不再用独立资源说明板块代替完整流程；WebSocket 对话构造器必须使用 `resource_ids` 字段而非 `attachments.url/base64`；dry-run smoke 必须输出该资源链路为 delegated/待 A2.2 实测的证据项。
- 交付 Kubernetes 源与环境模板：在目标集群契约登记后补齐 namespace、Deployment/Service/Ingress、ConfigMap/Secret 引用、Job/CronJob、NetworkPolicy/ServiceAccount/RBAC、probe、资源请求/限制、单执行 rollout 策略。
- 交付 Woodpecker A3/G1 流水线：在目标 Woodpecker server/agent、受保护 ref、审批/Secret 边界和 registry 契约确认后，构建一次、推送镜像、锁定 digest、运行迁移、部署到 test K8s、业务 smoke、生产批准、受控回退、证据归档。
- 交付 M1 smoke 套件：覆盖认证、EduPlus2 exchange、HTTP status、WebSocket `start_turn` / `auth_refresh`、session owner guard、pre-signed upload、HTTP/WS `resource_ids` 提交、ObjectStore、LightRAG/KB 可用性（目标环境具备时）、audit query/export、负例与脱敏检查。
- 交付迁移和回退 runbook：应用 PG migration、LightRAG 侧依赖状态核对、S3/Secret binding、失败阻断、兼容回退、无安全回退时的维护/前向修复流程。
- 交付 release evidence 模板：源码 SHA、upstream SHA/兼容审查、镜像 digest、schema 版本、配置清单、Secret ref、smoke run ID、失败/回退证据和未验证项。

## Scope

### In scope

- **M1/A1 收敛核对**：PG-only 与固定租户身份/会话/owner guard 的生产配置、迁移、真实 HTTP/WS/SDK 入口回归。
- **M1/A2 收敛核对**：ObjectStore、settings/Secret provider、pre-signed upload/resource binding、资源链路、LightRAG service binding、KB/文档/检索可用性门禁。
- **M1/A3/G1 生产验收**：Kubernetes manifests、Woodpecker pipeline、迁移 Job、部署、smoke、回退、证据归档。
- **EduPlus2 作为 M1 smoke 输入**：使用已归档 exchange/fronting contract 和 demo 的测试路径验证 `dt_token`、WS 续签以及 `resource_ids` 引用提交边界；demo 可执行 local/test 资源预上传 happy path，但不把 demo 升级为生产登录入口、生产资源治理 UI 或完整多模态模型编排。
- **Upstream mergeability**：所有产品/企业实现优先在 `extensions/enterprise/` 和部署源中完成；必要 core patch 只作为通用 seam，并记录目的、入口、风险和验证。
- **Fail-closed 与负例**：依赖缺失、Secret 缺失、迁移漂移、SQLite/local fallback、跨 owner、过期/撤销 token、WS refresh 不匹配、LightRAG unavailable、ObjectStore 权限不足、rollout/smoke 失败均阻断 G1。

### Out of scope

- 不交付 B1/B2 多租户开放、租户自管理 TMS、在线 client/app 治理 UI、真实多租户切换。
- 不交付 C1/C2 OMS 运营后台。
- 不交付 Handoff/OIDC callback 生产登录、实时撤权 SLA 或周期合法性调度；这些仍属后续 proposal。
- 不交付完整音频/视频/图片多模态模型编排能力；M1/G1 只固化可扩展的 ObjectStore 资源提交、安全校验、审计和 adapter 读取契约。
- Demo 只体现 local/test 资源预上传 happy path 和 turn 引用边界；除 A2.2 明确验证项外，不把 demo-only 页面等同于生产资源治理 UI、目标 ObjectStore 验收或完整多模态能力。
- 不把 LightRAG 内部 PG/HugeGraph schema/ACL 迁移实现放入 DeepTutor 企业包；DeepTutor 只绑定服务 API 与部署记录，LightRAG 侧由匹配制品/运维 Job 管理。
- 不实现多执行者/HA；首发为单执行模式。若目标拓扑启用多执行者或 HA，必须先通过 G-H。
- 不迁移真实业务数据或操作真实生产集群，除非后续单独获得环境、窗口和凭证授权。
- 不提交 `.secrets`、JWT、client secret、API key、用户隐私或完整生产配置值。

## Capabilities

### New Capability

- `enterprise-m1-g1-single-tenant-baseline`：定义 M1/G1 单租户 Kubernetes 生产基线的部署、配置、流水线、迁移、smoke、回退和证据验收契约。

### Related Existing Capabilities

- `postgres-only-runtime`、`sqlite-to-postgres-cutover`：M1/G1 不允许运行态 SQLite/local fallback。
- `postgres-business-stores`、`enterprise-local-identity`、`enterprise-session-lifecycle`、`enterprise-scoped-persistence`：固定租户身份、会话、turn、owner guard 和审计的生产路径。
- `externalized-runtime-configuration`、`externalized-resource-store`、`kubernetes-stateless-runtime`：ObjectStore/Secret/Settings provider 与 Pod 无状态恢复。
- `enterprise-eduplus2-federated-access`、`enterprise-eduplus2-fronting-app-integration`、`enterprise-eduplus2-fronting-auth-demo`：EduPlus2 exchange、前置契约和 local/test demo，作为 smoke 输入而非生产登录完成声明。
- `enterprise-runtime-composition`：企业应用组合根和 upstream-neutral core seam。

## Delivery Plan

1. **基线盘点与差距冻结**：读取已归档 specs/evidence 和 docs/enterprise，列出 M1/G1 必需能力、已有实现、缺口、环境前提和不得越界项。
2. **部署源与配置契约**：先登记目标部署契约（Woodpecker、registry、namespace、Ingress/TLS、SecretStore、RBAC、发布锁、回退和 evidence 存放位置），再补齐 `extensions/enterprise/` 或部署目录中的 K8s/Helm/Kustomize/manifest 源、ConfigMap/Secret ref、NetworkPolicy、probe 和单执行策略。
3. **迁移与 readiness**：确保应用 PG migration、固定租户 bootstrap、ObjectStore/Secret/LightRAG/EduPlus2 readiness 均 fail closed；运行进程只校验版本，不在普通 lifespan 中抢跑迁移。
4. **Woodpecker pipeline**：按目标 Woodpecker 契约实现 build/push/migrate/deploy/smoke/rollback/evidence 阶段，锁定 digest 与环境审批，拒绝 PR/未批准 tag/过期批准/Secret 越权/旧构建覆盖。
5. **Smoke harness 与 demo**：补齐可重复、脱敏、目标环境可运行的 HTTP/WS/EduPlus2/pre-signed upload/ObjectStore/LightRAG/audit/negative smoke；更新 EduPlus2 fronting demo，在真实 `/api/v1/ws` 对话测试区域执行并展示文件选择 → upload intent → pre-signed PUT → complete → `prompt + resource_ids`，验证 HTTP/WS turn 只携带资源引用、不承载上传 payload；每次输出 run ID 和证据路径。
6. **回退与恢复演练**：测试 migration 幂等、rollout/smoke 失败、兼容应用回退、无安全回退时维护模式，以及 release state 对账。
7. **Upstream 兼容审查**：记录 core patch 清单、通用 seam 目的和 upstream merge 风险；跑基础 auth/HTTP/WS/session/audit 回归。
8. **G1 收口**：在同构 test K8s 通过完整流水线；若获授权，再晋级目标生产环境并保留完整证据。未跑真实生产前只能标记“集成 G1 通过”，不能宣称已生产上线。

## Success Criteria

- `openspec validate add-m1-g1-single-tenant-production-baseline --strict` 与 `openspec validate --all --strict` 通过。
- 单租户 production runtime 在 K8s/test 目标中启动；缺少 PG/ObjectStore/Secret/LightRAG/EduPlus2 必需配置时 fail closed。
- Woodpecker 从受信提交构建并推送镜像，部署时使用 digest 而非 mutable tag；迁移/部署/smoke/回退阶段均有证据。
- Smoke 经真实 Ingress/TLS 路径完成登录/exchange、HTTP status、WebSocket 对话、`auth_refresh`、session owner guard、pre-signed upload、HTTP/WS `resource_ids` 提交、ObjectStore 校验/读取、audit、必要 negative cases；EduPlus2 demo 页面与 dry-run smoke 也展示同一资源引用边界；配置具备时完成 LightRAG/KB 检索链路。
- 迁移重复执行幂等，漂移/失败阻断；rollout 或 smoke 失败能受控回退兼容应用，或进入明确维护/前向修复状态。
- Release evidence 可追溯到源码 SHA、upstream 兼容审查、镜像 digest、schema 版本、配置/Secret ref、resource upload policy 摘要、resource binding 摘要、smoke run ID 和批准人。
- 未完成 B1/B2/C1/C2/H 的功能不会被标记为完成；M1/G1 结论明确区分“集成环境通过”和“生产已上线”。
