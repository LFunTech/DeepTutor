# 设计说明

## Context

本 change 专注 G1 发布流水线。它不建模租户 runtime，而是把已有/待完成的 enterprise runtime 制品通过目标 Woodpecker 和 Kubernetes 环境发布、验证和留证。租户数量只影响 smoke scope 和 runtime 配置，不决定 CI/K8s 拓扑。部署环境可能包含 local/test/pre/staging 和多个不同生产环境；流水线必须从受保护 deployment tag 解析 `target_env_id`，并按环境隔离 Secret、锁、namespace、Ingress/TLS、审批和 evidence。


## 决策 0：环境 registry 是发布契约的一部分

G1 流水线维护一个环境 registry，而不是把“prod”写死为唯一目标。每个环境条目至少包含：

| 字段 | 含义 | 约束 |
| --- | --- | --- |
| `env_id` | 稳定环境 ID，如 `test-cn`, `prod-cn-east`, `prod-overseas-a` | pipeline run 必须显式传入；禁止默认 prod |
| `env_class` | `local`/`test`/`pre`/`staging`/`prod` | 生产类环境必须额外审批 |
| `prod_group` | 多生产环境的业务/地域/客户分组 | 可为空；非空时 evidence 按组聚合但不合并验证结论 |
| `tag_pattern` | 允许触发该环境的 deployment tag pattern | 必须包含精确 `env_id`，禁止 `prod` 默认别名 |
| Woodpecker 契约 | server/agent/backend/protected ref/tag 规则 | 可按环境不同 |
| K8s 契约 | cluster/namespace/Ingress/TLS/SecretStore/RBAC/NetworkPolicy | 必须按环境隔离 |
| 数据面绑定 | PG/ObjectStore/LightRAG/EduPlus2 test credentials ref | 只记录 ref；禁止跨环境复用生产 Secret |
| 发布控制 | approval policy、release lock、migration lock、rollback policy | 生产环境逐环境审批和锁定 |
| evidence | evidence store/prefix/retention | 必须包含 `env_id`，避免不同生产环境互相覆盖 |

流水线一次只部署一个 `target_env_id`。如需发布到多个生产环境，必须执行多个可追溯 run，或由编排层显式展开为逐环境 run；任何环境失败不得被其他环境成功覆盖。

### Deployment tag 规则

环境选择必须来自 Git tag，而不是手工输入环境变量或默认值。Canonical tag 格式：

```text
deploy/<env_id>/v<major>.<minor>.<patch>[-rc.<n>|-hotfix.<n>]
```

解析规则：

- `env_id` 正则：`[a-z][a-z0-9-]{1,40}`，必须精确匹配环境 registry 中的 `env_id`。
- `version` 正则：`v[0-9]+\.[0-9]+\.[0-9]+(-(rc|hotfix)\.[0-9]+)?`。
- 完整 canonical 正则：`^deploy/(?P<env_id>[a-z][a-z0-9-]{1,40})/(?P<version>v[0-9]+\.[0-9]+\.[0-9]+(-(rc|hotfix)\.[0-9]+)?)$`。
- tag 必须是受保护 tag；生产环境 tag 还必须满足审批策略，可选要求 annotated/signed tag 或等价签名校验。
- `prod`、`production`、`latest`、`stable` 等别名不得作为部署目标；多个生产环境必须各自打精确 tag。
- pipeline 只从 tag 解析 `target_env_id`，不得接受手工覆盖；如 tag 与手工变量不一致，以拒绝为准，不做覆盖。
- tag object SHA、commit SHA、创建者、创建时间、审批记录和解析出的 `target_env_id` 必须进入 evidence。
- 已用于成功或失败发布的 deployment tag 不得移动、复用到其他 commit 或改指向其他环境；检测到 tag moved/reused 必须 fail closed。

示例：

```text
deploy/test-cn/v1.4.0-rc.1
deploy/pre-cn/v1.4.0-rc.2
deploy/prod-cn-east/v1.4.0
deploy/prod-overseas-a/v1.4.0-hotfix.1
```

如需同一 commit 发布到多个生产环境，必须分别创建多个 tag，例如 `deploy/prod-cn-east/v1.4.0` 与 `deploy/prod-overseas-a/v1.4.0`，并分别执行审批、部署、smoke、回退和 evidence 归档。


## 决策 0A：Woodpecker secrets 契约

