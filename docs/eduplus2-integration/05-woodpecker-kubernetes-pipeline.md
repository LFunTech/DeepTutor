# 05. Woodpecker 构建与 Kubernetes 部署流水线

## 决策与实施归属

2026-09-13 补充：**流水线开发是 M1/A3 的必交付子环节，从 A1 起并行建设，A3/G1 前完成真实交付验收；M2/M3 与官方更新复用，不增加第四阶段或第八个业务工作包。** A1/A2 尚未完成时可以部署集成环境，但不能借流水线提前发布半替换生产版本。

本文是待实施设计，不是可直接运行的 YAML 或已部署声明。需求与勾选状态以 [流水线 spec](../../openspec/changes/replace-rollout-with-three-production-stages/specs/kubernetes-delivery-pipeline/spec.md)、[tasks 第 3 组](../../openspec/changes/replace-rollout-with-three-production-stages/tasks.md) 为准，总门禁见 [02](02-rollout-testing-and-migration.md)。本轮不注册 CI 仓库、不写入 Secret、不打 tag、不触发流水线或操作集群。

## 当前仓库事实与差距

| 已检查的事实 | 实施影响 |
| --- | --- |
| `origin=https://github.com/LFunTech/DeepTutor.git`；`upstream=https://github.com/HKUDS/DeepTutor.git` | 接入的是 DeepTutor fork，不是 `LFunTech/edu-plus-2`；Woodpecker 中是否已激活尚未验证 |
| 仓库未发现 `.woodpecker` 配置 | 需要新增流程、脚本、环境契约与发布验收，不能认为既有 GitHub Actions 已提供 K8s 部署 |
| `.github/workflows/tests.yml` 已有 Python、架构、前端及浏览器检查 | 复用真实命令与测试，不另写只有 build 的简化质量门禁；新增 PG/S3 契约及阶段回归 |
| `.github/workflows/docker-release.yml` 发布合并镜像，目标为官方 `ghcr.io/hkuds/deeptutor` | fork 的生产镜像必须进入自有 registry；避免两个 CI 覆盖同一 tag 或误发官方命名空间 |
| `Dockerfile` 的 `production` 同时启动 FastAPI 和 Next.js；入口强制 JSON 配置并清理部分环境变量 | 需适配 [04](04-kubernetes-postgresql-architecture.md) 的独立前后端启动与 PG/Secret 配置契约，不能只往现镜像塞环境变量 |
| `Dockerfile.runner` 是执行沙箱，不是 CI agent | 首发启用沙箱时纳入镜像清单及安全验收，不能混用两种 runner 的凭证/权限 |

保留上游 GitHub Actions 的通用测试/发布资料，不要求为新增 Woodpecker 删除它们。自有 K8s 发布以本流程为唯一写入口；上游 workflow 在 fork 的启用、权限与镜像目标需显式收敛，不允许旁路自动部署。

## A3 内的开发顺序

| 子环节 | 启动与依赖 | 交付证据 |
| --- | --- | --- |
| 接入与契约 | 与 A1 同时开始 | 本仓库激活、版本/agent backend、受保护 ref、环境、镜像和权限契约 |
| CI 与生产镜像 | A1 开始，随 A1/A2 适配 | 质量检查、PG/S3 集成、前后端镜像、digest 及依赖清单 |
| 集成环境自动交付 | 第一批真实功能可用后持续执行 | 从提交到测试 K8s 的构建、迁移、发布与业务 smoke |
| 生产发布与故障演练 | A1/A2 完成，进入 A3 总验收 | 受控晋级、发布互斥、迁移失败、回退及 G1 证据 |
| 后续阶段回归 | B1/B2/C1/C2 与 upstream 合并 | 同一流水线增加已交付范围门禁，不复制租户流水线 |

文档前移至 05，任务按 A3 包内执行顺序编排：3.1–3.4 接入/环境/权限/CI，3.5–3.9 镜像/制品/网络/迁移/部署，3.10–3.14 功能与故障验收，3.15 放行、3.16 发布确认。A3 准备仍从 A1 并行，不等 A1/A2 全做完才开发流水线；失败处理、安全和回退与对应步骤一起开发，不延后至运营后台阶段。

