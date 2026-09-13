# 01. 当前 DeepTutor 基线分析

> 基线说明：本文记录现有实现及改造切入点；不表示已经完成 PG/S3 替换。实施顺序以 [02](02-rollout-testing-and-migration.md) 为准：存储/K8s 在阶段一，EduPlus2 与租户管理在阶段二，统一运营后台在阶段三。

## 当前架构摘要

DeepTutor 当前是 agent-native 学习应用，主要入口：

- CLI：`deeptutor run ...`、`deeptutor chat`
- WebSocket：`/api/v1/ws`
- Python SDK：`DeepTutorApp`

核心执行链路：

```text
HTTP/WS/SDK -> TurnRuntimeManager -> UnifiedContext -> ChatOrchestrator -> Capability/Tool -> StreamBus
```

关键文件：

| 文件 | 作用 |
| --- | --- |
| `deeptutor/runtime/orchestrator.py` | `ChatOrchestrator`，Capability 路由入口 |
| `deeptutor/services/session/turn_runtime.py` | turn payload 解析、上下文构建、异步运行 |
| `deeptutor/core/context.py` | `UnifiedContext` 数据结构 |
| `deeptutor/core/stream.py` | stream event 协议 |
| `deeptutor/api/routers/unified_ws.py` | `/api/v1/ws` WebSocket 入口 |
| `deeptutor/app/facade.py` | Python SDK facade |

## 当前 PostgreSQL 支持状态

当前 DeepTutor 不能视为原生 PostgreSQL 应用：

- `pyproject.toml` 中已有 `aiosqlite`，但没有 PostgreSQL driver。
- `deeptutor/services/session/__init__.py` 的 `get_session_store()` 当前只在 PocketBase 与 SQLite 之间切换。
- `SQLiteSessionStore` 是 sessions/messages/turn_events 的主要本地持久化实现。
- 多个 router、agent、capability 仍直接调用 `get_sqlite_session_store()`。
- settings、grants、model catalog、MCP config、cron jobs 等大量使用 JSON/YAML 文件。

因此，Kubernetes 企业多租户版需要新增 PostgreSQL store backend，而不是简单修改一个配置。

## 已有扩展点及边界（本轮代码核查）

| 现有接口 | 可以复用 | 不能据此推断 |
| --- | --- | --- |
| `deeptutor.extensions` / `CapabilityRegistry` | 外部包注册新的 Capability；旧 `deeptutor.plugins` 为兼容入口 | 自动发现会跳过已有同名能力；不是 Auth/Store/ObjectStore 的通用替换机制 |
| `ToolRegistry.register()` | 自有启动器/能力装配自定义工具 | 自动截获所有业务服务、router 和后台读写 |
| `set_application_container()` | 自有启动器显式注入应用容器 | 默认容器自动支持 PG，或容器替换能接管全部直连 SQLite |
| `TurnRuntimeManager(store=...)` / `SessionStoreProtocol` | 实现并注入外部 PG Store | memory/settings/KB/题库等全部数据随之迁移 |
| `runtime/coordination/` | 已有 Memory/Redis coordinator、lease/recovery 等基础可评估复用 | 已满足本方案多租户、PG 后端和全部 G-H 验收 |

核心缺口应收敛为通用 provider/scope/授权与生命周期接口；企业实现放独立包。仅包装 `DeepTutorApp` 仍会进入默认容器、notebook 和原有服务，不能绕过存储核查。详见 [13](13-deployment-and-upstream-sync.md)。

## 当前 LightRAG Server 支持

本仓库已同时存在 `lightrag`（本地引擎）和 `lightrag-server`（远端检索），不能把二者混为同一种本地文件改造。

- `services/rag/factory.py` 已注册 `lightrag-server`；知识库 UI/router 已提供连接配置、探测与注册。
- `pipelines/lightrag_server/client.py` 以 `X-API-Key` 调用 `POST /query`，设置 `only_need_context=true`；DeepTutor 继续负责回答，支持 `naive/local/global/hybrid/mix` 和 references→sources。
- `initialize/add_documents` 拒绝本地导入，`delete` 不删除远端索引；当前是检索专用连接，不是完整远端 KB 管理。
- `LightRagServerConfig` 只有 `base_url/api_key`；连接写入 `kb_config.json`，默认值写入运行时 `lightrag_server.json`，尚无企业 PG/Secret binding。
- 当前连接没有 per-request workspace 或最终用户授权契约；同一个 URL 下两个 KB 名称不意味着两个独立语料库。原版固定 workspace Server 的默认企业拓扑见 [06](06-postgresql-native-store-plan.md)。

因此默认保留 HTTP 检索和 LightRAG 引擎，A2 的工作改为企业连接/文档管理/存储/隔离适配，而非重新开发图检索。仍需验证现有部署版本及真实接口，代码存在不代表已经生产联调。

## 当前认证模型

关键文件：

- `deeptutor/services/auth.py`
- `deeptutor/api/routers/auth.py`

当前支持：

1. `AUTH_ENABLED=false` 时，所有请求视为 local admin。
2. `AUTH_ENABLED=true` 时，通过 `dt_token` cookie 或 `Authorization: Bearer` 认证。
3. token payload 当前主要包括：

