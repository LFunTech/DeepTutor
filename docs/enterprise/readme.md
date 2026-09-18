# DeepTutor 企业化架构与实施方案：三个里程碑、七个工作包

本目录覆盖 DeepTutor 的企业存储、生产部署、多租户、TMS/OMS、外部集成和持续维护。目录统一命名为 `docs/enterprise/`；EduPlus2 是身份、权限与组织数据集成子域，不是整个企业化方案的边界。保持 00–13 编号与阅读顺序，当前不另拆子目录。

## 方案状态与最新决策

- **修订日期**：2026-09-17；整体路线仍为待交付方案，不是已部署声明；首个身份/PG 会话子切片、生产 `data/` 外置化切片和 EduPlus2 API-only 联邦访问切片的实现与验证见下方独立记录。
- **最新数据库范围**：用户已明确取消独立 local/SQLite 模式，默认 Web、CLI、SDK 与后台全部使用 PostgreSQL；本机部署仍可用，但也必须连接 PG。完整迁移规划见 [`migrate-all-sqlite-state-to-postgresql`](../../openspec/changes/archive/2026-09-16-migrate-all-sqlite-state-to-postgresql/proposal.md)，已实施并归档，实际状态见该 change 的 tasks/执行证据，不把首切片验收当作全仓已经切换。
- **唯一主线**：阶段一单租户 Kubernetes 上线 → 阶段二 EduPlus2 多租户及每租户自己的管理界面 → 阶段三统一运营管理后台。
- **直接替换**：第一阶段就使用 PostgreSQL + S3-compatible；不开发 POC、租户独立部署、文件型多租户或双写过渡版本。
- **界面边界**：TMS（Tenant Management System，租户管理系统）采用 `/tms`；OMS（Operations Management System，平台运营管理系统，非订单管理）采用 `/oms`。租户页面复用现有组件，两级管理并存。
- **管理 API**：专属接口分别采用 `/api/v1/tms/*`、`/api/v1/oms/*`；角色与 `tenant.*` / `ops.*` 能力 key 不改名，通用业务 API、WS、`/api/v1/auth/eduplus2/exchange` 和 EduPlus2 接入路径各自保持契约。M1 `/tms` 仅管理固定租户，B1/B2 的 TMS 先锁定单租户 client/app 管理，普通第三方调用运行时仍按 EduPlus2 JWT `tid` 支持多租户；OMS 注册 client 后自动归口到对应 TMS。详见 [11](11-api-and-entrypoints.md)。
- **多租户从首发设计**：A1 固定内部 tenant/user、KB/index-version 和授权边界，A2/G1 验证双租户及同租户私有 KB 负例；B1/B2/G2 才开放真实多租户。应用 binding、内部 ID 与 LightRAG 内部存储映射不因外部身份绑定而搬迁。
- **执行粒度**：M1=A1/A2/A3，M2=B1/B2，M3=C1/C2；工作包不等于单独生产版本。
- **并行准备**：K8s 集成环境、Woodpecker 流水线开发与 EduPlus2 注册/契约准备从 A1 起并行，不阻塞为单独过渡阶段。
- **EduPlus2 身份边界**：DeepTutor 不提供普通用户注册；只有 TMS/OMS 需要 DeepTutor 交互式登录。第三方应用已完成登录时，将 EduPlus2 user JWT 传给 DeepTutor 换取短期 `dt_token`，由 active client/app 注册、租户/app 状态、owner/grant 和能力策略共同授权。
- **EduPlus2 当前实现状态**：[`enterprise-eduplus2-federated-access`](../../openspec/specs/enterprise-eduplus2-federated-access/spec.md) 已归档为正式 OpenSpec spec；当前 repo 已实现 API-only exchange、OIDC/JWKS、resolve/allowlist、短期 `dt_token`、WS `auth_refresh` 通用 seam、owner/resource guard、可选 profile/permission/webhook 增强和独立审计查询/导出 UI。P1 前置应用联调契约见 [EduPlus2 前置应用接入联调契约](eduplus2-fronting-app-integration-contract.md)。TMS/OMS、Handoff/OIDC callback、在线 client 治理和实时撤权 SLA 仍不在该切片内；打开/refresh/周期合法性校验由前置应用负责。
- **自动交付必需**：Woodpecker 是 M1/A3 必交付子环节；构建、镜像推送、迁移、K8s 部署、业务 smoke 与受控回退实跑后才通过 G1，后续阶段复用。
- **K12 容量基线（2026-09-14）**：用户委托评估，首期目标为 3,000 学生/约 8,000 三方账号、600 同时在线与一学年存量，另规划 30,000 学生扩容档；详见 [容量假设、数据量和验收目标](../../openspec/changes/archive/2026-09-16-migrate-all-sqlite-state-to-postgresql/capacity-assessment.md)。P1 隔离容量与重度尾部验收已按该 change 的 1.47 记录；这仍不代表 P2、正式 HA 或真实供应商并发已经通过。
- **可用性独立**：H 工作线按容量/可用性目标触发 G-H，不因第二个租户强制第二个 Pod；未通过协调验收不得启用多执行者。
- **维护策略**：配置与现有扩展点优先；必要通用核心 hook/旁路收敛 + 独立企业扩展包/应用外壳，不承诺完整产品仅靠配置或源码零 diff。
- **PG 实现归属调整**：通用 PG 连接/迁移/身份/业务 Store 从首切片下沉 core，默认发行物包含 PG 支持；企业特有集成、资源和治理仍在独立包，core 不反向依赖企业包，不复制第二套 schema/数据。
- **RAG 路线已确定**：企业首发使用 LightRAG Server，保留图检索，由 DeepTutor 回答；首发图后端使用用户 fork 的 `HugeGraphStorage`，WeKnora 不在首发实施范围。A1/A2 继续完成真实教材、生命周期、安全、容量及恢复验证；选型确定不等于通过 G1。
- **服务边界**：LightRAG 按内部 tenant/KB/index-version 使用固定 workspace 实例池，不按租户复制整套 DeepTutor。名称、workspace、HugeGraph scope 或 API key 都不能替代 owner/grant、PG RLS 与图服务端权限；实例容量、开通/回收和写互斥是必交付项。详见 [06](06-postgresql-native-store-plan.md)。
- **文件边界**：S3 保存原文/解析文件、附件、持久工作区文件、生成/导出物、动态 skills/personas 正文及需保留的中间产物；PG 保存业务状态与 memory/notebook 正文，Secret 保存凭证，scratch 仅临时使用。服务派生副本、配额及删除责任见 [06](06-postgresql-native-store-plan.md)，完整清单见 [07](07-resource-isolation.md)。

