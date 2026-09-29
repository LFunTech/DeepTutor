# 09. 权限与 Grants 方案

## 阶段边界

阶段一完成本地认证、owner/grant、基础审计、对象额度/必要限流、PG/图/S3 隔离和平台敏感配置防护；阶段二完成外部身份/学校状态核验、DeepTutor Enterprise 程序按 PG 事实执行的双应用域权限与撤权、学校管理员的**本校**资源治理及学校管理界面；阶段三复用安全组件建设独立 OMS。跨校服务授权、供给与额度写入仅归 OMS，TMS 只读本校额度及消耗。两类界面与完整权限矩阵见 [12](12-platform-operations-admin.md)。本期只改文档，未改变真实 DB/OpenFGA/Keycloak 状态。

### 当前实现状态（2026-09-17）

`enterprise-eduplus2-federated-access` 已在企业包内完成普通第三方调用所需的 JWT exchange、client/app/tenant resolve、短期 `dt_token`、owner/resource guard、可选 profile/permission snapshot、WS refresh 和审计查询/导出。该切片只计算普通 DeepTutor 能力边界，不授予 TMS、OMS、ops 或平台角色能力；学校管理员也不会因此映射成全局 admin。

前置应用仍负责用户打开、refresh 和周期合法性校验。DeepTutor 当前 repo 负责自身信任边界：签名/claims/registration/resolve、短期 token、HTTP/WS/SDK owner guard、可选 profile/permission/webhook fail closed 和审计证据。

## 权限实现归属

EduPlus2 在本产品权限链路中只提供认证与稳定身份识别；学校 lifecycle Webhook 另作业务状态输入，不提供 `ops.*`/`tenant.*` 许可。智能体基座两套**本产品应用权限**由 `deeptutor_enterprise` 程序统一判定，各自使用独立会话和 API；企业 PG 仅保存主体、角色/授权、版本与审计事实，PG 用户/GRANT/RLS 不代替逐请求程序鉴权。core 只保留通用 permission/scope/provider seam。首次登录默认零权；OMS 仅管理平台人员；TMS 首位学校管理员由真实订阅事件 actor 在 Webhook 接收事务内即时开启，此后仍由 TMS 管理本校授权。签名真实 `subscription.created.actor.user_id`（按 EduPlus2 文档作为后续 OIDC `sub` 匹配候选）按本产品策略提供首位管理员主体；不经签名事件与一次性栅栏不产生可用管理员权限，mock/system/null 时写入口关闭，不能以外部 `eit=adm`、旧全局 admin 或前端隐藏入口替代。目标见 [`add-enterprise-management-authorization`](../../openspec/changes/add-enterprise-management-authorization/proposal.md)，包与核心责任见 [13](13-deployment-and-upstream-sync.md)。

## 权限边界

EduPlus2 的 ReBAC 仅在其自身业务范围内使用；不消费它作为智能体基座 OMS/TMS 的授权决策。DeepTutor 的两应用域权限由本仓库 Enterprise 服务按 PG 版本化事实维护并判定。前端可以根据服务端动作摘要隐藏 UI，但后端仍必须逐动作、范围和版本强制校验。

参考：<https://eduplus-test.f123.pub/docs/permission/>

## 注册、登录与被调用方授权边界

DeepTutor 不维护用户注册能力，也不把“第三方系统已经登录”直接等同于可调用 DeepTutor：

- 普通用户、学校、组织、身份和账号生命周期由 EduPlus2 负责；DeepTutor 只保存经验证的内部映射、会话、资源授权和审计。
- 只有独立部署的 TMS、OMS 需要交互式登录；两者各自建立会话，TMS 按 `tenant.*`，OMS 按本产品 `ops.*` 具体能力鉴权，不复用普通租户换票。
- 第三方应用调用 DeepTutor 时必须先完成 EduPlus2 JWT exchange，DeepTutor 依据已注册 active client/app、JWT `tid/eui/azp`、租户状态和能力策略判断是否放行；`aud` 只做兼容或附加校验，不作为主依赖。
- `client_id` 是授权和审计维度；不能只凭用户 JWT 中的租户成员关系直接调用能力。
- DeepTutor 可做 JIT binding，但 JIT binding 只创建内部映射，不授予超出外部身份、注册 app 策略和本地 grants 的权限。

## OMS/TMS 角色与身份映射（目标，非当前已开放）

