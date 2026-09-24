## Purpose

定义 DeepTutor G1 Woodpecker/K8s 发布流水线基线：以环境 registry 和目标部署契约为边界，从受信提交构建一次、推送镜像、锁定 digest，通过受保护 deployment tag 解析 `target_env_id`，再执行迁移、部署到对应 Kubernetes、调用固定租户 runtime smoke、归档 release evidence，并在失败时受控回退或进入维护/前向修复状态。该能力支持多个不同生产环境逐一验收，不定义固定租户业务规则，不交付 B2 多租户/TMS、C1/C2 OMS 或 H 高可用。

## ADDED Requirements


### Requirement: 发布流水线必须维护环境 registry 并从 deployment tag 解析目标环境

系统 SHALL 维护部署环境 registry，并在每次 Woodpecker/K8s 发布时从受保护 deployment tag 解析 `target_env_id`。Canonical tag 格式 MUST 为 `deploy/<env_id>/v<major>.<minor>.<patch>[-rc.<n>|-hotfix.<n>]`，其中 `env_id` MUST 精确匹配环境 registry 中的稳定 `env_id`，且完整 tag MUST 匹配 `^deploy/(?P<env_id>[a-z][a-z0-9-]{1,40})/(?P<version>v[0-9]+\.[0-9]+\.[0-9]+(-(rc|hotfix)\.[0-9]+)?)$`。每个环境条目 MUST 包含稳定 `env_id`、`env_class`、可选 `prod_group`、允许 tag pattern、Woodpecker 契约、Woodpecker secrets 清单、registry、K8s cluster/namespace、Ingress/TLS、SecretStore/RBAC、NetworkPolicy、数据面 binding、approval policy、release/migration lock、rollback policy 和 evidence store/prefix。系统 MUST 支持多个 `env_class=prod` 的生产环境，并逐环境打 tag、审批、部署、smoke 和留证。Pipeline MUST NOT 使用默认生产环境、手工覆盖目标环境、歧义 `prod` 别名或跨环境 Secret/namespace/evidence。

#### Scenario: 多个生产环境登记
- **WHEN** 存在 `prod-cn-east`、`prod-overseas-a` 或其他多个生产环境
- **THEN** 每个生产环境都有独立 `target_env_id`、允许 tag pattern、审批策略、Secret ref、namespace/Ingress、release lock、rollback policy 和 evidence prefix
- **AND** 一个生产环境通过 smoke 不得自动推导其他生产环境通过

#### Scenario: 从 tag 解析目标环境
- **WHEN** pipeline 由 tag `deploy/prod-cn-east/v1.4.0` 触发
- **THEN** 系统解析出 `target_env_id=prod-cn-east` 和 `version=v1.4.0`，并要求该环境存在于 registry、tag 受保护、审批策略满足后才读取该环境 Secret 或部署

#### Scenario: 未指定、格式错误或歧义目标环境
- **WHEN** pipeline run 没有 deployment tag、tag 不匹配 canonical 格式、tag 中环境不存在、或使用歧义值如 `deploy/prod/v1.4.0` 且 registry 中存在多个生产环境
- **THEN** pipeline 在读取生产 Secret 或部署前 fail closed，并输出脱敏错误 code

#### Scenario: 跨环境资源混用
- **WHEN** 发布清单、Secret ref、registry credential、namespace、Ingress host、ObjectStore/LightRAG binding、release lock 或 evidence path 属于另一个环境
- **THEN** pipeline 拒绝继续执行，不允许把一个环境的生产凭证或发布状态用于另一个环境

#### Scenario: tag 被移动或复用
- **WHEN** deployment tag 已经产生过 release evidence，随后 tag object SHA、commit SHA、version 或解析出的 `target_env_id` 与历史 evidence 不一致
- **THEN** pipeline MUST fail closed，不允许用移动或复用的 tag 覆盖既有环境发布记录



### Requirement: Secret resolution 必须使用 Woodpecker 官方支持模式