Woodpecker secrets 必须按 `target_env_id` 隔离登记。Secret Extension 模式下，pipeline 使用稳定逻辑 secret 名，extension 根据 `target_env_id` 返回环境值；native/static 模式下，secret 名称使用稳定前缀，建议将 `env_id` 转为大写并把 `-` 替换为 `_` 得到 `<ENV_KEY>`，例如 `prod-cn-east` → `PROD_CN_EAST`。Proposal、pipeline 日志和 evidence 只能记录 secret name/ref、用途、权限摘要、短 hash 和校验结果，不得记录明文。


### Secret resolution 实现模式

根据 Woodpecker 官方文档，pipeline 可通过 `from_secret` 把已命名的 Woodpecker secret 注入 step 环境或 plugin settings；tag 名可通过 `CI_COMMIT_TAG` 获得，配置解析阶段支持字符串替换和字符串操作；Secret Extension 可在 pipeline 触发时从外部服务返回 secrets；Configuration Extension 可在配置解析前生成或改写 pipeline config。

本判断基于 2026-09-24 查阅的 Woodpecker 3.18.x 官方文档：

- Environment variables：`CI_COMMIT_TAG`/`CI_PIPELINE_EVENT` 以及配置解析期 string substitution。
- Workflow syntax：`when.event: tag`、`ref` 过滤和 `evaluate` 条件。
- Secrets：`from_secret` 将已命名 secret 注入 step 环境或 plugin settings，且参数表达式在 pipeline 启动前预处理。
- Secret Extension：pipeline 触发时扩展返回 `{ name, value, images?, events? }` secrets，`name` 与 pipeline config 中的 `from_secret` 匹配。
- Configuration Extension：pipeline 触发时扩展可返回新的官方 YAML 配置文件。

因此，单流水线适配所有环境的实现模式按优先级如下：

1. **推荐：Secret Extension + 稳定逻辑 secret 名**
   - Pipeline YAML 中只引用稳定逻辑名，例如 `REGISTRY_PUSH_TOKEN`、`KUBE_DEPLOY_TOKEN`、`PG_MIGRATOR_DSN`、`EVIDENCE_STORE_WRITE_TOKEN`。
   - Secret Extension 根据 pipeline 的 tag/ref、commit、repo 和环境 registry 解析 `target_env_id`，返回该环境对应的 secret 值。
   - 优点：一套 pipeline steps，不需要在 YAML 中枚举所有环境 secret 名；Woodpecker 仍按 secrets 机制注入与遮蔽。

2. **可选：Configuration Extension 生成静态 `from_secret` 配置**
   - Configuration Extension 根据 tag/env registry 生成官方 YAML，把 `from_secret` 渲染为静态名称，如 `DT_PROD_CN_EAST_REGISTRY_PUSH_TOKEN`。
   - 优点：生成后的配置仍使用 native `from_secret`；缺点：配置扩展本身成为高信任组件。

3. **native-only 兜底：按环境静态步骤/secret + `when.ref`**
   - 在同一个 pipeline 文件中为每个环境显式声明静态 `from_secret` 名称，并用 `when: event: tag` + `ref: refs/tags/deploy/<env_id>/**` 限定步骤。
   - 优点：不依赖扩展；缺点：环境多时配置膨胀，不是真正的动态 secret 名。

不支持/不得依赖的模式：在 shell step 中先计算 `ENV_KEY`，再期望 Woodpecker 动态解析 `from_secret: DT_${ENV_KEY}_...`。`from_secret` 注入发生在 step 运行前，shell 中计算出的变量不能反向改变已解析的 secret 绑定。除非目标 Woodpecker 版本经实测证明配置预处理支持该用法，否则不得作为 G1 完成依据。

### 必需 secrets / refs

