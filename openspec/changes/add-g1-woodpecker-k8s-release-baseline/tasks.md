# 实施任务

范围以 [proposal](proposal.md)、[design](design.md) 和 `enterprise-g1-woodpecker-k8s-release-baseline` delta spec 为准。本 proposal 只交付 G1 Woodpecker/K8s 发布闭环；固定租户 runtime、resource binding、EduPlus2 demo 和 smoke harness 由 `add-m1-fixed-tenant-runtime-baseline` 提供。未接入目标环境的占位 pipeline、通用 YAML、默认 `prod`、手工覆盖环境变量或只适配单一生产环境的实现不得标记完成；部署目标必须由受保护 deployment tag 解析。

## D0 环境 registry 与多生产环境边界

- [x] D0.1 迁移/配置：定义环境 registry 与 deployment tag schema，覆盖 `env_id`、`env_class`、`prod_group`、允许 tag pattern、Woodpecker 契约、Woodpecker secrets 清单、registry、K8s cluster/namespace、Ingress/TLS、SecretStore/RBAC、NetworkPolicy、数据面 binding、approval policy、release/migration lock、rollback policy 和 evidence prefix；支持多个 `env_class=prod`。Canonical tag 为 `deploy/<env_id>/v<major>.<minor>.<patch>[-rc.<n>|-hotfix.<n>]`。
- [x] D0.2 真实入口：读取并校验每个已登记环境，至少包含 test/pre 以及所有计划内生产环境；流水线必须从受保护 deployment tag 解析 `target_env_id`，不得默认选择生产环境或接受手工覆盖。
- [ ] D0.3 权限/异常测试：覆盖非 deployment tag、tag 格式错误、未保护 tag、未授权 tag、tag moved/reused、不存在环境、歧义 `prod`、缺失必需 secret、超权 secret、跨环境 Secret/namespace/Ingress/evidence path、生产环境未审批、多生产环境其中一个失败等拒绝或隔离路径。
- [x] D0.4 切换证据：保存脱敏环境矩阵、tag 规则、Woodpecker secrets 矩阵、生产环境清单、晋级路径、每个环境 verified/unverified 状态和未验证项；一个生产环境 tag 通过不得替代其他生产环境。

## D1 目标部署契约

- [x] D1.1 迁移/配置：按 deployment tag 可解析出的 `target_env_id` 登记目标 Woodpecker server/agent 版本、agent backend、受保护 tag/ref、审批/Secret 边界、Woodpecker secrets 清单、registry 凭证、K8s namespace、Ingress/TLS、SecretStore/RBAC、NetworkPolicy、发布锁、回退策略和 evidence 存放位置。
- [ ] D1.2 真实入口：用每个目标环境只读/校验命令验证 Woodpecker、registry、K8s、Ingress/TLS、SecretStore、ObjectStore/LightRAG/EduPlus2 test binding 可达或明确缺口。
- [ ] D1.3 权限/异常测试：验证 PR、非 deployment tag、未保护 tag、未批准 tag、过期批准、tag 环境与契约不匹配、缺失必需 secret、跨环境 Secret 越权、超权 DB/K8s/ObjectStore/SecretStore 凭证、registry 凭证缺失或 namespace/RBAC 不匹配被拒绝。
- [x] D1.4 切换证据：按 `target_env_id` 保存脱敏 deployment contract、审批人/窗口、Woodpecker secret name/ref 与权限摘要、Secret ref、evidence store ref 和未验证项；不得保存明文 Secret 或真实 token。
- [x] D1.5 Secret preflight：实现并实测按 `target_env_id` 校验 registry push、K8s deploy、SecretStore、PG migrator、runtime secret refs、smoke credentials、evidence store、tag/approval verify 等必需 secret/ref 的存在性、环境归属、最小权限和轮换状态。

## D2 Woodpecker build/push/digest