### 依赖层级（不是三种存储都由 DeepTutor 直连）

```text
DeepTutor → 应用 PostgreSQL / S3 / LightRAG Server API
                                  ├── 检索 PostgreSQL
                                  └── HugeGraph
```

HugeGraph 是 LightRAG 的图后端。DeepTutor 负责业务授权、服务 binding、文件及 API 级文档生命周期；图连接/凭证/schema/迁移/内部恢复归 LightRAG 及其部署运维。联合交付覆盖全部依赖，但不向 DeepTutor 业务进程授予图库访问权。详见 [06 责任边界](06-postgresql-native-store-plan.md#依赖层级与责任边界)。

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

OpenSpec 正式 specs 与 [02 执行总纲](02-rollout-testing-and-migration.md) 是需求、验收与任务状态主记录。当前 active changes 为空；已归档 changes 的证据见下方收口记录和 `openspec/changes/archive/`。企业包/外壳、TMS/OMS、三个里程碑、七个工作包及全部业务范围仍保留；不因单个切片完成而勾选未完成的里程碑门禁。

## 首个实施 proposal：A1 子切片

2026-09-13，用户确认首个变更采用较小纵向切片，规划为 [`add-enterprise-pg-identity-session-slice`](../../openspec/changes/archive/2026-09-16-add-enterprise-pg-identity-session-slice/proposal.md)：企业装配、可信固定租户本地身份与 PG 文本会话闭环；其余 A1 另立后续 proposal，不一次实施完整 A1。详见 [design](../../openspec/changes/archive/2026-09-16-add-enterprise-pg-identity-session-slice/design.md)、[子切片 tasks](../../openspec/changes/archive/2026-09-16-add-enterprise-pg-identity-session-slice/tasks.md)。用户随后批准执行；当前 34 项子任务已实现并完成隔离 PG/真实模型/入口及回归验证，见 [执行证据](../../openspec/changes/archive/2026-09-16-add-enterprise-pg-identity-session-slice/execution-evidence.md) 与 [运行说明](../../extensions/enterprise/README.md)。未合并或上线，完整 A1/G1 未通过。

总纲原 90 项保留为工作包汇总门禁，子切片 tasks 记录细项证据；只有原项的全部范围完成才更新总纲 checkbox，不因子切片完成标记 A1/M1/G1。A3 环境/CI、B1 外部契约及 H 目标准备继续按总纲并行；不新增过渡生产版本。

## 2026-09-17 OpenSpec 收口记录

- `add-eduplus2-federated-access` 已归档到 `openspec/changes/archive/2026-09-17-add-eduplus2-federated-access/`，正式 spec 为 [`enterprise-eduplus2-federated-access`](../../openspec/specs/enterprise-eduplus2-federated-access/spec.md)。实现已合并到 `master`，提交为 `2e9bdffd feat(enterprise): add EduPlus2 federated access`。
- `externalize-data-directory-for-kubernetes-runtime` 已收敛为归档目录 `openspec/changes/archive/2026-09-16-externalize-data-directory-for-kubernetes-runtime/` 和正式 specs：[`externalized-resource-store`](../../openspec/specs/externalized-resource-store/spec.md)、[`externalized-runtime-configuration`](../../openspec/specs/externalized-runtime-configuration/spec.md)、[`kubernetes-stateless-runtime`](../../openspec/specs/kubernetes-stateless-runtime/spec.md)；当前 OpenSpec 已无 active changes。
- 以上收口不表示完整 M1/G1、B2/G2、TMS 或 OMS 已交付。下一步建议先做前置应用联调契约与 M1/G1 生产基线，而不是直接把 TMS/OMS 壳层视为已完成。

## 文档地图（与文件编号一致）

已归档的全量 PostgreSQL-only 迁移 change 为 [全量 PostgreSQL-only 迁移](../../openspec/changes/archive/2026-09-16-migrate-all-sqlite-state-to-postgresql/proposal.md)：[调用清单](../../openspec/changes/archive/2026-09-16-migrate-all-sqlite-state-to-postgresql/inventory.md)、[design](../../openspec/changes/archive/2026-09-16-migrate-all-sqlite-state-to-postgresql/design.md)、[55 项任务](../../openspec/changes/archive/2026-09-16-migrate-all-sqlite-state-to-postgresql/tasks.md)与[执行证据](../../openspec/changes/archive/2026-09-16-migrate-all-sqlite-state-to-postgresql/execution-evidence.md)。覆盖所有剩余 SQLite 领域、Matrix 间接存储、旧数据只读导入与默认入口；不是完整 A1/A2/G1 的替代，未勾选项仍按该 change 保持未完成。

| 文档 | 执行位置 | 阅读/实施重点 |
| --- | --- | --- |
| [00-overview-and-decisions.md](00-overview-and-decisions.md) | 准备：总体决策 | 目标、边界与已采纳决策 |
| [01-current-deeptutor-baseline.md](01-current-deeptutor-baseline.md) | 准备：当前基线 | 确认现有功能、真实入口及改造范围 |
| [02-rollout-testing-and-migration.md](02-rollout-testing-and-migration.md) | 准备：执行总纲 | 七个工作包、并行依赖、G1/G2/G3/G-H 与切换验收 |
| [03-tenant-scope-schema.md](03-tenant-scope-schema.md) | M1 / A1：稳定契约 | 固定内部 tenant/user、所有权与 namespace；M2 仅绑定外部身份 |
| [04-kubernetes-postgresql-architecture.md](04-kubernetes-postgresql-architecture.md) | M1 / A3：环境准备 | 从 A1 并行准备 K8s、PG/S3、Secret、探针和运行模式 |
| [05-woodpecker-kubernetes-pipeline.md](05-woodpecker-kubernetes-pipeline.md) | M1 / A3：自动交付 | 从 A1 并行开发 CI、镜像、迁移/部署/smoke；G1 前验收 |
| [06-postgresql-native-store-plan.md](06-postgresql-native-store-plan.md) | M1 / A1–A2：存储替换 | 企业 Store、LightRAG 接入与上线门禁、原文/派生副本责任 |
| [07-resource-isolation.md](07-resource-isolation.md) | M1 / A2 → M2 / B2：资源链路 | S3/PG/Secret/scratch 内容清单；首发资源闭环及多租户隔离 |
| [08-auth-and-identity.md](08-auth-and-identity.md) | M2 / B1：外部身份 | EduPlus2 登录、无注册边界、第三方 JWT 静默换票、`dt_token` 与 WS 刷新 |
| [09-authorization-and-grants.md](09-authorization-and-grants.md) | M2 / B1–B2：业务权限 | 外部权限、grants、client/app 注册唯一性、token exchange 授权与审计 |
| [10-user-data-sync-and-webhooks.md](10-user-data-sync-and-webhooks.md) | M2 / B1–B2：数据与事件 | 首租户可先不依赖 Webhook；随后多租户同步、Webhook 与周期对账 |
| [11-api-and-entrypoints.md](11-api-and-entrypoints.md) | M2 / B1–B2：入口联调 | HTTP/WS/SDK、token exchange、TMS/OMS client API 与外部能力入口契约 |
| [12-platform-operations-admin.md](12-platform-operations-admin.md) | M2 / B2 → M3 / C1–C2：管理界面 | TMS 单租户 client/app 管理、OMS 归口、权限矩阵、迁移判断与验收 |
| [13-deployment-and-upstream-sync.md](13-deployment-and-upstream-sync.md) | 贯穿全程：扩展与持续维护 | 配置/插件/外壳可行性、企业包与通用补丁边界、组合制品及 upstream 回归 |
| [eduplus2-fronting-app-integration-contract.md](eduplus2-fronting-app-integration-contract.md) | P1：前置应用接入联调 | exchange、HTTP/SDK、WS refresh、错误矩阵、配置矩阵、审计排障与 smoke 命令；不代表 TMS/OMS 或生产上线完成 |
| [eduplus2-oauth-client-resolve-api-proposal.md](eduplus2-oauth-client-resolve-api-proposal.md) | 可转发给 EduPlus2 团队的接口需求 | 通用 `POST /api/v1/open/oauth-clients/resolve` 设计；按 `client_id` 解析 app/tenant/status/policy，不含 DeepTutor 定制语义 |

跨系统职责统一见 [06 责任矩阵](06-postgresql-native-store-plan.md#跨系统责任矩阵)：任务/取消、模型/预算、解析/S3 派生物、KB/实例开通、外部资格/本地启停、成员身份/私有资源授权。执行细节分别见 [07 模型](07-resource-isolation.md#聊天模型与检索模型分离)、[03 状态来源](03-tenant-scope-schema.md#租户状态的独立来源)和 [09 权限](09-authorization-and-grants.md#权限检查策略)。

## 核心结论

1. **先交付单租户 K8s，不等多租户和 OMS 运营界面**；首发已启用功能必须完整替换 PG/S3，不能只换新增表。
2. **第二阶段交付可用的多租户产品**：EduPlus2 身份/权限、所有资源与任务隔离、每租户管理 UI 同时完成。
3. **第三阶段单独建设统一运营后台**：管理所有租户生命周期、策略、配额、用量和审计；不取消租户管理界面。
4. **不维护过渡存储**：默认入口与企业入口均不双写、不静默回退；SQLite 只允许独立离线源读取/旧格式测试 fixture，不保留 local profile 或运行态临时 SQLite cache。
5. **安全控制不能后补**：M1 交付本地身份/owner/grant、PG/图/S3 隔离与基础限流；M2 补齐外部撤权、多租户策略、client/app 注册、token exchange 及治理 API，不等运营 UI。
6. **无状态持久化不代表自动可多副本**：首发可单执行副本并明确非 HA，多执行者/HA 目标触发时先通过 G-H 再扩容，触发时点不与租户数量绑定。
7. **首发交付流水线，不只交付部署清单**：Woodpecker 从 A1 并行建设，A3/G1 验证实际构建、部署、业务 smoke 与安全回退。
8. **保留上游可更新性，不保留旧数据库运行路径**：核心承载通用 PG 与必要扩展点/调用收敛，EduPlus2、TMS/OMS、client registry、token exchange 等企业专属实现放包外；升级验证 core、企业包及已选 RAG 服务/存储的兼容组合，不能重新带入 local SQLite。
9. **已选 LightRAG Server，不等于已可投产**：首发按用户 `LFunTech/LightRAG` fork + HugeGraphStorage 推进；PG 存 KV/vector/doc_status，HugeGraph 存图。现有 client 只负责检索，企业文档管理、权限、质量及恢复验收不能省略。
10. **零 diff 不是验收目标**：禁止用大规模 monkey patch、请求内切换进程环境、JSON/PG 异步双写或隐藏菜单代替可靠扩展和隔离。

## 选型实测附录

- [2026-09-13 WeKnora / LightRAG Server Docker 评估](evaluations/2026-09-13-rag-services.md)：固定版本、必需图检索、HugeGraph 可达性、生命周期与权限负例；作为历史证据保留，不代表生产验收通过。
- [脱敏机器结果与语料](evaluations/2026-09-13-rag-services-results.json)。

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
| `deeptutor/services/session/sqlite_store.py` | 当前仍存在的 SQLite session store；新 change 退出全部运行路径，旧格式仅由独立只读 importer 处理 |
| `deeptutor/services/session/protocol.py` | session store 协议基础；PG 化的优先扩展点 |
| `deeptutor/app/container.py` | 现有容器注入入口，不能覆盖所有直连 SQLite/文件旁路 |
| `deeptutor/runtime/registry/capability_registry.py` | `deeptutor.extensions` 能力发现；非全站基础设施插件机制 |
| `deeptutor/services/rag/factory.py` | 8 个已注册 provider；源码默认仍为 llamaindex，不表示企业方案已上线 |
| `deeptutor/services/rag/pipelines/lightrag_server/` | 已选路线的现有检索连接；企业层仍需完成受控 binding、完整文档生命周期及验收，其他上游 adapter 保留兼容但不作为首发托管实现 |
