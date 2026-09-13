# DeepTutor × EduPlus2 实施方案索引：三个里程碑、七个工作包

本目录沉淀 DeepTutor 与 EduPlus2 对接的架构决策、领域方案和后续实施边界。文档基于当前仓库结构、EduPlus2 开发者文档，以及本轮讨论形成的共识。

## 方案状态与最新决策

- **修订日期**：2026-09-13；本目录是待实施方案，不是已实现或已部署声明。
- **唯一主线**：阶段一单租户 Kubernetes 上线 → 阶段二 EduPlus2 多租户及每租户自己的管理界面 → 阶段三统一运营管理后台。
- **直接替换**：第一阶段就使用 PostgreSQL + S3-compatible；不开发 POC、租户独立部署、文件型多租户或双写过渡版本。
- **界面边界**：租户管理界面基于现有 DeepTutor 界面微调；统一运营后台面向全部租户，与租户界面并存。
- **不返工底座**：阶段一固定内部 tenant/user ID，阶段二只绑定 EduPlus2 外部身份；PG/S3 数据与 key 不搬迁。
- **执行粒度**：M1=A1/A2/A3，M2=B1/B2，M3=C1/C2；工作包不等于单独生产版本。
- **并行准备**：K8s 集成环境、Woodpecker 流水线开发与 EduPlus2 注册/契约准备从 A1 起并行，不阻塞为单独过渡阶段。
- **自动交付必需**：Woodpecker 是 M1/A3 必交付子环节；构建、镜像推送、迁移、K8s 部署、业务 smoke 与受控回退实跑后才通过 G1，后续阶段复用。
- **可用性独立**：H 工作线按容量/可用性目标触发 G-H，不因第二个租户强制第二个 Pod；未通过协调验收不得启用多执行者。
- **维护策略**：配置与现有扩展点优先；必要通用核心 hook/旁路收敛 + 独立企业扩展包/应用外壳，不承诺完整产品仅靠配置或源码零 diff。
- **RAG 路线**：默认保留现有 `lightrag-server` HTTP 检索，LightRAG Server 管理检索索引，企业适配层补齐授权、KB/workspace 路由、导入/删除/引用与 PG/S3；不重写检索内核。
- **服务边界**：不按租户复制整套 DeepTutor；允许共享检索基础设施中的固定 workspace Server 实例池，不把一个 Server 地址下的多个 KB 别名当成隔离。详见 [06](06-postgresql-native-store-plan.md) 与 [13](13-deployment-and-upstream-sync.md)。

## 里程碑与实施工作包

| 业务里程碑 | 工作包 | 发布边界 |
| --- | --- | --- |
| M1：单租户 K8s 上线 | A1 结构化状态替换；A2 文件与检索替换；A3 单租户生产验收 | A1/A2 可集成验收，A3 完成流水线与 G1 后正式上线 |
| M2：多租户及租户管理 | B1 EduPlus2 单租户闭环；B2 多租户与租户自管理 | 先验证一个真实租户的最终接入，再通过 B2/G2 开放多租户 |
| M3：统一运营后台 | C1 运营管理闭环；C2 运营治理完善 | C1 可先发布，但完成 C1+C2/G3 才算 M3 完整交付 |

H 为贯穿工作的可用性/容量工作线，不是第八个业务工作包。安全、恢复、监控和官方更新回归始终执行。任务粒度以真实行为闭环为准，不能用只有数据库、API 或页面一层的实现作为完成。

## 按执行顺序阅读

文件编号、下方索引和领域文档标题已按“准备 → M1 单租户 → M2 多租户 → M3 运营 → 持续维护”统一排序，不再按讨论时追加文档的先后编号。

- **00–02：先确认目标、基线与完整执行计划。** [02](02-rollout-testing-and-migration.md) 是依赖/门禁总纲，实施时持续返回核对。
- **03–07：建设 M1 底座。** 先固定内部身份契约，K8s 与 Woodpecker 从 A1 并行准备，随 A1/A2 完成 PG/S3/资源链路，最终由 A3/G1 验收。
- **08–11：推进 M2 接入与隔离。** 按 B1 的单租户身份/权限/事件/入口闭环验证，再以 B2 扩展多租户；不是先做完全部身份、再统一补 API 的水平分层开发。
- **12：交付两级管理界面。** 其中租户界面属于 B2，统一运营属于 C1/C2，不能把租户管理延后到 M3。
- **13：全程遵守的发布与 upstream 维护规则。** 编排在最后方便维护查阅，但从首次开发/发布即生效，不等待 M3 完成。