当前 core `Role = Literal["admin", "user"]` 属旧本地模式，不能直接扩展为可信的企业管理权限来源。企业 PG 按 `(issuer,sub,application)` 存版本化主体、角色模板、动作和 assignment：OMS `platform_security_admin`、`platform_config_admin`、`platform_operator`、`platform_auditor`；TMS `school_admin`、`school_operator`、`school_auditor`。模板不自动赋予首次登录者；操作必须同时满足当前应用域、具体动作、有效 assignment、`platform` 或已核验目标 `school`、账号/学校状态和撤权版本。敏感成本、Secret、导出及 TMS 学校侧开通分别分权，角色名只是已授动作集合的展示；授权治理动作与可授予动作/范围的显式委托上界分离，委托能力不等于业务执行权。

`eit=adm`、教师/学生/家长身份和外部 profile 可辅助身份/业务态展示，但不能自动生成 `tenant.permissions.manage`、`ops.*` 或全局 `admin`。OMS 与 TMS 会话不能互换；TMS 只在当前可信学校内授权。OMS 不列出、创建或审批任何学校账号；首位管理员由签名真实 `subscription.created.actor.user_id`（按 EduPlus2 文档作为后续 OIDC `sub` 匹配候选）在 Webhook 接收事务内由 Enterprise 程序即时开启；mock/system/null 不授予权限。后续 TMS 自主管理角色与成员，不得自授或撤销最后一名可用管理员。

## require_admin 的拆分

当前 `require_admin` 语义是全局 admin。多租户后建议拆分：

```python
require_platform_permission(capability)
require_tenant_member()
require_tenant_permission(relation, object)
```

阶段二直接替换所有生产管理调用，不保留旧 admin 放行旁路：

- 平台配置/治理 API 使用对应 `require_platform_permission()`，先验证外部身份当前有效、再查 DeepTutor 当前 `ops.*` 动作和目标学校授权；敏感能力仅可向经受控登记且具对应动作/范围的主体显式授予，不因模板名称自动获得。B2 开放跨学校治理 API 前须具备本仓库版本化权限迁移与撤权门禁，不等 C1 页面。
- 学校 KB、grants、settings 使用可信 school/tenant scope + 对应 `require_tenant_permission()` + 资源归属/策略上限；学校管理员必须有显式授予的本产品 `tenant.*` 动作，不能因 `eit=adm` 或角色名称默认放行。
- 用户自己的 session/memory/notebook 使用 `require_tenant_member()` **加可信 tenant/user scope、记录 owner 与操作权限检查**；仅资源本身已支持共享时才接受显式 grant。成员身份不等于所有权，不能省略 owner-scoped Store 校验。

同租户两用户必须在 HTTP/WS、列表/详情/搜索/导出、agent 工具、SDK 和后台 job 的已启用路径验证猜测资源 ID 被拒绝；tenant_admin 或平台运营身份不默认读取个人内容。本人正例、已支持共享资源的 grant 正例与撤权负例一并验收，不因此新增个人资源共享功能。

## Grants 存储

当前：

```text
data/system/grants/{user_id}.json
```

阶段一即写入 PostgreSQL grants 表，以内部 `(tenant_id, user_id)` 为主键。阶段二增加外部身份/学校映射与本产品应用权限版本，不建设租户 grants JSON fallback。

grant 内容保持逻辑资源，不写 secret/path：

```json
{
  "version": 3,
  "tenant_id": "<internal-tenant-uuid>",
  "user_id": "<internal-user-id>",
  "models": { "llm": [] },
  "knowledge_bases": [],
  "skills": [],
  "partners": [],
  "enabled_tools": null,
  "mcp_tools": null,
  "exec_enabled": null
}
```

## Resource ID 建议

```text
tenant:{tenant_id}:kb:{kb_id}
tenant:{tenant_id}:user:{user_id}:kb:{kb_id}
tenant:{tenant_id}:skill:{skill_id}
tenant:{tenant_id}:persona:{persona_id}
tenant:{tenant_id}:model-profile:{model_profile_id}
```

`skills` 仅用于本校自有/其他需要成员分配的 Skill，不用于对已获 OMS 学校授权的 global Skill 做 TMS 二次分配。`grant` 中只保存逻辑 ID，不保存文件路径、API key、base_url、token 等敏感信息。资源 ID 使用不可复用的稳定内部 ID，名称仅展示/别名，解析必须在可信 tenant/owner scope 下完成；重命名不改变授权，删除后同名新建分配新 ID 且不继承旧 grants。KB 的 grant 绑定 kb_id 而非可变 Server 地址或 index-version，授权资源重建索引后仍通过同一 KB 的受控 binding 解析；跨 KB/租户迁移不能沿用原 grant。旧 `admin:kb:{name}` 等标识只在显式、幂等且验证归属的导入/映射中转换，不作为新企业授权主键。