系统 SHALL 使用 Woodpecker 官方支持的机制解析环境相关 secrets。推荐模式是 Secret Extension：pipeline 使用稳定逻辑 secret 名，Secret Extension 根据受保护 deployment tag、pipeline 元数据和环境 registry 返回对应 `target_env_id` 的 secret 值。可选模式是 Configuration Extension 在配置解析前生成含静态 `from_secret` 名称的 pipeline config。native-only 兜底 MAY 使用同一 pipeline 文件中按环境静态声明的 `from_secret` 名称和 `when.ref` 过滤。系统 MUST NOT 依赖 step shell 中动态计算出的 `ENV_KEY` 去改变 `from_secret` 的 secret 名称，除非该 Woodpecker 版本和配置经过目标环境实测并记录证据。

#### Scenario: Secret Extension 提供环境 secret
- **WHEN** deployment tag 解析出 `target_env_id=prod-cn-east`
- **THEN** Secret Extension 基于 tag、pipeline 元数据和环境 registry 返回稳定逻辑名对应的 secret 值，例如 `REGISTRY_PUSH_TOKEN`、`KUBE_DEPLOY_TOKEN`、`PG_MIGRATOR_DSN` 和 `EVIDENCE_STORE_WRITE_TOKEN`
- **AND** pipeline evidence 记录 extension 信任来源、请求签名校验结果、`target_env_id`、secret name/ref 与权限摘要，不记录 secret 明文

#### Scenario: Configuration Extension 生成静态 secret 引用
- **WHEN** 使用 Configuration Extension 适配多环境
- **THEN** 生成后的 Woodpecker YAML 中 `from_secret` MUST 是目标环境的静态 secret 名称或稳定逻辑名称；生成过程必须记录 config extension 版本、输入 tag、输出摘要和审批/签名校验

#### Scenario: 禁止 shell 动态拼接 from_secret
- **WHEN** pipeline 只在 shell 命令中计算 `ENV_KEY=PROD_CN_EAST`，但 YAML 中试图依赖 `from_secret: DT_${ENV_KEY}_REGISTRY_PUSH_TOKEN` 或等价未验证动态名称
- **THEN** 该 pipeline 不得作为 G1 完成证据；必须改为 Secret Extension、Configuration Extension 或静态 `from_secret` + `when.ref` 模式

### Requirement: Woodpecker secrets 必须按环境显式声明且最小权限

系统 SHALL 为每个 `target_env_id` 声明 Woodpecker secrets/ref 清单和 secret resolution 模式，并在 pipeline 读取生产数据、推送镜像、访问 K8s 或执行迁移前完成 secret preflight。清单 MUST 至少覆盖 registry push、K8s deploy、SecretStore/ExternalSecret、DB migration、runtime secret refs、smoke credentials、evidence store 和 tag/approval verification；启用镜像签名、SBOM/漏洞扫描、通知或变更单系统时，还 MUST 声明对应条件性 secrets。所有 secret MUST 按环境隔离、最小权限、可轮换、可审计；evidence 只能记录 secret resolution 模式、secret name/ref、用途、权限摘要、短 hash 和校验结果，不得记录明文。

#### Scenario: 必需 secret 清单完整
- **WHEN** 环境 `prod-cn-east` 被登记为发布目标
- **THEN** deployment contract 至少声明 `DT_PROD_CN_EAST_REGISTRY_PUSH_TOKEN`、`DT_PROD_CN_EAST_KUBE_DEPLOY_TOKEN` 或 `DT_PROD_CN_EAST_KUBECONFIG`、`DT_PROD_CN_EAST_SECRETSTORE_AUTH` 或等价 role、`DT_PROD_CN_EAST_PG_MIGRATOR_DSN` 或 `DT_PROD_CN_EAST_PG_MIGRATOR_SECRET_REF`、runtime secret refs、smoke credential、`DT_PROD_CN_EAST_EVIDENCE_STORE_WRITE_TOKEN`、以及 tag/approval verify token 或可信元数据来源
- **AND** 每个 secret/ref 都记录 secret resolution 模式、用途、权限边界、环境作用域、轮换/过期策略和脱敏 evidence 字段

#### Scenario: Woodpecker 不读取 runtime 明文 secret
- **WHEN** runtime 需要模型 key、EduPlus2 client secret、LightRAG API key、ObjectStore access key 或应用 DB 密码
- **THEN** Woodpecker 只写入或校验 SecretStore/ExternalSecret/ref 绑定，不把这些 runtime 明文 secret 输出到 manifest、日志、evidence 或 pipeline 环境变量

