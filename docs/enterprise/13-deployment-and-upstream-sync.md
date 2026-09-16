# 13. 企业扩展包、应用外壳与官方 upstream 维护方案

> 发布顺序统一采用 [02](02-rollout-testing-and-migration.md) 的三个阶段；M1 `/tms` 保留固定租户既有管理功能，B2 完成多租户 TMS，C1/C2 交付 `/oms` 统一运营界面。下面 Git 命令仅为后续维护示例，本次不执行分支、提交、推送或合并操作。

## 目标

DeepTutor 官方更新后，企业版本仍能以可验证的核心补丁和扩展包组合持续升级。采用“配置优先 → 现有注入/插件 → 必要通用 hook/旁路收敛”，不承诺全产品零改源码，也不重写上游教学与检索算法。生产 PG/S3、无状态 backend、完整权限和三阶段门禁不变。

2026-09-13 最新批准范围：取消本仓库所有 local/SQLite 运行模式，默认 Web/CLI/SDK/后台必须使用 PG。通用 PG 下沉 core、企业专属策略保持包外；[完整迁移设计](../../openspec/changes/migrate-all-sqlite-state-to-postgresql/design.md)当前待实施，首切片的 local 兼容仅为历史基线。

当前 repo 已有以下 remote，不能重复执行下面的初始化示例：

```text
origin   https://github.com/LFunTech/DeepTutor.git
upstream https://github.com/HKUDS/DeepTutor.git
```

## 推荐 Git 拓扑

```text
upstream/main        # 官方 HKUDS/DeepTutor
origin/main          # 自有 fork 主分支
origin/eduplus2      # EduPlus2 长期适配分支
```

仅尚未配置 fork/upstream 的仓库才参考以下初始化示例，本仓库不执行：

```bash
git remote rename origin upstream
git remote add origin git@github.com:<your-org-or-user>/DeepTutor.git
git fetch upstream
git fetch origin
git checkout -b eduplus2 upstream/main
git push -u origin eduplus2
```

如果当前仓库还需要保留官方 origin，也可以另加：

```bash
git remote add fork git@github.com:<your-org-or-user>/DeepTutor.git
```

但长期推荐 `upstream=官方`、`origin=自有 fork`。

## 官方更新合并流程

```bash
git fetch upstream
git checkout eduplus2
git merge upstream/main
# 解决冲突
# 运行测试
# push 到 origin/eduplus2
```

团队协作建议使用 merge，不建议对共享长期分支频繁 rebase。

## 启用冲突复用

```bash
git config rerere.enabled true
```

这样同类冲突后续可以复用解决记录。

## 配置、扩展和外壳的选择

| 手段 | 本方案用途 | 边界与决策 |
| --- | --- | --- |
| 配置/部署文件 | 已支持模型与引擎配置、K8s/CI、Secret 注入、独立镜像入口 | 优先使用；拟定 PG/S3 配置不是现有功能，启动写出 JSON 不能替代运行时 Store |
| 外部 Tool/Capability | 新业务工具、能力和受控工具装配 | 使用现有协议；`deeptutor.extensions` 自动加载不覆盖同名内置能力，不能拿它替代全站基础设施 |
| 应用容器/启动器 | 通过 `set_application_container()`、Store 注入和已核验的生命周期装配企业服务 | 有效复用点，但 direct SQLite/file、默认单例和后台枚举仍需逐项收敛 |
| 薄代理/SSO/iframe | 流量入口、工作台导航、安全传输 | 不能改变原生全局 admin、内部持久化或资源授权，不作为企业化完整实现 |
| 厚外壳重建应用层 | 自管全部 API/WS/存储/UI，只复用部分 AI 能力 | 技术上可保持上游文件不变，但成本/兼容面大；不作为本方案默认实现 |
| 必要通用核心补丁 | 补缺失 provider/scope/授权/lifecycle、收敛直连后端与前端权限接口 | 采用；范围由真实调用审计决定，不承诺固定文件数/行数，不夹带 EduPlus2 业务 |

禁止以大规模 monkey patch、`sitecustomize`/`sys.modules` 替换、导入顺序碰运气、请求内更改进程环境或 root 路径实现生产隔离；禁止把挂载 S3 模拟 POSIX、JSON/PG 异步同步双写当作 Store 替换。测试注入不等于批准以上生产机制。

## 通用 PG 与独立企业包交付布局（目标）

在同一受控 fork 中维护 core 通用 PG 与独立可构建企业包；不要求新增另一个仓库。企业首切片包已存在，下面的 core 下沉及其余模块仍是待实施布局，以具体 change 证据区分状态：