编号表示主阅读/实施路径，不把并行工作变成串行：A1/A2 依赖稳定契约协作；A3 环境与流水线、B1 外部注册/契约准备从 A1 启动；H 的目标评估从 A1 执行，实际多执行者/HA 前先过 G-H。

OpenSpec 是需求、验收与任务状态主记录：[proposal](../../openspec/changes/replace-rollout-with-three-production-stages/proposal.md)、[按工作包及包内执行顺序排列的 tasks](../../openspec/changes/replace-rollout-with-three-production-stages/tasks.md)。本次在既有编排上更新扩展包/外壳职责与 LightRAG Server 技术路线，保持三个里程碑、七个工作包及完整业务验收范围；同步细化任务，不勾选实施任务。

## 文档地图（与文件编号一致）

| 文档 | 执行位置 | 阅读/实施重点 |
| --- | --- | --- |
| [00-overview-and-decisions.md](00-overview-and-decisions.md) | 准备：总体决策 | 目标、边界与已采纳决策 |
| [01-current-deeptutor-baseline.md](01-current-deeptutor-baseline.md) | 准备：当前基线 | 确认现有功能、真实入口及改造范围 |
| [02-rollout-testing-and-migration.md](02-rollout-testing-and-migration.md) | 准备：执行总纲 | 七个工作包、并行依赖、G1/G2/G3/G-H 与切换验收 |
| [03-tenant-scope-schema.md](03-tenant-scope-schema.md) | M1 / A1：稳定契约 | 固定内部 tenant/user、所有权与 namespace；M2 仅绑定外部身份 |
| [04-kubernetes-postgresql-architecture.md](04-kubernetes-postgresql-architecture.md) | M1 / A3：环境准备 | 从 A1 并行准备 K8s、PG/S3、Secret、探针和运行模式 |
| [05-woodpecker-kubernetes-pipeline.md](05-woodpecker-kubernetes-pipeline.md) | M1 / A3：自动交付 | 从 A1 并行开发 CI、镜像、迁移/部署/smoke；G1 前验收 |
| [06-postgresql-native-store-plan.md](06-postgresql-native-store-plan.md) | M1 / A1–A2：存储替换 | 企业 Store、S3、LightRAG Server 路由/存储/生命周期与真实调用 |
| [07-resource-isolation.md](07-resource-isolation.md) | M1 / A2 → M2 / B2：资源链路 | 首发资源存储闭环；多租户时复验资源隔离与策略 |
| [08-auth-and-identity.md](08-auth-and-identity.md) | M2 / B1：外部身份 | EduPlus2 登录、身份绑定与撤权；注册/契约准备在 A1 并行 |
| [09-authorization-and-grants.md](09-authorization-and-grants.md) | M2 / B1–B2：业务权限 | 外部权限、grants、平台/租户能力边界；M1 本地防护仍先做 |
| [10-user-data-sync-and-webhooks.md](10-user-data-sync-and-webhooks.md) | M2 / B1–B2：数据与事件 | 首租户必要事件、权限失效，随后多租户同步/对账 |
| [11-api-and-entrypoints.md](11-api-and-entrypoints.md) | M2 / B1–B2：入口联调 | HTTP/WS/SDK/后台上下文贯通与双租户验收，M1 基础入口随存储先接通 |
| [12-platform-operations-admin.md](12-platform-operations-admin.md) | M2 / B2 → M3 / C1–C2：管理界面 | B2 先交付租户界面；C1/C2 再交付统一运营后台 |
| [13-deployment-and-upstream-sync.md](13-deployment-and-upstream-sync.md) | 贯穿全程：扩展与持续维护 | 配置/插件/外壳可行性、企业包与通用补丁边界、组合制品及 upstream 回归 |

## 核心结论

