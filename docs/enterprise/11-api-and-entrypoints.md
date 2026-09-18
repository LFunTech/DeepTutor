# 11. API 与入口适配方案

## 阶段边界

A1/A2 保留现有入口/产品协议并替换固定 tenant 的 PG/S3/scratch，A3 集成验收；B1 验证首租户 EduPlus2 接入和权限，B2 开放多租户及租户管理；C1/C2 新增运营入口和治理视图。服务端-to-服务端调用同样不能绕过 scope 和权限。

### 当前实现状态（2026-09-17）

已实现并归档的 API-only 联邦访问切片包括：

- `POST /api/v1/auth/eduplus2/exchange`：EduPlus2 user JWT → DeepTutor 短期 `dt_token`。
- `POST /api/v1/auth/eduplus2/revocations`：可选签名 revocation 事件入口；不是实时撤权 SLA gate。
- `/api/v1/ws` 的通用 `auth_refresh` / `auth_ack` / `auth_revoked` 协议 seam。
- `GET /api/v1/enterprise/audit/eduplus2/events` 与 `POST /api/v1/enterprise/audit/eduplus2/exports`。
- 独立页面 `/enterprise/audit/eduplus2`，不依赖 `/tms` 或 `/oms`。

P1 前置应用联调 contract、错误矩阵、配置矩阵和 smoke 命令见 [EduPlus2 前置应用接入联调契约](eduplus2-fronting-app-integration-contract.md)。仍未实现：`/tms`、`/oms`、TMS/OMS Handoff/OIDC callback、在线 client 注册治理页面，以及 `/api/v1/tms/*`、`/api/v1/oms/*` 的完整管理闭环。前置应用负责打开/refresh/周期合法性校验；当前 repo 只处理自身 token/session/owner/resource guard 与审计。

## 企业应用外壳与核心入口

企业启动器/应用 factory 位于独立 `deeptutor_enterprise` 包，优先复用容器注入、TurnRuntimeManager/SessionStore、Tool/Capability 协议；缺失处通过通用核心 seam 补齐。产品继续使用既有 HTTP 与 `/api/v1/ws` 语义，不把 Plugin API 或直接 `DeepTutorApp()` 默认初始化当作企业入口的等价替代。

装配时显式选择已接入企业 Store/scope/权限的原路由，注册企业新增路由并校验无重复冲突。相同路径不能靠先后注册偷偷覆盖，原生未适配入口不对外暴露；必需行为必须改造接通而不是简单禁用。启动任务、SDK/CLI、后台容器也使用同一企业 profile，缺 provider/兼容版本拒绝启动。详见 [13](13-deployment-and-upstream-sync.md)。

## 现有入口

DeepTutor 当前主要入口：

| 入口 | 文件 | 说明 |
| --- | --- | --- |
| WebSocket | `deeptutor/api/routers/unified_ws.py` | `/api/v1/ws`，产品主聊天入口 |
| HTTP API | `deeptutor/api/main.py` 注册的 routers | knowledge、sessions、settings、memory 等 |
| Python SDK | `deeptutor/app/facade.py` | `DeepTutorApp` |
| CLI | `deeptutor_cli/main.py` | 本地开发/命令行 |
| Plugin API | `deeptutor/api/routers/plugins_api.py` | playground-style tool/capability execution |

生产对接 EduPlus2 时，主入口应是 HTTP + `/api/v1/ws`。Plugin API 不建议作为生产会话入口。

## WebSocket `/api/v1/ws`

当前 WebSocket 支持：

- `start_turn` / `message`
- `subscribe_turn`
- `subscribe_session`
- `resume_from`
- `cancel_turn`
- `submit_user_reply`
- `regenerate`
- `check_active_turn`
- `auth_refresh`（已作为通用协议 seam 实现，用新 `dt_token` 或 provider 解释的 `external_token` 静默刷新当前 WS 身份）
- `ping`

多租户适配要求：