```python
TokenPayload(
    username: str,
    role: str,
    user_id: str = "",
)
```

4. WebSocket 通过 cookie 或 query param `token` 认证。
5. `_install_current_user()` 将 `TokenPayload` 映射为 `CurrentUser` 并写入 ContextVar。

## 当前多用户模型

关键文件：

- `deeptutor/multi_user/models.py`
- `deeptutor/multi_user/paths.py`

当前模型：

```python
Role = Literal["admin", "user"]
ScopeKind = Literal["admin", "user"]
```

路径布局：

```text
data/user           # admin workspace
data/users/<uid>    # 普通用户 workspace
data/system         # auth、grants、audit、indexes
data/partners/<id>  # partner workspaces
```

当前 `PathService` 的核心约定：

- `PathService(workspace_root=data)` 时，用户数据目录为 `data/user`。
- `PathService(workspace_root=data/users/<uid>)` 时，用户数据目录为 `data/users/<uid>/user`。
- 知识库目录为 `<workspace_root>/knowledge_bases`。
- chat history 为 `<workspace_root>/user/chat_history.db`。

## 当前 grants 模型

关键文件：

- `deeptutor/multi_user/grants.py`

当前 grants 位于：

```text
data/system/grants/{user_id}.json
```

授权内容包括：

- `models.llm`
- `knowledge_bases`
- `skills`
- `partners`
- `enabled_tools`
- `mcp_tools`
- `exec_enabled`

当前问题：grants 是部署全局的，不包含 `tenant_id`。

## 当前知识库模型

关键文件：

- `deeptutor/multi_user/knowledge_access.py`

当前有两类 KB：

```text
admin:kb:{name}  # 全局 admin KB
user:kb:{name}   # 当前用户 KB
```

当前问题：`admin:kb:*` 实际指向全局 admin workspace。如果在 EduPlus2 多租户下沿用，会导致租户共享知识库混在一起。

## 当前全局资源风险点

| 资源 | 当前位置/行为 | 多租户风险 |
| --- | --- | --- |
| admin workspace | `data/user` | 容易成为跨租户共享空间 |
| grants | `data/system/grants` | 不含 tenant 维度 |
| model catalog | `data/user/settings/model_catalog.json` | 模型凭证和可用模型全局混用 |
| admin KB | `get_admin_path_service()` | 不区分租户 |
| skills/personas | admin workspace | 租户间可能互相可见 |
| partners | `data/partners` / admin-gated | 当前是部署级资源 |
| MCP config | admin settings | 可能暴露 host-side 能力 |
| cron | admin workspace | 定时任务可能跨租户 |
| sandbox/exec | 系统级隔离依赖强 | 必须独立评估后开放 |

## 可复用基础

现有身份与执行链路可继续使用，但不能只改 UserScope.root 就宣称 PG/S3 或多租户已经完成：

TokenPayload → CurrentUser → 可信 tenant/user scope → Store / ObjectStore / scratch adapter

- HTTP/WS/CLI/SDK 与 tools/capabilities 的产品语义保持。
- 现有 SessionStore 协议可作为数据库替换入口；必须检查直接依赖 SQLite 的旁路。
- 当前 turn_runtime.py 已是组合式 facade，运行时工作还涉及 services/session/turns/ 等实际实现，不能只改 facade。
- 现有 web/app/(admin)/admin 管理界面在阶段二按租户和权限微调，不重写每租户 UI。
- PathService 仅保留本地运行或 scratch；企业持久化走 Store，不增加 tenant-local 文件后端。

## 需要重点改造的边界

1. `TokenPayload` 需要携带 EduPlus2 租户和用户身份。
2. `CurrentUser` / `UserScope` 需要 first-class tenant 字段。
3. `get_admin_path_service()` 的生产调用需要显式拆分为平台/租户/个人资源服务，缺 scope 不得回退全局。
4. grants 需要租户级存储。
5. admin KB、model catalog、skills/personas 等共享资源需要 tenant namespace。
6. `require_admin` 需要区分 platform admin 与 tenant admin。
7. A1/A2 生产存储需要在独立企业包新增 `PostgresSessionStore`、`GrantStore`、`SettingsStore`、`ObjectStore` 等实现；核心只暴露通用协议/provider 并替换生产旁路。
8. 直接调用 `get_sqlite_session_store()` 的路径需要收敛到 `get_session_store()` 或新的 store provider。

## 实施粒度提示

基线风险映射：结构化读写进入 A1，文件/检索进入 A2，K8s 集成与最终上线验收进入 A3（部署准备从 A1 并行）；B1 验证一个真实 EduPlus2 租户的最终接入，B2 才开放多租户与租户管理页面。C1/C2 是统一运营能力的两个工作包；H 多执行者协调按发布目标触发，不绑定 B2。默认 `lightrag-server` 将索引交给外置服务，A2 验证其稳定 namespace、PG 全部索引状态、S3 原文和端到端生命周期；若确有本地 `lightrag` 存量，才评估文件索引/绝对路径 workspace 的只读导入或重建，不默认重写本地 pipeline。