## 接入参数与外部准备

以下值由实施接入任务确认并留在环境登记中，不能从其他仓库或个人电脑配置推断；缺失时阻止相应环境发布，而不是静默用测试值。

| 参数 | 必须确认的内容 |
| --- | --- |
| Woodpecker | server URL、实际 server/agent 版本、仓库标识、配置读取路径、agent backend/标签与可用构建资源 |
| 源码与授权 | 受保护集成分支、发布 ref 规则、触发人/批准人、服务端授权机制及 workflow 修改审查 |
| Registry | 自有命名空间、push/pull 权限、保留周期、目标节点架构，是否确需 amd64/arm64 |
| 环境 | 测试/生产 cluster 标识、namespace、域名、Ingress/TLS、PG/S3/Secret 引用及网络连通；预发布按实际环境启用 |
| 发布工具 | 固定版本的构建器、Woodpecker CLI、kubectl/Kustomize 与插件；用目标版本校验语法和权限 |
| 验收与通知 | 专用测试账号/租户、受控模型凭证和调用预算、门禁记录存放位置、批准记录和通知渠道 |

现有 EduPlus 的 Woodpecker 地址、tag 约定只能作为接入线索，不直接视为本仓库已配置。若不满足实际版本功能，调整实现或单独审批升级；本项目流水线开发不隐含升级共享 Woodpecker 服务。

## 目标文件与职责

以下为拟新增交付物，路径在实施时创建；**当前只调整方案，不生成假可执行文件**。

| 目标路径 | 职责 |
| --- | --- |
| `.woodpecker/verify.yaml` | PR/可信提交的质量与契约检查；无部署权限 |
| `.woodpecker/publish.yaml` | 可信来源构建、扫描、推送镜像，生成不可变发布清单 |
| `.woodpecker/deploy-test.yaml` | 测试环境迁移、部署、rollout、smoke 与证据 |
| `.woodpecker/deploy-prod.yaml` | 校验批准及已验收清单后晋级生产，包含失败处理 |
| `scripts/ci/` | 校验来源/发布清单、构建、迁移编排、部署、smoke、回退及证据归档的可测试命令 |
| `deploy/kubernetes/base/`、`deploy/kubernetes/overlays/` | Kustomize 基础清单与环境差异，显式独立前后端/可选 worker、迁移 Job、服务、探针及运行模式 |
| `deploy/images/` | 复用现有 Dockerfile 构建段，独立企业 Dockerfile/启动器装配 core + 企业包，前后端独立启动；不改上游镜像入口，启用时另构建 sandbox runner |
| `extensions/enterprise/` | 独立 Python 包/企业 UI、版本锁与迁移，实现业务适配而非复制上游；布局和 hook 边界见 [13](13-deployment-and-upstream-sync.md) |
| 检索服务清单与锁定记录 | 企业 RAG Gateway/文档 worker、原版固定 workspace LightRAG Server 镜像 digest、PG 图后端/权限迁移及受控 binding，不新增独立业务发布阶段 |

默认选择 **Woodpecker → Kustomize/kubectl → Kubernetes**，不把新建 Argo CD/Flux/GitOps 平台作为 M1 前置。若目标环境已有强制发布控制器，应复用其唯一部署入口并重新登记契约，不能两个系统同时写同一工作负载。