#### Scenario: secret 缺失、过期或越权
- **WHEN** 必需 secret 缺失、过期、命名环境与 tag 解析出的 `target_env_id` 不一致、权限覆盖其他环境、或是 DB superuser/ObjectStore root/SecretStore root 等超权凭证
- **THEN** pipeline MUST 在读取生产数据、推送镜像、访问 K8s 或执行迁移前 fail closed，并记录脱敏错误 code

#### Scenario: 禁止长期 token 和明文配置
- **WHEN** Woodpecker secrets 或 release evidence 中出现 `.secrets` 内容、长期 JWT、DeepTutor `dt_token`、真实用户密码、完整生产配置、Kubeconfig 明文转储、模型 key 明文或用户隐私
- **THEN** secret leakage scan MUST 失败，发布不得继续，泄露项必须从 artifact/evidence 中移除并轮换受影响 secret

### Requirement: 发布流水线必须先登记目标部署契约

系统 SHALL 在新增或运行 Woodpecker pipeline、K8s manifests 或等价发布流程前，为 deployment tag 可解析出的每个 `target_env_id` 登记目标部署契约。契约 MUST 包含 Woodpecker server/agent 版本、agent backend、受保护 ref、审批/Secret 边界、Woodpecker secrets 清单、registry、K8s namespace、Ingress/TLS、SecretStore/RBAC、NetworkPolicy、发布锁、回退策略和 evidence 存放位置。部署和流水线拓扑 MUST 来自该环境契约，不得从“单租户/多租户”状态或通用 prod 假设推导。

#### Scenario: 目标部署契约未登记
- **WHEN** A3/G1 准备新增 K8s 部署源或 Woodpecker pipeline
- **THEN** 系统要求先登记并验证环境 registry 与该 `target_env_id` 的部署契约；未登记或未验证这些契约时，A3/D0/D1/D2 不得标记完成

#### Scenario: 目标部署契约脱敏输出
- **WHEN** pipeline 或维护命令输出 deployment contract 摘要
- **THEN** 输出 `env_id`、`env_class`、`prod_group`、server/agent/backend、protected ref、Woodpecker secret name/ref 与权限摘要、Secret ref kind、registry ref、namespace、Ingress/TLS host hash、release lock 和 evidence store ref；不得输出 registry credential、Kubeconfig、JWT、client secret、模型 key 或完整 host/token 明文

### Requirement: Woodpecker 必须完成构建、推送、digest 锁定和部署门禁

系统 SHALL 提供 Woodpecker pipeline 或等价自动交付流程，从受保护 deployment tag 对应的受信提交构建一次、按 tag 解析出的 `target_env_id` 的 registry 推送镜像、解析 immutable digest，并将 digest 写入该环境发布清单。PR、非 deployment tag、未保护 tag、未批准 tag、过期批准、环境不匹配、缺失/歧义 `target_env_id`、tag moved/reused、缺失必需 secret、超权 secret、旧构建覆盖、新 tag 指向旧 digest、跨环境 Secret 越权 MUST 被拒绝。

#### Scenario: 受信提交生成可部署 digest
- **WHEN** G1 pipeline 在受保护 deployment tag 上运行
- **THEN** pipeline 从 tag 解析 `target_env_id` 和 version，完成 build/push/digest 阶段，所有阶段记录原始 tag、tag object SHA、`target_env_id`、exit code、digest、source SHA、upstream SHA、build run id 和脱敏摘要

#### Scenario: 未授权构建或制品异常
- **WHEN** pipeline 来自 PR、非 deployment tag、未保护 tag、未批准 tag、过期批准、错误环境、歧义 `target_env_id`、tag moved/reused、registry 推送失败或 digest 与受信源码不匹配
- **THEN** pipeline 停止在部署前，记录脱敏失败证据，不更新任何目标 K8s 发布清单

### Requirement: 迁移和部署必须由发布步骤受控执行