个人 KB 默认私有，租户管理员的共享 KB 管理能力不自动授予他人私有 KB 读取权。DeepTutor binding 只引用 LightRAG 服务/workspace 及其 API 凭证；HugeGraph scope/graph locator 与存储凭证归 LightRAG 部署运维管理，不进入应用 binding、grant 或用户请求。网关校验 owner/grant 后只解析服务绑定，LightRAG 数据面身份仍限制在 KB 授权范围。M1/G1 验证同租户两用户、双租户、撤权缓存/引用及受限图身份直接 REST/Gremlin 越权拒绝，不能推迟到外部登录完成。详见 [06](06-postgresql-native-store-plan.md)。

## 外部身份与内部授权对象映射

外部稳定 `(issuer,sub)` 与已核验学校 ID 映射到 DeepTutor 内部主体/学校；名称、`school_code`、`tid/eui/eit` 不能作为 OMS 平台授权或 TMS 管理授权凭据。EduPlus2 不存本产品 `ops.*`/`tenant.*` relation。内部角色、范围、成员/应用/服务使用 grant 和 owner 事实只留企业 PG，并使用版本栅栏即时撤权；账号/学校停用时写入失败关闭。OMS 学校权益授权是 TMS 服务访问 grant 的上界，TMS 授权不能扩展额度或读取私有正文。

## EduPlus2 client/app 注册授权

外部 client/app 注册是第三方调用 DeepTutor 的前置授权，不是用户注册。DeepTutor 侧依赖 EduPlus2 提供通用 `POST /api/v1/open/oauth-clients/resolve` 能力按 `client_id` 解析权威 app/tenant/status 元数据；该接口需求草案见 [EduPlus2 通用 OAuth Client Resolve API 需求建议](eduplus2-oauth-client-resolve-api-proposal.md)。

| 场景 | 规则 |
| --- | --- |
| TMS 注册 client | 当前 TMS 租户锁定为登录用户所在内部 tenant；管理员输入 `client_id` 后，DeepTutor 调 EduPlus2 通用 resolve API 并取得权威 `external_tenant_id/external_app_id/app_name/tenant_name/status`；`external_tenant_id` 必须与当前租户绑定完全一致，否则拒绝。 |
| OMS 查询 client | OMS 仅凭 `ops.clients.read` 和已核验学校范围读取脱敏的 client/app 注册状态；不注册、注销、暂停 TMS client，也不因查询自动进行 tenant provisioning。 |
| 普通第三方调用 | 不访问 TMS/OMS；只通过 `POST /api/v1/auth/eduplus2/exchange` 静默换票，再按 client/app 策略、用户 owner/grant 和能力 allowlist 使用 DeepTutor。 |

同一个 EduPlus2 租户下同一个应用只能有一个 active client 注册。应用唯一性必须使用 EduPlus2 返回的权威应用 ID（如 `external_app_id` / `app_code` / `canonical_app_id`），不能只靠可变 `app_name`。

推荐约束：

```sql
UNIQUE (provider, client_id) WHERE status = 'active';
UNIQUE (provider, external_tenant_id, external_app_id) WHERE status = 'active';
UNIQUE (provider, internal_tenant_id, external_app_id) WHERE status = 'active';
```

如果 `(tenant=A, app=alpha, client_id=client-001, status=active)` 已存在，则禁止再注册 `(tenant=A, app=alpha, client_id=client-002, status=active)`；只有先将旧记录 `revoked/retired` 后，才允许注册新 client。

建议表模型：

```text
external_client_registrations(
  id, provider, internal_tenant_id, external_tenant_id, external_tenant_name,
  client_id, external_app_id, external_app_name, external_app_code,
  status, registered_by_type, registered_by_user_id, registered_at,
  revoked_at, revoked_by_user_id, revocation_reason,
  last_verified_at, metadata_snapshot
)
external_tenant_bindings(internal_tenant_id, provider, external_tenant_id, external_tenant_name, status, created_at, updated_at)
external_user_bindings(internal_tenant_id, internal_user_id, provider, external_tenant_id, external_user_id, identity_type, status, created_at, updated_at)
```

## 权限检查策略