Woodpecker 的不同 workflow 不共享工作目录；同次构建依赖用 `depends_on`，跨 workflow 的镜像/发布清单须经 registry 或独立 CI 制品存储传递，不能靠本地文件路径。条件依赖和并发功能以目标版本为准。[官方 Workflows 文档](https://woodpecker-ci.org/docs/usage/workflows)

## 构建、测试与制品契约

```text
PR ──→ 无生产凭证的质量/契约检查
可信提交 ──→ 同 SHA 必需检查 → 构建/扫描 → push → 不可变发布清单
          → 测试环境锁/来源校验 → 迁移 Job → 部署 → rollout → 业务 smoke → 证据
已验收清单 + 生产批准 ──→ 同 digest 晋级 → 生产迁移/部署/smoke → 发布记录
```

1. 基础检查沿用当前 `ruff check .`、`ruff format --check .`、`lint-imports`、`python scripts/check_architecture.py`、`pytest -q tests deeptutor/learning/tests`，前端使用 `npm ci --legacy-peer-deps` 与 `npm run check` 及适用浏览器测试。依赖安装按现有 workflow 和后续真实变更同步，不能仅复制命令而缺少依赖/fixture。
2. 新增真实 PG/S3 服务集成、版本化迁移、RLS/所有权、对象失败补偿，以及已交付阶段的 HTTP/WS/管理页面回归。独立本地 SQLite fixture 可继续测试，但不能代替生产后端测试。PR 使用临时依赖与非生产测试数据，不连接生产资源。
3. 构建 core + 企业包组合后端、前端/企业 UI 及已启用执行组件；纳入企业 RAG Gateway/文档 worker 和锁定 digest 的 LightRAG Server（无源码变更时复用已核验镜像，不必自建引擎镜像）。验证扩展入口真实装配与 core/企业包/Server/图后端兼容，适配受控 PG/Secret 配置和非 root/scratch 权限；运行期不下载未锁定的软件包或写本地 settings 作为生产权威。不得通过换镜像入口绕回 SQLite。验证同一镜像在不同环境读取各自配置，避免前端固化测试 URL。
4. 固定基础镜像/构建工具/插件版本，记录解析出的 digest 与依赖清单，生成 SBOM、漏洞和凭证泄露扫描报告。阻断级别与例外批准登记；缓存按锁文件/架构/信任域区分，不缓存业务数据/凭证，不允许不可信 PR 污染可信发布缓存。
5. 使用独立受限构建环境；默认不将宿主 Docker socket、特权模式或集群管理员权限交给普通 PR。BuildKit/Buildx 的实际 backend 与多架构能力在目标 agent 验证，不将本机能 build 当作验收。
6. 发布清单额外绑定企业包/依赖锁、通用核心补丁、LightRAG API/镜像/存储版本及 workspace binding 格式；所有组合同一轮验收。一次构建按 `image@sha256:…` 晋级；人类可读 tag 仅作索引，不部署 `latest`，不在生产按同 SHA 重建另一个镜像。清单至少含源码/upstream SHA、构建 ID、各镜像 digest/平台、清单配置版本、schema/对象格式兼容范围、启用能力和运行模式。
7. 清单采用签名或等效防篡改、只读可信发布记录，并与测试结果和批准绑定；部署校验来源和摘要。制品存储与租户业务 S3 隔离；清单缺失、被篡改或不匹配时失败，不按 tag 猜 digest。跨环境复制镜像后也要核对 digest。

## 触发、批准和凭证边界

| 来源 | 默认行为 | 权限边界 |
| --- | --- | --- |
| PR、fork、非受保护来源 | 检查/受限构建，不推正式镜像、不部署 | 无 registry 发布、K8s、生产 PG/S3 或模型凭证 |
| 受保护集成分支的可信提交 | 同 SHA 检查通过后发布候选镜像，自动部署测试 | 只授候选仓库和测试环境所需权限 |
| 正式晋级请求 | 指向已经通过测试的发布清单，经授权批准后部署生产 | 生产独立凭证；固定环境白名单和目标 digest |
| 重试/回退 | 复用原清单、校验当前状态，回退作为显式批准动作 | 同样来源校验、环境锁、兼容检查、smoke 和审计 |

实现可采用目标版本支持的 `deployment` 事件发起晋级；`manual` 或 tag 不是“自动获得生产批准”。Woodpecker 的 `branch` 过滤不应用于 tag，因此 tag 还必须验证受保护 ref、提交来源与制品证据，不能仅以 `branch` 阻止任意 tag 部署。[官方条件与事件语法](https://woodpecker-ci.org/docs/usage/workflow-syntax)

**批准是服务端信任边界，不是在 PR 可改的 YAML 中写一句判断。** 普通开发者不能通过改 workflow、修改环境参数或重放旧批准获取生产凭证。优先对接既有受控晋级/凭证发放机制，绑定 actor、environment、digest、有效期和单次使用；若现有 Woodpecker/代码托管权限不能保证此边界，生产步骤放入仅发布负责人可修改/触发的受保护交付仓库。此时仍消费同一套清单和脚本，不另造应用版本。实现前必须选定并负向验证，未验证不得配置生产凭证。

Secret 仅通过 Secret 引用注入所需步骤，限定事件/插件，PR 不开启 Secret；不能认为日志遮罩能阻止恶意代码取走凭证。[官方 Secrets 文档](https://woodpecker-ci.org/docs/usage/secrets)

- CI agent 身份、应用身份、迁移身份、部署身份相互分离；CI 不需要租户业务数据查询权限，生产 DB 凭证在迁移 Job 内引用，不在普通构建步骤展开。
- 环境级短期凭证优先；确需 kubeconfig 时使用专用 namespace 受限身份，不上传个人 kubeconfig 或 `cluster-admin`。显式校验 API server/cluster、namespace、registry、域名，不接受任意 shell/values 参数。
- 创建 namespace、RBAC、PG/S3、Secret 及准入策略属于受控一次性基础设施准备；普通发布不重建/删除它们。不批量 `get secrets`，日志/制品不得包含解码凭证。
- 能创建 Job/修改 Deployment 的身份可能间接使用 namespace 的 Secret/ServiceAccount，因此还需限定可挂载 Secret、可使用身份、镜像和工作负载范围，配合环境隔离与准入控制，不能只说“namespace RBAC 即绝对安全”。

## 迁移、部署与发布互斥

1. **预检与互斥**：取得以 cluster/namespace/应用为范围的环境发布锁；普通发布与回退共用，校验当前版本/期望前序版本。旧构建迟到、重复触发或其他入口更新后须拒绝覆盖，不能把队列串行当作防旧版本覆盖。锁持有覆盖迁移至 smoke/恢复确认；运行中任务不能因新提交被自动取消。
2. **失败恢复**：发布锁与状态不能只存在 CI 进程；执行方失联时，先核对仍运行的迁移 Job/rollout，禁止仅凭超时启动第二次发布。用原发布 ID/迁移历史对账，确认安全后恢复或显式解锁。Woodpecker 并发限制可以辅助排队，但不能替代数据库迁移锁与实际发布状态校验。
3. **迁移**：复用企业包内 A1/A2 的版本化迁移实现，区分应用 schema 与 LightRAG 索引/图/数据库权限及低权运行初始化；由匹配候选版本的独立 Job 执行，独立 DB 角色、数据库锁、超时及历史记录，schema 已到目标版本时幂等跳过。必须核实并控制锁定 LightRAG 版本的启动建表/迁移行为，不能让原版 Server 用高权账号自行抢跑迁移。失败立即停止部署并保存脱敏证据，不能逐 Pod 跑迁移、靠 `|| true` 放行或对非幂等外部副作用盲目重试。
4. **兼容窗口**：可兼容旧应用的扩展迁移可先执行；不兼容变更必须先停接新 turn、排空所有执行者并进入批准的维护窗口，再迁移。迁移后的应用/对象格式兼容范围决定能否回退，不以“Job 成功”推断旧实例能继续写。
5. **应用发布**：按固定清单和 digest 更新配置/前后端/启用的执行组件，检查配置引用、readiness、rollout 超时及实际镜像。只管理本应用声明资源，不使用广泛 prune、删除 PVC/bucket 或重装依赖。
6. **单执行模式**：必须先排空并确认旧执行进程终止，再启新执行者，显式无 surge/重叠的更新顺序和单 worker 限制，接受维护中断。`replicas: 1` 本身不能证明发布期没有两个执行者；frontend 与无执行权的组件独立判断。
7. **多执行者模式**：实际滚动更新/扩缩容导致竞争执行或目标要求 HA 时，先校验本版本/拓扑适用的 G-H 证据；未通过拒绝该发布配置，不因流水线能改 replicas 就视为安全。

## 业务 smoke、失败处理与回退

smoke 通过真实 Ingress/TLS 路径验证企业启动器下的前端、认证、HTTP、`/api/v1/ws` 建连及一次完整 turn、历史读取、文件上传/授权下载、托管 KB 经企业服务导入→LightRAG ready→检索→授权引用及隔离资源删除，以及首发已启用能力。Server 仅可达、原版连接探测通过或导入 HTTP 2xx 均不能替代完整链路。使用专用受限账号/数据、唯一 run ID 和受控模型调用预算；PR 的确定性测试不冒充目标环境真实 smoke。

破坏性故障演练、两个租户串租负例、撤权和全量回归主要在同构测试环境执行；生产使用经批准的隔离测试资源，不修改真实用户数据。清理只通过授权路径删除本 run 创建的资源，失败保留定位信息，不做全 bucket/namespace 清理。后续 B1 加真实外部登录/撤权，B2 加双租户及租户管理，C1/C2 加运营权限/执行一致性；适用时增加 G-H 演练证据。

| 失败位置 | 处理与禁止项 |
| --- | --- |
| 检查/构建/扫描/推送/清单校验 | 失败并阻断下游，不允许缺失必需检查被当作成功 |
| 授权/环境不匹配/旧版本覆盖 | 在取生产凭证和写入前拒绝，保留安全审计 |
| 迁移 Job 失败或超时 | 停止新应用部署，检查实际迁移状态；不自动降库或删除对象 |
| rollout 或 smoke 失败 | 标记发布失败；锁内判断上一应用与当前 schema/对象/策略兼容，再受控回退完整镜像/非敏感配置组合并重跑 smoke |
| 无安全应用回退版本 | 保持受控维护/停止相关写入，人工批准前向修复或经演练的 PG/S3 成套恢复，明确数据损失窗口 |
| CI/agent 中断、通知或证据存储失败 | 对账实际部署状态，告警并补存证据；不能据此声称成功或盲目重跑迁移，关键发布证据未持久化不得验收 |

应用回退不等于数据库回滚；恢复旧应用不能还原已撤销的权限或退回旧 SQLite/file。通知应覆盖成功/失败，且不覆盖原失败状态；只有恢复验证通过才记录“已恢复”，失败发布本身仍留失败记录。

## G1 必需的流水线验收证据

验收分发布前放行与发布后完成确认：测试环境、恢复/安全及适用 G-H 先通过并取得批准，再执行首次生产交付；生产隔离 smoke 与记录完成后才确认 M1 并开放普通业务流量。首次上线不以尚不存在的生产成功记录作为前置，后续发布仍须保留完整历史。

1. 目标 Woodpecker/agent 实跑可信提交 → 测试 K8s → 业务 smoke，完整记录源码、镜像、迁移与门禁；文档/YAML lint 不替代真实执行。
2. 同一 core/企业包/前端/LightRAG 兼容制品组合经批准晋级目标生产环境并通过 smoke；生产接入未完成只能认定集成子环节通过，不能宣称 M1 已上线。
3. PR/非受保护分支、伪造 tag、未批准/过期批准、修改环境/digest、Secret 越权均被拒绝；故障注入使用测试环境/测试凭证。
4. 迁移失败阻断部署，重复迁移与发布幂等；两条发布竞争、旧构建迟到、agent 中断、rollout/smoke 失败和兼容应用回退均实测留证。
5. 单执行发布无执行者重叠并符合接受的中断/恢复语义；启用多执行者/HA 时有效 G-H 已通过。
6. 发布记录可从构建追溯到批准人、目标环境、upstream/自有 SHA、清单版本、全部 digest、schema/对象格式、运行模式、门禁/回退证据；保留周期与访问权限已确认。
7. 现有与新增必要检查均为强制，失败/缺失/未执行不放行。完整故障/容量门禁可引用受保护、适用版本/拓扑的演练记录，但不得用过期记录替代当前受影响范围回归。

实现时用与目标 server 匹配的工具校验 `.woodpecker/`，再进行实际事件/权限/集群联调；配置语法验证只证明可解析，不证明可部署。[官方 Linter 文档](https://woodpecker-ci.org/docs/usage/linter)