- [x] D2.1 迁移/配置：实现 build-once、按 `target_env_id` 的 registry image push、digest resolve、SBOM/scan 摘要和 mutable tag 禁用/限制策略。
- [x] D2.2 真实入口：在受保护且批准的 deployment tag 上运行 pipeline，从 tag 解析 `target_env_id` 和 version，生成 frontend/backend 镜像 digest，并将 digest 写入该环境发布清单。
- [ ] D2.3 权限/异常测试：验证旧构建覆盖、新 tag 指向旧 digest、非 deployment tag、tag moved/reused、未批准 ref/tag、歧义/错误 `target_env_id`、缺失/错误 registry push secret、agent 中断和 registry 推送失败不会进入部署阶段。
- [x] D2.4 切换证据：记录原始 tag、tag object SHA、tag creator、`target_env_id`、version、源码 SHA、upstream SHA、企业包版本、镜像 digest、build run ID、扫描摘要和失败证据。

## D3 migration/deploy/smoke

- [x] D3.1 迁移/配置：实现独立 migration/bootstrap Job 或等价步骤，包含按 `target_env_id` 隔离的 release lock、migration lock、schema_history drift 检查、幂等 bootstrap 和失败阻断。
- [ ] D3.2 真实入口：部署 by digest 到选定 `target_env_id` 的目标 K8s，经该环境真实 Ingress/TLS 调用 `add-m1-fixed-tenant-runtime-baseline` 提供的 runtime smoke，覆盖 HTTP/WS/EduPlus2/resource/ObjectStore/LightRAG/audit 路径。
- [ ] D3.3 权限/异常测试：验证迁移失败、rollout 超时、readiness fail、smoke fail、LightRAG unavailable、ObjectStore 权限不足、同环境并发发布竞争、跨环境 lock 混用和 release lock 丢失均被拒绝或进入受控恢复。
- [x] D3.4 切换证据：按 `target_env_id` 归档 migration/deploy/smoke evidence，包含 exit code、schema version、release id、run id、request id 短 hash、错误 code、未验证项和脱敏摘要。

## D4 rollback/maintenance

- [x] D4.1 迁移/配置：按环境定义兼容应用回退、不兼容回退维护/停止写入、前向修复和成套恢复决策门禁。
- [ ] D4.2 真实入口：按 `target_env_id` 实测 rollout/smoke 失败后的兼容回退并重跑 smoke；若无安全回退版本，实测该环境进入维护或停止写入状态。
- [ ] D4.3 权限/异常测试：覆盖 agent 中断、回退镜像缺失、schema 不兼容、跨环境 ObjectStore/LightRAG binding 不匹配和重复 rollback 请求。
- [x] D4.4 切换证据：记录 `target_env_id`、失败原因、回退步骤、结果、批准人、仍需跟进项和是否需要前向修复。

## D5 evidence、脱敏与复用边界

- [x] D5.1 迁移/配置：定义按 `target_env_id` 分区的 release evidence 目录/对象结构、retention、访问权限和 future M2/M3 复用边界。
- [ ] D5.2 真实入口：为每个已验证环境生成完整 release evidence 并运行 secret leakage scan，确认不包含 `.secrets` 明文、JWT、`dt_token`、client secret、模型 key、Woodpecker secret 明文、Kubeconfig 明文或用户隐私。
- [ ] D5.3 权限/异常测试：验证普通 tenant_admin、伪造 `ops.*` scope、错误 evidence path、跨环境 release id 或不同生产环境之间无法越权查看/覆盖发布证据。
- [x] D5.4 切换证据：按环境记录 evidence path、scan 摘要、未验证项和 G1 结论边界；未跑某个真实生产环境前，不能宣称该环境生产上线或所有生产环境已完成。

## 验证与归档准备

- [x] V.1 运行 `openspec validate add-g1-woodpecker-k8s-release-baseline --strict`。
- [x] V.2 运行 `openspec validate --all --strict`。
- [x] V.3 完成 upstream mergeability review，记录 core patch 清单、通用 seam 目的、风险和回归命令。
- [ ] V.4 获得用户对实施完成、证据和归档的明确确认后，再按 OpenSpec 归档；未合并/未验证项不得勾选或归档。