1. **先交付单租户 K8s，不等多租户和新 Admin**；首发已启用功能必须完整替换 PG/S3，不能只换新增表。
2. **第二阶段交付可用的多租户产品**：EduPlus2 身份/权限、所有资源与任务隔离、每租户管理 UI 同时完成。
3. **第三阶段单独建设统一运营后台**：管理所有租户生命周期、策略、配额、用量和审计；不取消租户管理界面。
4. **不维护过渡存储**：生产不双写、不静默回退；现有 SQLite/local 只供独立本地模式或只读导入，不新增企业文件后端。
5. **安全控制不能等运营 UI**：tenant_admin/平台角色边界、RLS、撤权、配额执行、审计和必要管理 API 在第二阶段到位。
6. **无状态持久化不代表自动可多副本**：首发可单执行副本并明确非 HA，多执行者/HA 目标触发时先通过 G-H 再扩容，触发时点不与租户数量绑定。
7. **首发交付流水线，不只交付部署清单**：Woodpecker 从 A1 并行建设，A3/G1 验证实际构建、部署、业务 smoke 与安全回退。
8. **保留上游可更新性，不保留旧生产写路径**：核心只承载必要通用扩展点/调用收敛，企业实现放包外；升级验证 core、企业包及 LightRAG 的兼容组合。
9. **保留 LightRAG Server，不把 pgvector 当替代引擎**：当前连接只负责检索；导入、索引状态、权限、源文、删除与恢复仍须完整交付。
10. **零 diff 不是验收目标**：禁止用大规模 monkey patch、请求内切换进程环境、JSON/PG 异步双写或隐藏菜单代替可靠扩展和隔离。

## 主要外部参考

- EduPlus2 平台概述：<https://eduplus-test.f123.pub/docs/getting-started/>
- EduPlus2 OAuth/OIDC：<https://eduplus-test.f123.pub/docs/oauth-oidc/>
- EduPlus2 工作台 Handoff：<https://eduplus-test.f123.pub/docs/oauth-oidc/workbench-handoff/>
- EduPlus2 JWT 验证：<https://eduplus-test.f123.pub/docs/oauth-oidc/jwt-verification/>
- EduPlus2 权限集成：<https://eduplus-test.f123.pub/docs/permission/>
- EduPlus2 Me Profile API：<https://eduplus-test.f123.pub/docs/user-data/me-profile-api/>
- EduPlus2 组织与用户数据对接：<https://eduplus-test.f123.pub/docs/user-data/org-sync-guide/>
- EduPlus2 Webhook：<https://eduplus-test.f123.pub/docs/webhook/>
- SQLite 使用场景：<https://sqlite.org/whentouse.html>
- Kubernetes Persistent Volumes：<https://kubernetes.io/docs/concepts/storage/persistent-volumes/>
- PostgreSQL Row Level Security：<https://www.postgresql.org/docs/current/ddl-rowsecurity.html>

## 当前仓库关键文件

| 文件 | 作用 |
| --- | --- |
| `deeptutor/api/main.py` | FastAPI router 注册和 auth dependency 安装 |
| `deeptutor/api/routers/auth.py` | HTTP / WebSocket auth guard、当前用户上下文安装 |
| `deeptutor/services/auth.py` | token 生成、解码、认证入口 |
| `deeptutor/multi_user/models.py` | `CurrentUser`、`UserScope`、role/scope 模型 |
| `deeptutor/multi_user/paths.py` | `UserScope -> PathService` 路径解析 |
| `deeptutor/multi_user/grants.py` | 用户资源授权 grants |
| `deeptutor/multi_user/knowledge_access.py` | 用户 KB / admin KB 可见性与写入控制 |
| `deeptutor/services/path_service.py` | runtime 文件布局封装 |
| `deeptutor/api/routers/unified_ws.py` | `/api/v1/ws` turn-based WebSocket 入口 |
| `deeptutor/services/session/turn_runtime.py` | turn payload 解析、上下文构建、事件持久化 |
| `deeptutor/services/session/__init__.py` | 当前 session store 选择入口；需扩展 PostgreSQL backend |
| `deeptutor/services/session/sqlite_store.py` | 当前 SQLite session store；企业生产替换后仅独立本地模式/只读导入使用 |
| `deeptutor/services/session/protocol.py` | session store 协议基础；PG 化的优先扩展点 |
| `deeptutor/app/container.py` | 现有容器注入入口，不能覆盖所有直连 SQLite/文件旁路 |
| `deeptutor/runtime/registry/capability_registry.py` | `deeptutor.extensions` 能力发现；非全站基础设施插件机制 |
| `deeptutor/services/rag/pipelines/lightrag_server/` | 现有检索专用客户端/pipeline，保留并通过通用 provider seam 接入企业服务 |