1. `ws_require_auth()` 必须安装带 `tenant_id` 的 `CurrentUser`。
2. `TurnRuntimeManager.start_turn()` 异步任务必须继承当前 user context。
3. `session_id` 只能在当前 tenant/user scope 内解析。
4. `knowledge_bases` 引用必须通过租户感知的 `resolve_kb()`。
5. stream event 持久化到 PG 当前 tenant/turn，按 seq 重放；取消/回复在多副本下必须到达正确执行者，不能只访问本 Pod 内存。
6. 已接受的单个 turn 不因 `dt_token` 在生成中自然到期而中断；但新 turn、cancel、reply、下载、读历史和敏感工具操作必须重新校验。
7. token 剩余 3–5 分钟时服务端可发送 `auth_expiring`；客户端通过 `POST /api/v1/auth/eduplus2/exchange` 静默换新 `dt_token` 后发送 `auth_refresh`，服务端返回 `auth_ack`。刷新失败时用新 token 重连并通过 `resume_from turn_id + after_seq` 恢复事件流。外部用户合法性周期校验由前置应用负责。

## HTTP API

所有受保护 router 当前通过 `Depends(require_auth)` 安装用户上下文。需要确保：

- `require_auth()` 解码 DeepTutor `dt_token` 后恢复 `tenant_id/eui/eit`。
- 管理类 API 不再统一使用旧 `require_admin()`，而是拆成 platform / tenant 管理权限。
- 数据库调用统一使用 tenant/owner-scoped PG Store，默认入口也不保留 SQLite 模式；`get_current_path_service()` 不得产生数据库权威，企业仅用于受控 scratch/只读资源，其余文件载荷按对应资源契约处理。
- `POST /api/v1/auth/eduplus2/exchange` 是特殊认证交换入口：它不要求已有 `dt_token`，但必须要求 EduPlus2 user JWT、active client/app registration、租户状态和审计写入；失败必须 fail closed。

## EduPlus2 API 状态

当前已实现的外部联调 API 由企业应用外壳注册；完整前置应用契约以 [P1 接入契约](eduplus2-fronting-app-integration-contract.md) 为准。本节只保留入口地图，避免复制两份易漂移的 payload 细节。

| Method | Path | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/auth/eduplus2/exchange` | 已实现。第三方应用传入 EduPlus2 user JWT，DeepTutor 静默换发短期 `dt_token`。 |
| `POST` | `/api/v1/auth/eduplus2/revocations` | 已实现可选增强。签名 revocation 事件入口；不是实时撤权 SLA gate。 |
| `GET` | `/api/v1/enterprise/audit/eduplus2/events` | 已实现。tenant_admin 查询脱敏审计事件。 |
| `POST` | `/api/v1/enterprise/audit/eduplus2/exports` | 已实现。tenant_admin 创建 JSONL/CSV 脱敏导出。 |
| `GET` | `/api/v1/eduplus2/handoff/callback` | 未实现。后续 TMS/OMS 或 Handoff proposal 再定义。 |
| `POST` | `/api/v1/eduplus2/logout` | 未实现。后续 session/handoff proposal 再定义。 |
| `GET` | `/api/v1/eduplus2/session` | 未实现。后续 session/handoff proposal 再定义。 |
| `POST` | `/api/v1/eduplus2/webhooks` | 未实现为该路径；当前可选 revocation 入口为 `/api/v1/auth/eduplus2/revocations`。 |
| `POST` | `/api/v1/eduplus2/sync/{tenant_id}` | 未实现。后续同步 proposal 再定义。 |

### Token exchange 契约

```http
POST /api/v1/auth/eduplus2/exchange
Authorization: Bearer <eduplus2_user_jwt>
```

当前成功响应：

```json
{
  "dt_token": "<deeptutor-dt-token>",
  "token_type": "Bearer",
  "expires_in": 900,
  "expires_at": 1790000000,
  "tenant_id": "<internal-tenant-id>",
  "user_id": "<internal-user-id>",
  "client_registration_id": "<internal-registration-id>"
}
```

校验流程：验签 EduPlus2 JWT → 校验 `iss/exp/iat/nbf` 并提取 `azp` 作为权威 `client_id` → 提取 `tid/eui/sub` → 校验 allowlist/registration → 调用 EduPlus2 通用 `POST /api/v1/open/oauth-clients/resolve` 刷新 app/tenant/client 状态 → 可选 profile/permission 复核 → 映射内部 tenant/user → 签发短期 `dt_token` → 写 `token.exchange` 审计。请求体、query 或非签名 header 中的 tenant/user/client 信息不能作为授权证据，也不能用来覆盖 JWT claims。错误码、WS refresh、审计排障和 smoke 入口见 [P1 接入契约](eduplus2-fronting-app-integration-contract.md)。通用 resolve API 需求草案见 [EduPlus2 通用 OAuth Client Resolve API 需求建议](eduplus2-oauth-client-resolve-api-proposal.md)。

### TMS/OMS client 注册 API

| Method | Path | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/tms/eduplus2/clients` | 当前 TMS 租户注册一个 EduPlus2 `client_id`；必须校验 EduPlus2 返回的外部 tenant 与当前 TMS tenant 完全一致 |
| `DELETE` | `/api/v1/tms/eduplus2/clients/{id}` | 当前 TMS 租户注销/retire 自己归属的 client 注册 |
| `GET` | `/api/v1/tms/eduplus2/clients` | 当前 TMS 租户查看归口到本 tenant 的 client/app 注册 |
| `POST` | `/api/v1/oms/eduplus2/clients` | OMS 校验 `client_id` 后按 EduPlus2 返回的外部 tenant 自动归口到对应 TMS |
| `DELETE` | `/api/v1/oms/eduplus2/clients/{id}` | OMS 注销/retire 任一已归口 client 注册 |
| `GET` | `/api/v1/oms/eduplus2/clients` | OMS 跨租户检索 client/app 注册及状态 |