| 操作 | 校验 |
| --- | --- |
| 访问自己的 session/memory/notebook | require_tenant_member + 可信 tenant/user scope + owner/该资源已支持的显式 grant + 操作权限；RLS/成员身份均不能单独放行 |
| 使用租户共享 KB | 租户/用户有效、平台及租户策略/grant 允许，再签发受限调用上下文并路由已选 provider 的受控远端 KB/workspace；引用下载重验，Server key 不下放 |
| 上传/删除租户共享 KB | 本租户资源归属 + 经验证的管理/editor 权限 |
| 配置本校成员/应用模型使用 grant | 可信 tenant scope + 成员/应用授权管理 permission + OMS 已授服务范围；显式获 `tenant.access.manage` 的本校管理员可管理使用 grant，但不能增加 OMS 服务授权或额度 |
| 配置平台模型凭证 | `ops.credentials.manage` + `platform` 范围，默认仅受控 platform_admin 应用模板；Secret 引用与脱敏 |
| 查看学生/班级数据 | EduPlus2 当前权限；组织缓存只做业务态，不替代授权 |
| 开启 exec/MCP/cron | 默认拒绝，需显式租户授权和安全评估 |
| TMS 注册/注销 EduPlus2 client | 当前 tenant scope + `tenant.clients.manage` + EduPlus2 校验结果 tenant 完全一致 + client/app 唯一约束 |
| OMS 查询 EduPlus2 client/app | DeepTutor OMS `ops.clients.read` + 已核验学校范围，仅脱敏只读；注册/注销仍由当前学校 TMS 管理 |
| 第三方 token exchange | EduPlus2 JWT 验签 + active client registration + tenant/app/client 状态 + 用户映射；失败 fail closed |
| 外部能力调用/start_turn | `dt_token` + tenant/user/client policy + owner/grant + capability allowlist；不接受请求体覆盖 tenant/user/client |

## 缓存策略

普通能力的非管理读路径可使用带 `policy_version` 的短 TTL 缓存；OMS/TMS 管理写、导出和敏感读取须使用当前 PG 授权决策，不以旧会话或异步 Webhook 失效作为正确性前提。缓存键至少包含应用域、主体、目标学校、动作、资源和授权版本；本地撤权提交后旧版本不得再用于写入。

## 审计

所有管理类操作记录：

```json
{
  "tenant_id": "<internal-tenant-uuid>",
  "actor_user_id": "<internal-user-id>",
  "actor_role": "tenant_admin",
  "action": "grant.update",
  "resource_id": "tenant:<internal-tenant-uuid>:user:<target-user-id>",
  "timestamp": "...",
  "request_id": "..."
}
```

生产审计写 PG 并同步日志平台，不新增租户文件审计后端。所有运营动作记录 actor 与 target tenant，角色、授权、Secret 引用等默认数据需版本化迁移；OMS/TMS 本产品应用权限均只迁移 DeepTutor 企业 PG，不修改 EduPlus2/OpenFGA/Keycloak；若缺外部身份/学校接口，由所属团队独立交付，写路由保持关闭。权限 key/前端入口/API 对齐见 [12](12-platform-operations-admin.md)。

EduPlus2 对接新增审计事件至少包括：

| action | 必要字段 |
| --- | --- |
| `eduplus2.client.register` / `eduplus2.client.revoke` | `source=tms`、`actor_user_id`、`internal_tenant_id`、`external_tenant_id`、`external_tenant_name`、`client_id`、`external_app_id`、`external_app_name`、`result`、`request_id`；OMS 仅查询并记录独立读取审计 |
| `eduplus2.token.exchange` | `client_id`、`external_app_id`、`external_app_name`、`external_tenant_id`、`external_tenant_name`、`internal_tenant_id`、`internal_user_id`、`result`、`request_id` |
| `turn.start` | `request_id`、`client_id`、`external_app_id`、`internal_tenant_id`、`internal_user_id`、`session_id`、`turn_id`、`capability`、`result` |

日志和审计禁止记录 access token 原文、refresh token、client secret、模型 API key、完整私密聊天正文或可复用签名 URL。

## 工作包验收归属

A1 完成本地所有权/授权存储；B1 完成首租户身份到具体权限、撤权的真实闭环；B2 扩展多租户治理及独立 TMS。OMS 的 C1 可先交付真实受权只读，C2 再接完整写动作；任何提前开放的写 API 仍必须先完成平台身份、本产品权限、版本与审计门禁，不能以界面阶段延后安全。多执行者下的权限缓存/额度一致性由 H/G-H 在启用该模式前验收，单执行模式也不能放松租户隔离。