| 类别 | 建议 secret/ref 名称 | 用途 | 权限边界 | 备注 |
| --- | --- | --- | --- | --- |
| Registry push | `DT_<ENV_KEY>_REGISTRY_PUSH_TOKEN`、可选 `DT_<ENV_KEY>_REGISTRY_USERNAME` | 构建后推送 frontend/backend 镜像并解析 digest | 仅允许 push 到该环境/项目镜像仓库；不得拥有删除仓库或跨环境 push 权限 | 若所有环境共用 registry，也必须用环境级 repo/path 或 policy 隔离 |
| K8s deploy | `DT_<ENV_KEY>_KUBE_DEPLOY_TOKEN` 或 `DT_<ENV_KEY>_KUBECONFIG`，可选 `DT_<ENV_KEY>_KUBE_CA_CERT` | apply/patch Deployment、Job、Service、Ingress、ConfigMap、Secret ref、NetworkPolicy 等 | namespace-scoped；只允许目标 namespace 和所需 API verbs；生产环境不得复用 test token | 优先短 TTL service account token/OIDC；若用 kubeconfig，必须脱敏并限制 context |
| SecretStore / ExternalSecret | `DT_<ENV_KEY>_SECRETSTORE_AUTH` 或 `DT_<ENV_KEY>_SECRETSTORE_ROLE` | 创建/更新 ExternalSecret、SecretProviderClass 或等价 secret ref 绑定 | 只允许读取/绑定该环境允许的 secret path/ref；不得读取明文应用密钥到日志 | 若由集群内 operator 拉取 secret，Woodpecker 只应写 ref，不应接触明文 |
| DB migration | `DT_<ENV_KEY>_PG_MIGRATOR_DSN` 或 `DT_<ENV_KEY>_PG_MIGRATOR_SECRET_REF` | 迁移 Job/初始化步骤执行 schema migration、固定 tenant bootstrap | 当前单库单用户模式下可与 runtime DB DSN 指向同一目标库 owner；该用户不得是 superuser/createdb/createrole/bypassrls，且不得跨环境 DB | 推荐让 Job 从 SecretStore 拉取 DSN，Woodpecker 只持有 ref；拆分 migrator/runtime 角色不是 G1 test-cn 前置条件 |
| Runtime secret refs | `DT_<ENV_KEY>_APP_DB_SECRET_REF`、`DT_<ENV_KEY>_OBJECTSTORE_SECRET_REF`、`DT_<ENV_KEY>_LIGHTRAG_API_SECRET_REF`、`DT_<ENV_KEY>_MODEL_PROFILE_SECRET_REF`、`DT_<ENV_KEY>_EDUPLUS2_CLIENT_SECRET_REF` | 将 runtime 所需 secret ref 写入 manifest/ConfigMap/ExternalSecret | 仅引用该环境 secret；Woodpecker 不读取明文 | 这些是 ref，不是 secret 明文；evidence 记录 ref kind/短 hash |
| Smoke credentials | `DT_<ENV_KEY>_SMOKE_EDUPLUS2_CLIENT_SECRET` 或 `DT_<ENV_KEY>_SMOKE_TOKEN_ISSUER_SECRET`、可选 `DT_<ENV_KEY>_SMOKE_TEST_USER_SECRET` | 获取测试 user JWT / `dt_token`、运行 HTTP/WS/EduPlus2/resource smoke | 只用于该环境 smoke；短 TTL；最小测试用户权限 | 禁止长期保存 JWT 或 `dt_token`；运行后只记录短 hash/request id |
| Evidence store | `DT_<ENV_KEY>_EVIDENCE_STORE_WRITE_TOKEN`，可选 `DT_<ENV_KEY>_EVIDENCE_STORE_READ_TOKEN` | 上传 release evidence、smoke 摘要、rollback 记录、scan 结果 | 写入限定 env/release prefix；读取权限分离 | evidence path 必须包含 `target_env_id` |
| Tag / approval verify | `DT_VCS_TAG_VERIFY_TOKEN` 或环境级 `DT_<ENV_KEY>_VCS_TAG_VERIFY_TOKEN` | 查询受保护 tag、tag object SHA、审批记录和 tag creator | 只读仓库/tag/approval 元数据 | 若 Woodpecker 原生提供可信元数据，可不单独配置，但必须记录信任来源 |

### 条件性 secrets

| 类别 | 建议 secret/ref 名称 | 触发条件 | 约束 |
| --- | --- | --- | --- |
| Image signing / attestation | `DT_IMAGE_SIGNING_KEY` 或 OIDC/keyless issuer 配置 | 启用 cosign/签名/attestation | 优先 keyless/OIDC；私钥不得进入日志/evidence |
| SBOM / vulnerability scanner | `DT_SCANNER_TOKEN` 或环境级 scanner token | 私有扫描服务需要 token | 只允许上传/查询本项目扫描结果 |
| Notification / change ticket | `DT_RELEASE_NOTIFY_TOKEN`、`DT_CHANGE_TICKET_TOKEN` | 发布需通知或关联审批系统 | 不得拥有发布权限，只能写通知/状态 |
| Registry read mirror | `DT_<ENV_KEY>_REGISTRY_READ_TOKEN` | smoke/rollback 需要验证镜像可拉取 | 只读；不得替代 push token |

### 禁止作为 Woodpecker secret 保存

- `.secrets` 目录内容、完整生产配置文件、用户隐私或业务正文。
- 长期有效 JWT、DeepTutor `dt_token`、真实用户密码。
- 跨环境通用的生产 Kubeconfig、DB superuser DSN、ObjectStore root key、SecretStore root token。
- 模型 API key、EduPlus2 client secret、LightRAG API key 的明文，除非仅作为环境 SecretStore 中的 ref；Woodpecker 不应读取这些明文。