系统 SHALL 使用独立 migration/bootstrap Job 或等价发布步骤执行应用 PG schema migration、固定租户 bootstrap、默认 policy/profile 初始化和版本验证。Deployment 普通 startup/lifespan MUST 只校验版本和 readiness，不得在 Pod 启动时抢跑非幂等迁移。部署 MUST 使用 image digest，而非 mutable tag；schema_history、release lock 和 migration lock MUST 按 `target_env_id` 校验和留证。

#### Scenario: 重复执行迁移 Job
- **WHEN** 同一 G1 候选版本的 migration Job 在同一 `target_env_id` 被重复触发
- **THEN** Job 在该环境的 release lock、migration lock 和 schema_history 校验下幂等完成或明确报告已应用，不重复创建 tenant/user/policy，不覆盖已有 Secret 或密码

#### Scenario: 迁移漂移或失败
- **WHEN** schema_history 漂移、迁移失败、权限不足、锁竞争或超时发生
- **THEN** pipeline 阻断部署并保存脱敏失败证据，不能继续 rollout、不能自动降库、不能用 `|| true` 放行

### Requirement: K8s 发布必须显式声明执行拓扑并校验多副本一致性

系统 SHALL 为每个 `target_env_id` 显式登记 backend executor 拓扑。`backend_executor_replicas` MUST 支持大于 1 的企业高并发配置，但多副本或 HPA 配置 MUST 同时声明 `rolling-replicated-agent` rollout、Redis turn coordination、共享 turn lease、fencing token、共享事件/命令流和 worker-lost recovery 证据；否则 pipeline MUST fail closed。程序运行态 MUST 与该拓扑一致：Redis coordination 模式不得继续使用单执行者全局 `ExecutorLease` 阻断其他 Pod，启动恢复不得批量失败其他 Pod 的 nonterminal turn。单副本环境 MAY 使用排空后重建的 rollout。Frontend 或无执行权组件 MAY 独立滚动，但不能替代 backend executor 一致性门禁。

#### Scenario: 单副本 rollout
- **WHEN** pipeline 向 `backend_executor_replicas=1` 的某个 `target_env_id` 部署 backend 新版本
- **THEN** pipeline 先获取该环境 release lock，停止接新 turn 或排空，确认旧执行者无 running/waiting turn 或已进入受控恢复，再启动新执行者并记录不重叠证据

#### Scenario: 多副本或 HPA rollout
- **WHEN** 部署配置请求 `backend_executor_replicas>1`、HPA 或其他会产生多个 backend executor 的拓扑
- **THEN** 环境契约必须声明 Redis runtime coordination、共享 PG/ObjectStore/SecretStore/LightRAG binding、turn lease/fencing/event replay/command delivery/worker recovery 一致性控制和对应 evidence ref
- **AND** pipeline 渲染对应 replicas/HPA 原生 Kubernetes YAML，并将 replicas、autoscaling 和 coordination 摘要写入 release evidence

#### Scenario: 多副本缺少一致性控制
- **WHEN** 部署配置请求多个 backend executor，但运行时协调仍为 memory、本地事件流、缺少 Redis secret/ref、缺少 fencing/worker recovery 或未登记一致性 evidence
- **THEN** pipeline MUST 在调用 `kubectl` 前 fail closed，不允许通过 HPA、replicas patch 或手工 kubectl 绕过一致性门禁

### Requirement: G1 smoke 必须调用固定租户 runtime smoke 并经真实 Ingress/TLS 留证

系统 SHALL 经选定 `target_env_id` 的真实 Ingress/TLS 路径调用 `add-m1-fixed-tenant-runtime-baseline` 提供的 runtime smoke，覆盖 frontend/backend 可达、auth/status、EduPlus2 user JWT exchange、HTTP bearer 调用、WebSocket `/api/v1/ws` 认证与 `start_turn`、`auth_refresh`、session history/owner guard、ObjectStore 写读删或授权下载、`start_turn` 资源引用、audit query/export、必要负例和脱敏检查。目标环境具备 LightRAG 样本语料时，smoke MUST 覆盖 KB 导入/ready/检索/授权引用；若缺失该依赖，G1 MUST 记录为阻断或未完成项，不得声明完整生产上线。