```text
deeptutor/persistence/postgres/      # 通用连接/事务/scope、PG Store、身份与统一迁移

extensions/enterprise/
  pyproject.toml                    # 发行包 deeptutor-enterprise，锁定兼容 core
  src/deeptutor_enterprise/
    bootstrap.py                    # 自有启动器/组合根、配置与版本预检
    api/                            # EduPlus2、TMS/OMS 专属路由与企业应用装配
    integrations/eduplus2/           # Handoff、JWT、profile、权限、sync、webhook
    identity/                       # 可信 tenant/user scope 与授权适配
    stores/                         # 消费 core PG；企业资源/ObjectStore、Secret 适配
    resources/                      # 文件/KB/源文、配额及生命周期
    rag/                            # LightRAG 服务 binding/API client、授权路由与文档协调；无图 driver
    jobs/                           # 持久任务、补偿、调度/协调适配
    migrations/                     # 企业新增迁移适配；共用应用 PG 历史，旧 schema 1 不改写
  web/                              # 企业 UI 模块/运营界面，构建方式按前端契约落实

deploy/images/                      # 独立企业启动入口，不覆盖上游 Dockerfile
部署清单、流水线、scripts/ci/         # 沿用 05 的受控交付职责
```

LightRAG 的检索 PG/HugeGraph 初始化、schema/ACL 迁移及内部恢复脚本归其 fork 或独立部署制品，不放入上述企业 Python 包；DeepTutor 交付流水线只按受控制品调用对应维护 Job。

不再把具体 EduPlus2 集成实现默认放到 `deeptutor/integrations/eduplus2/`。本目录其他文档中的 `deeptutor_enterprise.*` 均指上述包；Python 包位置不决定对外 HTTP/WS 路径；企业专属管理前缀按 [11](11-api-and-entrypoints.md) 统一为 `/api/v1/tms/*`、`/api/v1/oms/*`，通用业务 API、`/api/v1/ws` 与 `/api/v1/eduplus2/*` 保持原契约。企业包“独立”指依赖/构建和职责边界，不强制每个模块部署成独立微服务。

## 核心通用 seam 与企业责任

| 核心位置/边界 | 必要通用变更或复用 | 企业包实现及必须核验的调用 |
| --- | --- | --- |
| `app/container.py`、`app/facade.py`、turn lifecycle | 默认容器与入口必须装配通用 PG、可信身份/provider 和生命周期 | 企业组合复用相同 PG/scope，附加资源/治理策略；不存在 local SQLite 备用容器 |
| `services/session/` 及直连调用方 | 收敛 `get_sqlite_session_store()` 等旁路为协议/provider | 会话、题库、学习、后台读写全覆盖，不仅首次聊天 |
| auth/current user/scope | provider-aware 身份与通用 scope/权限边界，缺失拒绝 | 本地固定租户、EduPlus2 映射、停用/撤权；学校 admin 不映射全局 admin |
| grants/settings/identity/memory/notebook | 补齐 Store provider，清除写文件的真实生产调用 | PG/RLS/owner/version、Secret 引用，管理保存到 runtime 生效 |
| KB/附件/生成物/source reader | 资源/ObjectStore/scratch/provider seam | PG metadata + S3 生命周期、授权引用下载，输出持久化前不报成功 |
| RAG factory/config/client | 保留已选 `lightrag-server` 的图检索/context/references 语义，补可注入 binding/client provider | 从 PG/Secret 解析连接与可信短期调用上下文，不能依赖旧 `kb_config.json` |
| API factory/router/lifespan | 显式注册/选择受保护路由与启动迁移策略；避免同路由注册顺序覆盖 | 企业 API 装配与版本/依赖校验；原未适配入口不能旁路暴露 |
| 原管理页面/导航/前端权限契约 | 复用现有组件，企业入口统一 `/tms`、`/oms`；接通必要租户标识与资源/角色/能力字段，不改权限 key | M1 固定租户 `/tms`，B2 多租户适配，C1/C2 `/oms`；路由/菜单/API client/Ingress/smoke 同步，新前端不重复实现治理后端 |
| cron/partners/MCP/exec/后台协调 | provider、可信执行 scope、重新授权和恢复接口 | 首发必需能力与所有 worker 路径；复用现有 coordinator 后重新验收 G-H |

“最小必要改动”指满足全部已启用行为的最小完整接口与调用改造，不是只改工厂几个文件。A1 必须登记入口→服务→Store/资源→后台调用矩阵，明确复用/扩展/补丁归属；A2/B2 随链路补齐，最终以无生产旁路和行为回归验收。

默认与企业启动器均须在开始业务前装配 PG/provider、路由、可信权限及生命周期并验证 schema/版本。缺少配置/hook、未知 backend 或绕过企业策略时拒绝启动，不降为 local admin/SQLite/PocketBase。原 local/SQLite 模式取消，完整默认能力在 PG 上运行而非缩成企业 chat-only 白名单。