Pipeline 启动时必须执行 secret preflight：确认当前 tag 解析出的 `target_env_id` 所需 secret/ref 全部存在、secret resolution 模式受支持、作用域匹配、权限摘要符合最小权限、未使用其他环境 secret，并把脱敏结果写入 evidence。缺失、过期、跨环境、权限过大、命名不匹配或依赖未验证的动态 `from_secret` 解析时必须在读取生产数据或部署前 fail closed。

## 设计前提：目标部署契约优先

A3/G1 的任何 pipeline 或 manifest 都必须从环境 registry 中选定的目标部署契约出发。每个 `target_env_id` 的契约至少包含：

- Woodpecker server/agent 版本；
- agent backend 与可用插件/runner 权限；
- 受保护 ref、deployment tag 命名、审批门禁和过期策略；
- Woodpecker secrets 清单、Secret 边界、registry 凭证、镜像仓库和签名/扫描策略；
- K8s namespace、Ingress/TLS、allowed origins、SecretStore/RBAC、NetworkPolicy；
- release lock、migration lock、回退策略、evidence 存放位置和环境级 retention/访问边界。

没有环境 registry 或目标契约时，只能实现契约校验、smoke/evidence 工具和待接入说明，不能用通用 YAML、默认 prod、或凭“单租户”推断出的 pipeline 当作 A3 完成证据。

## 发布闭环

```text
protected deployment tag + approval
        │
        ▼
Woodpecker pipeline
        ├── parse tag -> target_env_id
        ├── verify env registry / contract / secrets / permissions / secret refs
        ├── build frontend/backend once
        ├── push image and resolve immutable digest
        ├── migration/bootstrap Job with locks
        ├── deploy by digest to target_env_id K8s
        ├── run fixed-tenant runtime smoke via Ingress/TLS
        ├── rollback or maintenance/forward-fix on failure
        └── archive redacted release evidence
```

## 决策 1：流水线复用 runtime smoke，不重新定义租户规则

`add-m1-fixed-tenant-runtime-baseline` 提供 readiness、resource binding、EduPlus2 exchange、HTTP/WS、ObjectStore、LightRAG、audit 和负例 smoke。G1 流水线只负责在目标环境通过真实 Ingress/TLS 调用这些 smoke，并把 run ID、exit code、request id、短 hash、错误 code 和 evidence path 归档。

流水线不得把固定租户 smoke 直接声明为生产发布成功；只有 build/push/migration/deploy/smoke/rollback/evidence 全链路通过并留证，才能形成 G1 发布结论。

## 决策 2：构建一次，部署 digest

Pipeline MUST 从受信提交构建一次，并将 frontend/backend 镜像推送到目标环境登记的 registry。部署源 MUST 使用 immutable digest，不得使用 mutable tag。Evidence MUST 记录 `target_env_id`、环境类别、源码 SHA、upstream SHA、企业包版本、镜像 digest、SBOM/scan 摘要和 build run ID。

旧构建覆盖、新 tag 指向旧 digest、tag 格式错误、tag 未保护/未授权、tag moved/reused、缺失/歧义 `target_env_id`、环境不匹配、缺失必需 secret、权限过大 secret、跨环境 Secret ref、未批准 ref 或过期批准都必须拒绝。

Woodpecker 构建把前端 bundle、Python dependency tree 和 runtime OS/base layer 拆成同一 tag run 内的并行 artifact-image steps。各 step 使用语义化命名和 Kaniko 构建受信提交中的固定 Dockerfile/target，并推送不可变中间镜像：`frontend-builder` 产出 `frontend-build:<tag>`，`python-base` 产出 `python-deps:<tag>`（使用 `--skip-unused-stages` 避免构建无关 stage），`Dockerfile.protected-runtime-base` 产出 `runtime-base:<tag>`。最终 `Dockerfile.protected-runtime` 只从这些 artifact images 复制 `/app/web/.next/standalone`、`/app/web/.next/static`、`/app/web/public`、`/usr/local` Python 依赖、enterprise extension source 和 runtime base，再装配 runtime image、推送并解析 digest；不在最终阶段执行 apt、npm、pip、rustup 或 cargo。runtime 进程配置与启动脚本作为 `deploy/docker-runtime/` 下的受版本控制文件复制进入镜像，避免 Kaniko 在复制大体积 artifact 之后为多个 heredoc/sed/chmod 小步骤反复做全文件系统 snapshot。这样仍满足“同一受信提交构建一次并部署 digest”的契约，同时允许前端、Python 依赖和 runtime base 真正并行，并避免 workspace artifact 在 Woodpecker command 容器与 Kaniko context 间复制造成的不一致。CI 中 apt 使用 Tsinghua Debian mirror，npm/PyPI/Cargo 使用目标网络可达的内部 mirror；PyPI 必须指向 PEP 503 simple endpoint（例如 `.../pypi/simple/`）。