同一 provider 下 active `client_id` 只能注册一次；同一租户同一 EduPlus2 app 只能有一个 active client。注册时应通过 EduPlus2 通用 resolve API 取得权威 `app_id/tenant_id/app_name/tenant_name/status`，不能只信任人工输入。冲突返回 409；tenant 不匹配返回 403 或 409（按 API 规范细分），未绑定 external tenant 时要求先做 tenant provisioning。

## 对外能力调用 API（阶段二后续开放）

完成 EduPlus2 单租户接入、client/app 注册、token exchange、审计和 WS 续期后，再逐步开放外部能力 API。第一批建议仅开放 `chat`、`deep_solve`，可选 `deep_question`；默认关闭 `exec`、`cron`、MCP、任意 KB、任意模型覆盖和未授权工具。

拟定接口：

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/external/capabilities` | 返回当前 client/app/tenant/user 可用能力与配置边界 |
| `POST` | `/api/v1/external/turns` | 以当前 `dt_token` 创建外部 turn，服务端填充 tenant/user/client metadata |
| `GET` | `/api/v1/external/turns/{turn_id}/events` | 读取或流式订阅 turn events，按 owner/grant/client policy 校验 |
| `POST` | `/api/v1/external/turns/{turn_id}/cancel` | 取消当前授权 turn；不得扩大到其他 session/job/workspace |
| `POST` | `/api/v1/external/turns/{turn_id}/reply` | 响应 `ask_user` 等需要用户补充输入的 turn |

该 API 是 HTTP 形态的能力入口，不替代 `/api/v1/ws`。两者都必须使用同一认证、授权、审计、quota、turn persistence 和 event replay 逻辑。

## RAG 服务接口适配

A1/A2 按已选 LightRAG Server 接入，保留 `POST /query` + `only_need_context=true`、图检索及 references 语义，由 DeepTutor 回答。当前 client 没有动态 workspace、完整企业文档管理或最终用户授权；企业 binding/client provider 从 PG/Secret 与可信身份构造调用，受控路由到固定实例，KB 管理 API 接通 RagDocumentService 的上传/状态/引用/删除/重建。不是只修改 URL 或 provider 名称，也不新增 WeKnora 生产分支。已选用户 fork 通过 HugeGraphStorage 存图，但没有因此增加动态 workspace 路由；图服务/graphspace/graph/namespace/凭证由 LightRAG 部署配置解析，不由 DeepTutor 业务 binding/client 解析；DeepTutor 只调用 LightRAG API，不持有图凭证或直通 REST/Gremlin。M1/G1 即验证双租户及同租户私有 KB 负例；M2/G2 复验真实外部身份。

客户端提交逻辑 KB/document ID，服务端验证归属/操作并解析受控 provider/endpoint/远端 tenant/KB 或 workspace；不开放任意 Server URL、远端文档路径、workspace 或 key。原文引用经 source object_id 映射再次授权；非托管外部连接仍仅解绑。服务间身份、错误与恢复契约见 [06](06-postgresql-native-store-plan.md)。

### 服务管理接口的范围与状态

KB 创建返回业务资源申请/分配状态，不等于部署实例或索引已 ready；采用 [06 预开池交接](06-postgresql-native-store-plan.md#kb-申请与预开实例池交接)，重复请求幂等，池不足显示等待/失败。文档提交原始文件，解析/manifest/派生物由检索服务契约负责；派生引用重新授权后经受控服务读取 API 获取。

任务 API 区分业务 job、远端执行观察状态、`cancel_scope` 和 `cancel_state`，见 [06](06-postgresql-native-store-plan.md#业务任务远端索引与取消边界)。turn 的 cancel 不自动取消同 KB 的后台导入；单 job 请求不能升级为 workspace 取消。`cancel_requested`、不支持与冲突明确返回，重复请求和迟到响应按 operation ID/状态版本对账。HTTP/WS/SDK/worker 使用相同授权，不把断开 HTTP 或结束 turn 视作远端停止/额度释放。

用户 payload 仅可选择已授权业务模型或 profile 引用；检索模型执行配置/Secret 不从聊天设置透传，配置待生效与当前运行版本分别返回。私有 session/memory/notebook 全部入口叠加 owner/已支持的显式 grant，不只调用成员 guard。

## Turn payload metadata

现有 `UnifiedContext.metadata` 可承载租户元信息，但不应让前端直接传入决定性 tenant 信息。建议由服务端填充：

```python
metadata={
    "tenant_id": current_user.tenant_id,
    "user_id": current_user.id,
    "eduplus_user_id": current_user.eduplus_user_id,
    "identity_type": current_user.identity_type,
    "auth_provider": "eduplus2",
    "client_id": current_user.client_id,
    "external_app_id": current_user.external_app_id,
    "external_app_name": current_user.external_app_name,
    "external_tenant_name": current_user.external_tenant_name,
}
```

禁止信任客户端 payload 中的 `tenant_id` 来切换租户。

## SDK

Python SDK 主要用于本地或服务端集成。EduPlus2 模式下建议：

1. 保持本地 SDK 行为不变。
2. 若 SDK 调远端 DeepTutor API，应先用 EduPlus2 user JWT 调 `POST /api/v1/auth/eduplus2/exchange` 换取 `dt_token`，之后使用 `Authorization: Bearer <dt_token>`。
3. 不建议 SDK 直接传 `tenant_id` 覆盖服务端 auth context。
4. 服务端-to-服务端场景使用单独 M2M token，并显式限制可访问租户。

## CLI

CLI 保持本地开发语义。可选增强：

```bash
deeptutor eduplus2 sync --tenant <tid>
deeptutor eduplus2 tenant list
```

阶段一不依赖这些命令；阶段二必须提供受保护管理 API 和可审计运维入口用于开通/绑定/停用/配额，不手工改库，也不等阶段三 UI。上面命令为拟定接口，不是当前可执行命令。

## Plugin API

当前 plugin API 的 capability execute-stream 更偏 playground transport，不走完整 `TurnRuntimeManager` persistence。EduPlus2 生产场景建议：

- 默认不开放给普通用户。
- 如需开放，必须安装 tenant context，且能力输出/持久化路径必须受 scope 限制。
- 不作为主聊天入口。

## API 安全清单

1. 所有入口都必须先 auth，再解析 path/resource。
2. 不允许 query/body 中的 `tenant_id` 覆盖 token 中 tenant。
3. 管理接口区分 `platform_admin` 与 `tenant_admin`。
4. WebSocket token 过期时不得接受新 turn；应优先走 `auth_expiring` / `auth_refresh` 静默刷新，失败再关闭连接或要求重连恢复。
5. 第三方传入的 EduPlus2 JWT 只用于换票和校验，不在 DeepTutor 日志、审计、前端存储中保留原文。
6. 错误响应不泄露路径、secret、token、signature。

## 两级管理入口

企业模式统一采用以下目标命名；这是待实施契约，不表示当前源码已有这些路由：

| 管理域 | 页面入口 | 专属管理 API | 范围与交付 |
| --- | --- | --- | --- |
| TMS（Tenant Management System，租户管理系统） | `/tms`、`/tms/*` | `/api/v1/tms/*`，例如 `/api/v1/tms/kbs` | 当前可信租户；M1 复用既有管理功能服务固定租户，B2 完成多租户自管理适配 |
| OMS（Operations Management System，平台运营管理系统） | `/oms`、`/oms/*` | `/api/v1/oms/*`，例如 `/api/v1/oms/tenants`、`/api/v1/oms/tenants/{tenant_id}` | 平台获授权范围；B2 先提供治理 API，C1/C2 再交付运营界面 |

1. **术语与权限分离**：本方案 OMS 指平台运营，不指订单管理。URL 改名不修改 `tenant_admin`、`platform_admin/platform_operator/platform_auditor` 或 `tenant.*`、`ops.*` 能力 key；页面与后端继续按同一具体能力鉴权，不根据路径名自动授予角色。
2. **TMS 锁定当前租户**：租户来自可信身份 scope，不接受 query/body/header 覆盖。M1 仍使用受保护本地身份和固定内部租户，不提前引入 EduPlus2 或平台运营能力；B1/B2 的 TMS 首先做成单租户管理视图，只能管理与当前 TMS 绑定的 `external_tenant_id` 完全一致的 client/app；B2 使用 `tenant_admin` 及获具体能力的自定义角色。首页按已有授权显示可用管理模块，不要求所有角色都具备 KB 管理能力。
3. **OMS 显式目标范围**：租户 ID 出现在运营路由时，必须先校验平台具体能力，再验证并绑定目标租户；列表只返回获授权管理元数据。OMS 注册 EduPlus2 client 时根据 EduPlus2 返回的外部 tenant 自动归口到对应 TMS。普通业务 API 不获得任意 tenant override，租户管理员不能因路径改名访问运营 API。
4. **专属管理前缀，不迁移全部 API**：仅租户/运营专属管理接口采用 TMS/OMS 前缀；聊天、资源等通用业务 API、`/api/v1/ws`、`/api/v1/auth/eduplus2/exchange` 和 `/api/v1/eduplus2/*` 保持各自契约。共用业务服务不等于共用全局放行依赖。
5. **源码基线与目标入口分开**：`web/app/(admin)/admin` 是现有源码位置，复用其页面/组件后由企业前端路由组合接入 `/tms`，不把该源码引用改写为已经存在的 `tms` 目录。企业目标入口不再使用 `/admin`、`/ops` 及旧管理 API 前缀；不默认增加旧 URL 重定向，原生未适配路由不得作为旁路暴露。默认应用也必须使用 PG；本次取消 SQLite 不自动改变非企业管理页面 URL，页面改名仍按各自入口契约实施。

后续实施须同步企业路由注册、菜单/按钮链接、工作台跳转目标、前端 API client、Ingress 路由规则及 smoke/权限负例，不能只改页面标题。完整权限/菜单矩阵见 [12](12-platform-operations-admin.md)。

## 不同运行模式的发布约束

B1/B2 所有入口都必须使用可信 scope，不以是否多副本为条件。跨 Pod 订阅/重放/cancel/reply 按独立 H 工作线实现并通过 G-H 后才启用多执行者；单租户的 HA 需求也会触发，多租户本身不强制 replicas=2。