只读镜像配置/ConfigMap 可保留；凭证通过 Secret provider 注入内存。若上游库确需非敏感临时配置，只允许由权威 Store 生成的可丢弃只读投影，不从该文件反向同步或接受管理写入。用户可变设置、KB 连接及业务数据不得把文件投影当权威。

企业包与检索 fork 的补丁责任还须遵守 [06 责任矩阵](06-postgresql-native-store-plan.md#跨系统责任矩阵)：KB 索引解析/S3 派生物、文档级取消、检索 profile/内部限额/用量与状态接口由 LightRAG 或其明确装配的组件实现；企业包只实现业务协调、授权、映射和对账，不消费服务内部队列。K8s 实例预开/回收留在独立部署运维流程。联合制品锁定上述契约及配置版本；upstream 更新复验六类边界，不因服务缺 API 把内部能力迁回 DeepTutor。

## 通用扩展点与 upstream 升级

优先贡献无 EduPlus2 耦合的 Auth/Scope/Store/ObjectStore/RAG binding/application factory hook、直接后端调用收敛及契约测试；不等待官方接受 PR 才交付。已有合适 seam 不重复新建一套框架。

核心补丁逐项记录用途、真实调用覆盖、上游基线与测试；企业包声明兼容版本，构建锁定依赖。每次升级验证 core + 企业包 + 前端 + 已选 RAG/存储/必要队列和解析组件组合，检查新增 capabilities/tools 是否引入旧写路径。无需改动时直接升级依赖，有接口变化时更新通用补丁和适配层；不承诺无条件跟随 latest。

## Kubernetes 生产部署模式

推荐生产模式：

```text
DeepTutor core + 企业包 backend Deployment（自有组合入口；多执行者前过 G-H）
DeepTutor frontend Deployment
PostgreSQL primary database
S3-compatible Object Storage for files/artifacts
企业 RagGateway/文档 worker → LightRAG Server API（用户 fork，固定 workspace 实例池）
  LightRAG 内部依赖：检索 PostgreSQL（KV/vector/doc_status）
                    HugeGraph（HugeGraphStorage 图后端）
                    实际必需队列/解析组件
  检索存储凭证与迁移/恢复由 LightRAG 部署运维持有，DeepTutor 不直连
DeepTutor 自身协调的 Redis/NATS/Queue 为可选实现
Kubernetes Secret / External Secrets for secrets
```

关键要求：

1. backend Pod 不保存 source-of-truth 状态。
2. sessions/messages/turn_events/grants/webhook/audit 进入 PostgreSQL。
3. 按 [07](07-resource-isolation.md) 将 KB 原文/解析文件/服务副本、附件、持久工作区文件、生成/导出物、动态 skills/personas 正文及需保留的中间产物存入 S3；明确权威、配额、TTL 和删除责任，不上传全部 workspace。
4. SQLite 不作为任何默认或企业运行 profile 的数据库/缓存；只限独立离线源读取和旧格式 fixture。
5. 默认运行只有 PG；旧 backend 值必须拒绝，PG 配置/连接/schema 不可用时 readiness 或启动失败，不能自动降级写 SQLite。

## 不再交付兼容部署路线

不交付每租户独立 DeepTutor 部署、复合 user_id 软隔离、tenant-local 文件后端或 SQLite/PVC 过渡版。LightRAG 选型已确定，A1/A2 完成质量/容量/安全/恢复验收，A3 汇总 G1。固定 workspace 实例池是首发交付要求，不复制租户前后端/认证/控制面；WeKnora 不在首发范围；用户 fork 的 HugeGraph 支持纳入首发，不先发布一个再整体切换。保留连接 PG 的本机/CLI/SDK，而非 local SQLite 存储模式；生产文件仍用 S3，检索图使用 HugeGraph，不将全部文件/图搬 PG，不新增 fallback。

第一阶段使用固定内部 tenant 的同一生产底座，第二阶段扩大租户集合，第三阶段叠加运营界面；不是建设三个不同系统。

## 发布策略

采用 [05：Woodpecker 构建与 K8s 部署流水线](05-woodpecker-kubernetes-pipeline.md)，从 A1 并行开发、A3/G1 完成真实发布验收，后续阶段与官方更新复用。保留三个里程碑、七个工作包，不另立 CI/CD 业务阶段。

- 同一可信源码构建一次，前后端及启用的执行组件按 digest 晋级；测试到生产不重复构建，不部署 latest。
- 开发/测试/生产是环境，不是三个各自构建不同制品的长期分支；实际受保护集成分支与发布 ref 由接入契约确认。
- 自有镜像推送 fork 的受控 registry，不能沿用现 GitHub Actions 中官方 ghcr.io/hkuds/deeptutor 目标；协调两个 CI，避免双发布。
- 生产批准与权限由可信服务端边界实施；PR 无发布/集群凭证。迁移 Job、部署、smoke 和回退共用环境锁及当前版本校验。
- 企业镜像/启动器与默认镜像/合并启动都适配显式 PG/Secret 配置；必要时修改现有 Dockerfile/入口并测试，不能假设 Kubernetes Secret 自动生效或默认启动仍可使用 SQLite。

每次发布记录流水线/批准人/环境、upstream 与自有 SHA、制品清单和全部镜像 digest、企业包版本/依赖锁、通用补丁基线、LightRAG 选型及上线验收记录、LightRAG fork 仓库/包含 HugeGraphStorage 的 commit/上游基线与镜像、接口、HugeGraph 版本/schema/权限/存储拓扑、必要队列及 binding 版本、原文/服务派生副本责任、PG 迁移版本/结果、对象格式、配置版本、运行模式、门禁与恢复证据。必需检查失败/缺失不得放行。本地未提交 adapter 或仅旧 PG 图评估不能作为 fork 制品证据；upstream 合并须保留 HugeGraph 注册与语义并重验固定 workspace、低权权限、同名实体/跨库遍历/删除、写不确定性与 PG/HugeGraph/S3 成套恢复。

## 回滚策略

1. 每次发布说明应用/fork 版本与 PG、HugeGraph 数据/schema/权限、S3/object 及 binding 版本的兼容范围，不保证任意旧 tag 都能回滚。
2. 优先使用兼容当前 PG/HugeGraph/S3/binding 的上一版应用与检索制品组合；变更采用先扩展后收敛，在验证窗口后才删除旧字段/格式。这是安全发布策略，不是双写过渡系统。
3. 首次导入切换前失败可停用新版本继续源系统；PG/HugeGraph/S3 已有新写入后禁止直接切回旧 SQLite/file 丢弃新数据。
4. 不兼容变更需停止写入，按经演练的 应用/检索 PG、HugeGraph 数据/schema/权限及 S3/binding 成套备份恢复，记录 RPO/RTO 和潜在损失；不得只回滚 PG 而遗留图状态、权限或对象引用错配。
5. 保留数据与审计，清理/失效必要 token 和策略缓存，确认租户停用/授权不会因应用回滚反向放开。

## 合并冲突高风险文件

| 文件 | 风险原因 |
| --- | --- |
| `deeptutor/services/auth.py` | 官方可能调整 auth 逻辑 |
| `deeptutor/api/routers/auth.py` | WebSocket/HTTP auth 共用逻辑 |
| `deeptutor/multi_user/paths.py` | 上游路径兼容与 scratch 边界，不新增企业 tenant-local 持久化 |
| `deeptutor/multi_user/models.py` | user/scope 模型核心 |
| `deeptutor/multi_user/knowledge_access.py` | KB 访问控制核心 |
| `deeptutor/services/session/turn_runtime.py` | turn 生命周期复杂 |
| `deeptutor/services/session/__init__.py` | session store backend 选择入口 |
| `deeptutor/services/session/sqlite_store.py` | 退出全部业务运行路径；旧格式由隔离 importer 处理，不能从 upstream 重新引入本地兼容 |

降低冲突的关键是：不要把 EduPlus2 业务逻辑散落在这些文件中。

## Upstream 合并门禁

按已交付里程碑运行 G1/G2/G3 及适用的 G-H，检查新 SQL/文件写入旁路、全局 admin 调用、turn runtime 拆分文件及新 tool/capability 持久化。默认发行物 PG-only 同样是合并门禁，不重新引入上游 SQLite profile；企业文件权威继续遵守 PG/S3。通用 PG/Store/身份 hook 可贡献上游，但不以等待官方接受 PR 为上线前置。

## 并行准备与发布证据

A3 的 Woodpecker 开发、镜像、K8s 集成环境和清单准备从 A1 开始，A1/A2 每个真实功能增量都部署验证；A3/G1 才开放完整单租户生产。EduPlus2 注册/测试账号/权限契约准备同时推进，但不成为 M1 上线依赖。后续 B1 单租户接入、B2 多租户、C1 基础运营、C2 完整治理共用底座；工作包验收不等于全部里程碑完成。

每次发布记录容量、可用性/恢复目标及运行模式；多执行者或 HA 目标先完成 H/G-H，不把多副本硬编码为 M2 的固定拓扑。PG/HugeGraph/S3 等依赖的可用性也纳入验证，不能只凭 backend 有两个 Pod 声称 HA。单执行模式需记录业务/运维接受的维护窗口与恢复语义。

### K8s deployment acceptance

Before cutover, record the backend image digest, migration version, ObjectStore provider summary, Secret references, readiness/status output, and stateless smoke result. A Deployment with multiple replicas is not an HA claim unless the separate H-line fencing and recovery gates are satisfied.
