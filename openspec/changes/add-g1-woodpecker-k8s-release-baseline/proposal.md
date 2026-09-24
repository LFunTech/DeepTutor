# G1 Woodpecker/K8s 发布流水线基线实施方案

## Why

Woodpecker 流水线与租户数量没有必然关系。它属于生产交付和 G1 release gate：从受信提交构建一次、推送镜像、锁定 digest、按显式目标环境执行迁移、部署到对应 Kubernetes、运行业务 smoke、归档 evidence，并在失败时受控回退或进入维护/前向修复状态。实际部署可能存在 local/test/pre/staging 以及多个不同生产环境，流水线必须从受保护 deployment tag 解析 `target_env_id`，再用环境 registry 校验目标，不能把“prod”当成唯一、默认或隐含环境。

此前 `add-m1-g1-single-tenant-production-baseline` 把固定租户 runtime 与 Woodpecker/K8s 发布闭环放在同一 proposal，容易误导为 CI/K8s 拓扑可以由“单租户/多租户”推导。该误导已经在历史 execution evidence 中导致通用 `.woodpecker` 与 K8s YAML 被撤回。本 proposal 专门承接 A3/V.3：发布拓扑必须来自目标部署契约，而不是来自租户模型。

## What Changes

官方文档约束：native `from_secret` 适合引用配置中已声明的 secret 名称；本 proposal 不依赖 shell 中动态计算的 `<ENV_KEY>` 去拼接 `from_secret` 名称。单流水线适配多环境必须采用受支持模式：优先使用 Woodpecker Secret Extension 按 tag/env registry 返回同一组逻辑 secret 名称；或使用 Configuration Extension 在配置解析前生成含静态 `from_secret` 的环境化配置；native-only 兜底只能用按环境静态声明的步骤/secret 与 `when.ref` 过滤。


- 新增 G1 发布流水线能力：`enterprise-g1-woodpecker-k8s-release-baseline`。
- 要求在新增任何 Woodpecker pipeline 或 K8s manifest 前，先登记环境 registry、deployment tag 规则、Woodpecker secrets 清单与每个部署目标契约：`env_id`、环境类别（test/pre/prod 等）、生产环境分组、允许 tag pattern、Woodpecker server/agent 版本、agent backend、受保护 ref、审批/Secret 边界、registry、K8s namespace、Ingress/TLS、SecretStore/RBAC、NetworkPolicy、发布锁、回退策略和 evidence 存放位置。
- 交付 Woodpecker build/push/migration/deploy/smoke/rollback/evidence 阶段，使用镜像 digest、从 tag 解析出的 `target_env_id`、环境锁和批准门禁；一次 deployment tag 只能部署一个目标环境，多生产环境必须逐环境打 tag、逐环境留证。
- 交付 K8s 部署源或等价发布清单：backend/frontend/Job/Service/Ingress/ConfigMap/Secret ref/NetworkPolicy/ServiceAccount/probes/resources，并明确单执行 rollout 策略。
- 复用 `add-m1-fixed-tenant-runtime-baseline` 的 readiness、smoke harness、resource binding 和 EduPlus2/API/WS 测试入口；不在本 proposal 重新定义 tenant runtime 规则。
- 固化 Woodpecker secrets 契约：按 `target_env_id` 声明 registry push、K8s deploy、SecretStore、migration、runtime Secret ref、smoke credentials、evidence store、tag/approval 校验等 secret；Secret Extension 模式下 pipeline 使用稳定逻辑名（如 `REGISTRY_PUSH_TOKEN`），由 extension 根据 tag/env registry 返回对应环境的值；native/static 模式下才使用 `DT_<ENV_KEY>_*` 静态名称。只记录 secret 名称/ref、用途、权限、作用域和轮换要求，不记录明文。
- 归档 release evidence：源码 SHA、upstream SHA、digest、schema、配置/Secret ref、smoke run ID、批准人、失败/rollback 结果、未验证项和 secret leakage scan 摘要。

## Scope

### In scope

- 环境 registry、目标部署契约登记与验证；支持多个生产环境并禁止默认生产目标。
- Woodpecker pipeline：受信 ref、审批、Secret 边界、build once、push image、digest lock、migration、deploy、smoke、rollback、evidence。
- Kubernetes 发布源：namespace、Deployment/Service/Ingress、ConfigMap/Secret ref、Job、NetworkPolicy/ServiceAccount/RBAC、probe、资源请求/限制、单执行 rollout 策略。
- 发布期 fail-closed：tag 缺失/格式错误/未保护/未授权/被移动、无法从 tag 精确解析 `target_env_id`、PR/未批准 tag/过期批准/环境不匹配/缺失必需 secret/跨环境 Secret 越权/旧构建覆盖/迁移失败/rollout 失败/smoke 失败/agent 中断/并发发布竞争。
- Release evidence 与脱敏/secret leakage scan。

