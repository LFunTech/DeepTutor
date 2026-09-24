# M1 固定租户运行基线实施方案

## Why

DeepTutor 企业化路线中，M1 先交付固定租户运行基线，再由 G1 发布流水线完成目标环境构建、部署、smoke、回退和证据归档。此前 `add-m1-g1-single-tenant-production-baseline` 同时承载“固定租户 runtime 边界”和“Woodpecker/K8s 发布闭环”，容易让人误解为 Woodpecker 流水线由单租户模型推导而来。

本 proposal 将二者解耦：固定租户只定义 M1 runtime 的 tenant binding、权限边界、PG/ObjectStore/Secret/LightRAG provider、EduPlus2 exchange、HTTP/WS turn、资源上传引用和后续多租户/TMS/OMS 的未开放边界。Woodpecker server/agent、CI backend、registry、K8s namespace、Ingress/TLS、SecretStore、发布锁、回退和 release evidence 存储均不由本 proposal 决定。

## What Changes

- 新增 M1 固定租户运行基线能力：`enterprise-m1-fixed-tenant-runtime-baseline`。
- 保留并收敛原 A1/A2/B 边界成果：PG-only、固定 tenant/user bootstrap、owner guard、resource binding、ObjectStore 校验、LightRAG service readiness、EduPlus2 exchange、HTTP/WS `resource_ids` 提交和 audit/export 脱敏。
- 更新 `enterprise-eduplus2-fronting-auth-demo` delta：demo 在真实 `/api/v1/ws` 对话测试区域展示 local/test 文件选择 → upload intent → pre-signed PUT → complete → `resource_ids` 自动填充。
- 固化 runtime smoke/evidence 工具契约：可由本地/集成环境或独立 G1 发布流水线调用，但本 proposal 不创建目标 Woodpecker/K8s 拓扑。
- 明确 B2/C1/C2/H 边界：M1 保留 schema/API/证据输入，不开放多租户自助、TMS/OMS、生产 Handoff/OIDC callback、实时撤权 SLA 或多执行者/HA。

## Scope

### In scope

- 固定租户 runtime 配置契约：production mode、固定内部 tenant、PG-only、ObjectStore、Secret/Settings provider、LightRAG API binding、EduPlus2 exchange、模型 profile、audit/export、禁用本地权威 fallback。
- 第三方资源提交契约：DeepTutor 发放 pre-signed upload URL 与 `resource_id`，调用方直传 ObjectStore，HTTP/WS turn 只提交 prompt + `resource_ids`。
- 真实入口回归：企业组合入口、HTTP status/session、WebSocket `/api/v1/ws`、SDK/CLI 受控路径、EduPlus2 exchange/demo、resource binding、ObjectStore/LightRAG/audit。
- 权限和异常：跨 owner、伪造 tenant、过期/撤销 token、WS refresh 身份不匹配、Secret 缺失、ObjectStore/LightRAG unavailable、资源状态异常、本地 fallback 均 fail closed。
- Upstream mergeability：企业特有策略留在 `extensions/enterprise/`，core patch 仅作为通用 seam。

### Out of scope

- 不交付 Woodpecker/K8s 目标部署、registry、Ingress/TLS、SecretStore、发布锁、rollout、回退或 release evidence 存储；这些归 `add-g1-woodpecker-k8s-release-baseline`。
- 不交付 B2 多租户开放、租户自管理 TMS、在线 client/app 治理 UI、真实多租户切换。
- 不交付 C1/C2 OMS 运营后台。
- 不交付 H 高可用、多执行者或零停机发布。
- 不迁移真实业务数据或操作真实生产集群，除非后续单独授权。
- 不提交 `.secrets`、JWT、client secret、API key、用户隐私或完整生产配置值。

## Dependencies

- 上游能力：`postgres-only-runtime`、`sqlite-to-postgres-cutover`、`postgres-business-stores`、`enterprise-local-identity`、`enterprise-session-lifecycle`、`enterprise-scoped-persistence`、`externalized-runtime-configuration`、`externalized-resource-store`、`enterprise-runtime-composition`、`enterprise-eduplus2-federated-access`、`enterprise-eduplus2-fronting-app-integration`。
- 下游依赖：`add-g1-woodpecker-k8s-release-baseline` 依赖本 proposal 提供可部署 runtime、smoke harness、readiness/evidence 输出和固定租户测试边界。

## Delivery Plan

1. **基线盘点与差距冻结**：复核已归档 specs/evidence，确认 runtime 仍阻断生产的 SQLite/local `data/`/文件权威路径。
2. **Runtime 配置与 readiness**：固定 tenant、PG/ObjectStore/Secret/Settings/LightRAG/EduPlus2 binding 均 fail closed；生产入口禁止本地权威 fallback。
3. **资源与检索链路**：pre-signed upload、ObjectStore metadata/head 校验、HTTP/WS `resource_ids`、adapter 读取、LightRAG readiness、audit 关联。
4. **EduPlus2 demo 与 smoke**：前置 demo local/test happy path 与 dry-run smoke 展示同一资源引用边界，不宣称生产登录或资源治理 UI 完成。
5. **边界保护**：验证 TMS/OMS 未开放、多租户治理未开放、C2/H 后续缺口不被 G1 证据覆盖。
6. **Upstream 兼容审查**：记录 core seam 目的、风险和回归命令。

## Success Criteria

- `openspec validate add-m1-fixed-tenant-runtime-baseline --strict` 与 `openspec validate --all --strict` 通过。
- 固定租户 runtime 缺少 PG/ObjectStore/Secret/LightRAG/EduPlus2 必需配置时 fail closed。
- HTTP/WS/SDK/EduPlus2 demo/smoke 可以证明 prompt + `resource_ids`、ObjectStore 校验、owner/tenant guard、audit 脱敏和资源异常拒绝。
- 本 proposal 不再要求或推导 Woodpecker/K8s 拓扑；发布闭环由独立 G1 proposal 验收。
- 未完成 B2/C1/C2/H 的功能不会被标记为完成。