## 决策 3：迁移和 rollout 由发布步骤编排

应用 PG migration、固定租户 bootstrap、默认 policy/profile 初始化由独立 Job 或等价发布步骤执行：

1. 按 `target_env_id` 获取 release lock 和 migration lock；
2. 校验目标环境、当前版本、schema_history drift、pending release 和环境数据面绑定；
3. plan/apply/verify，并将 schema version 和 release id 写入 evidence；
4. 应用 Deployment 启动时只读取/校验版本，不抢跑迁移；
5. 失败阻断 rollout，不允许 `|| true` 或逐 Pod 抢跑。

LightRAG 内部 PG/HugeGraph 迁移不属于 DeepTutor 应用 Job。Release evidence 只引用 LightRAG 部署记录、API 契约版本、workspace/index-version binding 和 readiness。

## 决策 4：执行拓扑显式登记；多副本必须有一致性门禁

M1/G1 不把 backend executor schema 锁死为 1。Deployment/rollout 需要显式策略：

- `backend_executor_replicas=1` 走单副本发布：发布前停止接新 turn 或进入维护/排空，确认旧执行者终止后启动新执行者；
- `backend_executor_replicas>1` 或 HPA 走企业多副本发布：必须声明 `rolling-replicated-agent`、Redis runtime coordination、共享 turn lease、fencing token、共享事件/命令流和 worker-lost recovery；
- `replicas: 1` 不能单独证明无重叠，pipeline 必须有排空/锁/状态确认；
- 多副本不能只靠 K8s replicas/HPA 证明安全；缺 Redis 协调、共享 PG/ObjectStore/SecretStore/LightRAG binding 或一致性 evidence 时 fail closed。
- 程序运行态必须和部署契约一致：Redis coordination 模式下企业组合根不得继续获取单执行者 `ExecutorLease`，否则 K8s 多 Pod 会被应用层 advisory lock 退化为单实例；启动恢复也只能处理 Redis 已过期的 turn lease，不能把其他 Pod 正在执行的 nonterminal turn 批量标为 `worker_lost`。

Frontend 或无执行权组件可独立滚动，但不能因此把 backend execution 改为无门禁滚动。HPA 通过原生 Kubernetes YAML overlay 应用，不引入 Helm。

## 决策 5：回退是应用/配置/依赖组合回退，不是数据库回滚

回退流程按 `target_env_id` 的发布清单组合执行：镜像 digest、非敏感配置、schema 兼容性、ObjectStore binding、LightRAG binding、feature gate 必须一致。应用回退不自动降库；若 migration 不兼容旧应用，则不能回退旧应用继续写入，应进入维护模式、前向修复或按已演练的成套恢复方案执行。

回退成功必须重跑 smoke 并保存 evidence；失败发布本身仍保留失败记录，不能被通知成功覆盖。

## 决策 6：Evidence 脱敏且可追溯

建议每次 G1 候选生成一个 evidence 目录或对象：

```text
release-evidence/
  <target-env-id>/
    <release-id>/
    deployment-contract.json   # 脱敏目标环境契约摘要，含 env_id/env_class/prod_group/secrets 摘要
    manifest.yaml              # 脱敏发布清单
    build.json                 # 源码 SHA、镜像 digest、SBOM/scan 摘要
    migration.json             # plan/apply/verify、schema version、drift 结果
    deploy.json                # rollout、probe、release lock、单执行状态
    smoke.json                 # run id、cases、request id、脱敏摘要
    rollback.json              # 未执行则写明原因；执行则记录步骤与结果
    upstream-compat.md         # core patch 清单、upstream merge 风险、回归命令
    unresolved.md              # 未验证项、阻断项、环境前提
```

证据可进入受控对象存储、CI artifact 或审计系统，但不得包含明文 Secret/token。Evidence path 必须包含 `target_env_id`，并记录原始 tag、tag object SHA、commit SHA 和解析结果；多个生产环境的验证结论不得合并成一个无环境标识的“prod passed”。Pipeline 必须对新增/修改文档、脚本、manifest、pipeline 与 evidence 运行 secret leakage scan。