### Out of scope

- 不定义固定租户 runtime、PG/ObjectStore/LightRAG/EduPlus2/resource binding 业务规则；这些由 `add-m1-fixed-tenant-runtime-baseline` 提供。
- 不把 Woodpecker/K8s 拓扑硬编码为“单租户专用”；后续 M2/M3 和 upstream 更新应复用同一发布基线或通过兼容演进。
- 不交付 B2 多租户/TMS、C1/C2 OMS、H 高可用或多执行者安全。
- 不迁移真实业务数据或操作真实生产集群，除非后续单独获得环境、窗口和凭证授权。
- 不提交 `.secrets`、JWT、client secret、API key、用户隐私、完整生产配置值或任何 Woodpecker secret 明文；proposal/evidence 只能记录 secret ref、短 hash、权限摘要和校验结果。

## Dependencies

- 依赖 `add-m1-fixed-tenant-runtime-baseline` 提供可部署 enterprise runtime、readiness、smoke harness、固定 tenant 测试边界、resource upload/reference demo 和 upstream-neutral core seam 清单。
- 依赖每个目标环境授权：Woodpecker server/agent、registry、K8s cluster、Ingress/TLS、SecretStore/RBAC、ObjectStore/LightRAG/EduPlus2 test credentials、发布窗口和审批人；多个生产环境必须分别登记、审批和留证。
- 若目标拓扑要求多执行者/HA，必须先通过 G-H；本 proposal 仅交付单执行发布闭环。

## Delivery Plan

1. **环境 registry、tag 规则、secrets 清单与目标部署契约登记**：收集并验证每个 `target_env_id` 的环境类别、生产分组、允许 tag pattern、Woodpecker、registry、K8s、SecretStore、Ingress/TLS、NetworkPolicy、发布锁、回退、evidence store 和必需 Woodpecker secret refs。
2. **部署源与流水线源**：按每个目标环境契约创建/补齐 K8s manifests 或等价发布清单，以及 Woodpecker pipeline；不得使用未接入目标环境或只适配单一 prod 的占位 YAML 标记完成。
3. **迁移与发布门禁**：实现 tag 解析、受支持的 secret resolution（Secret Extension / Configuration Extension / native static fallback）、迁移 Job、schema drift 检查、环境锁、digest 部署、单执行 rollout 和失败阻断；所有状态、锁和 Secret ref 均按 tag 解析出的 `target_env_id` 隔离。
4. **Smoke 与负例**：调用固定租户 runtime smoke，覆盖 HTTP/WS/EduPlus2/resource/ObjectStore/LightRAG/audit；实测未批准/过期/环境错配/缺失必需 secret/Secret 越权/并发发布等拒绝路径。
5. **回退与恢复演练**：验证兼容应用回退、不兼容时维护/停止写入、agent 中断/rollout 失败状态对账。
6. **Evidence 与泄露扫描**：保存 release evidence，运行 secret leakage scan，记录未验证项和后续风险。
7. **G1 收口**：在同构 test K8s 通过完整流水线；若获授权，再按环境 registry 逐个晋级目标生产环境并保留完整证据。未跑某个生产环境前，只能声明其他已验证环境通过，不能宣称所有生产环境上线。

## Success Criteria

- `openspec validate add-g1-woodpecker-k8s-release-baseline --strict` 与 `openspec validate --all --strict` 通过。
- A3.1/A3.2 只有在环境 registry、deployment tag 规则、Woodpecker secrets 清单与目标部署契约已登记并验证后才能勾选；多个生产环境必须逐个标明 verified/unverified。
- Woodpecker 从受信提交构建并推送镜像，部署时使用 digest 而非 mutable tag。
- 迁移/部署/smoke/rollback/evidence 阶段均有脱敏证据；失败时受控回退或进入维护/前向修复状态。
- 每个目标环境 smoke 经该环境真实 Ingress/TLS 路径调用固定租户 runtime smoke；未具备 LightRAG 样本检索、真实 EduPlus2 token、生产 Ingress 或回退演练时，evidence 明确记录对应 `target_env_id` 的未验证项且不得越权宣称该环境 G1 完整通过。