#### Scenario: 目标环境 smoke 通过
- **WHEN** deployment rollout 在某个 `target_env_id` 完成且 smoke 持有该环境有效测试凭证
- **THEN** pipeline 经该环境 Ingress/TLS 运行 runtime smoke，记录 `target_env_id`、run id、exit code、request id 短 hash、case 摘要和 evidence path

#### Scenario: 权限和依赖负例
- **WHEN** smoke 使用过期/撤销 token、跨 owner session、伪造 tenant、ObjectStore 权限不足、LightRAG unavailable 或未授权 KB
- **THEN** 系统返回稳定脱敏错误并 fail closed，不泄露资源存在性、token、Secret 或其他用户内容；pipeline 按预期负例结果归档证据

### Requirement: 回退必须按兼容发布组合执行并留证

系统 SHALL 将回退视为某个 `target_env_id` 内应用镜像、非敏感配置、schema 兼容性、ObjectStore binding、LightRAG binding 和 feature gate 的组合操作。应用回退不得假设数据库可自动降级；无安全回退版本时 MUST 进入维护/停止写入，并要求人工批准前向修复或成套恢复。

#### Scenario: 兼容应用回退
- **WHEN** 某个 `target_env_id` 的新版本 rollout 或 smoke 失败且上一应用版本兼容当前 schema/object/binding
- **THEN** pipeline 使用该环境上一 release 的镜像 digest 和配置 ref 回退，重跑 smoke，并在 evidence 中记录失败原因、回退步骤、结果和仍需跟进项

#### Scenario: 不兼容回退
- **WHEN** 当前迁移或对象格式不允许旧应用安全写入
- **THEN** 系统保持维护状态或停止相关写入，不自动降库，不回退到 SQLite/local 文件权威，并记录前向修复或成套恢复决策需求

### Requirement: Release evidence 必须可追溯且脱敏

系统 SHALL 为每个 deployment tag / `target_env_id` 的每个 G1 候选和发布保存 release evidence，至少包含原始 tag、tag object SHA、tag creator、deployment contract 摘要、`env_id`、`env_class`、`prod_group`、Woodpecker secret preflight 脱敏摘要、源码 SHA、upstream 兼容审查、镜像 digest、schema version、迁移结果、部署状态、smoke run ID、审批/操作者、Secret ref、错误/回退记录、未验证项和后续风险。Evidence MUST 脱敏，禁止保存 JWT、DeepTutor `dt_token`、client secret、模型 key、完整 profile、用户隐私或原始业务正文。

#### Scenario: 生成 release evidence
- **WHEN** pipeline 完成或失败
- **THEN** evidence 可用于从发布结果追溯到源码、制品、迁移、`target_env_id`、smoke、审批和回退状态，且 secret leakage scan 对 evidence 和日志无命中

#### Scenario: 未验证项存在
- **WHEN** LightRAG 样本检索、生产 Ingress、真实 EduPlus2 token、回退演练或 upstream 兼容检查未执行
- **THEN** evidence 明确记录对应 `target_env_id` 的未验证原因和影响；G1 结论不得越权声明这些范围已通过，也不得把其他生产环境结果合并替代

### Requirement: 发布流水线必须可复用且不得硬编码租户拓扑

系统 SHALL 将 Woodpecker/K8s 发布流水线设计为 G1 release gate，可被后续 M2/M3 和 upstream 更新复用或兼容演进。Pipeline MAY 接收固定租户 smoke scope，但 SHALL NOT 把 Woodpecker agent、K8s namespace、Ingress/TLS、SecretStore、release lock、evidence store 或 production target 硬编码为“单租户专用”或单一 `prod`。

#### Scenario: 后续多租户或 OMS 发布复用
- **WHEN** 后续 proposal 需要发布多租户/TMS/OMS 能力
- **THEN** 它可以复用本发布基线的目标部署契约、digest、migration/deploy/smoke/rollback/evidence 框架，并只替换业务 smoke scope 和权限边界

#### Scenario: 尝试由租户模式推导发布拓扑
- **WHEN** 文档、pipeline 或 manifest 以“单租户/多租户”或单一 `prod` 默认值为依据推导 Woodpecker/K8s 拓扑
- **THEN** 该制品不得作为 A3/G1 完成证据，必须回到环境 registry 与目标部署契约登记验证步骤
