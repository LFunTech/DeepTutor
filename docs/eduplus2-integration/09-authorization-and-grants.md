# 09. 权限与 Grants 方案

## 阶段边界

阶段一完成本地认证下的用户所有权和平台敏感配置防护；阶段二完成 tenant_admin、业务权限/撤权、grants、配额、审计和本租户管理界面；阶段三复用这些服务建设统一运营后台。两类界面与完整权限矩阵见 [12](12-platform-operations-admin.md)。本期只改文档，未改变真实 DB/OpenFGA/Keycloak 状态。

## 权限实现归属

EduPlus2 权限 client、映射、grants/policy Store 与审计实现位于独立 `deeptutor_enterprise` 包；core 保留通用 permission/scope/provider，并将原管理 API、工具和后台调用接入同一授权服务。外壳登录或前端隐藏入口不足以完成替换，不通过给学校管理员签发旧全局 admin token 兼容界面。包与核心责任见 [13](13-deployment-and-upstream-sync.md)。

## 权限边界

EduPlus2 提供 ReBAC 权限模型，DeepTutor 需要把它用于租户级能力控制。前端可以根据权限隐藏 UI，但后端仍必须强制校验。

参考：<https://eduplus-test.f123.pub/docs/permission/>

## DeepTutor role 模型建议

当前只有：

```python
Role = Literal["admin", "user"]
```

建议扩展：

```python
Role = Literal[
    "platform_admin",
    "platform_operator",
    "platform_auditor",
    "tenant_admin",
    "user",
    "admin",  # legacy local mode
]
```

角色语义：

| Role | 来源 | 能力边界 |
| --- | --- | --- |
| `platform_admin` | 可信平台授权/受控应急账号 | 平台设置、Secret 引用/轮换、运营授权；无默认租户私有内容读取 |
| `platform_operator` | 可信平台授权 | 已授权租户日常运营，无 Secret/角色管理 |
| `platform_auditor` | 可信平台授权 | 只读运营用量和审计 |
| `tenant_admin` | EduPlus2 租户管理员或有对应 app 权限用户 | 当前 `tid` 下的共享 KB、授权、租户配置 |
| `user` | 教师、学生、家长等 | 当前用户资源和被授权资源 |
| `admin` | 旧本地模式 | 保持兼容，不用于 EduPlus2 tenant admin |

## EduPlus2 身份映射

基础映射：

| EduPlus2 信息 | DeepTutor 默认映射 |
| --- | --- |
| 平台运维白名单账号 | `platform_admin` |
| `eit=adm` 且通过权限检查 | `tenant_admin` |
| `eit=tch` | `user`，启用教师相关功能 |
| `eit=stu` | `user`，启用学生学习功能 |
| `eit=par` | `user`，启用家长关联学生能力 |

`eit=adm` 和 profile 仅提供身份/业务态，tenant_admin 与具体管理操作必须通过权限服务校验，不单凭身份类型放行。下方 object/relation 为拟定映射，需要核对 EduPlus2 实际契约后通过受控迁移配置，不能假设已存在。

## require_admin 的拆分

当前 `require_admin` 语义是全局 admin。多租户后建议拆分：

```python
require_platform_permission(capability)
require_tenant_member()
require_tenant_permission(relation, object)
```

阶段二直接替换所有生产管理调用，不保留旧 admin 放行旁路：

- 平台配置/治理 API 使用对应 `require_platform_permission()`，敏感能力默认仅授权 platform_admin；B2 开放跨租户治理 API 前就具备可信平台授权，不等 C1 页面。
- 租户 KB、grants、settings 使用可信 tenant scope + 对应 `require_tenant_permission()` + 资源归属/策略上限；tenant_admin 默认授予能力，自定义已授权角色也能操作，不以角色名称作唯一门槛。
- 用户自己的 session/memory/notebook 使用 `require_tenant_member()`。

## Grants 存储

当前：

```text
data/system/grants/{user_id}.json
```

阶段一即写入 PostgreSQL grants 表，以内部 `(tenant_id, user_id)` 为主键。阶段二增加外部权限映射，不建设租户 grants JSON fallback。


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

`grant` 中只保存逻辑 ID，不保存文件路径、API key、base_url、token 等敏感信息。资源 ID 使用不可复用的稳定内部 ID，名称仅展示/别名，解析必须在可信 tenant/owner scope 下完成；重命名不改变授权，删除后同名新建分配新 ID 且不继承旧 grants。KB 的 grant 绑定 kb_id 而非可变 Server 地址或 index-version，授权资源重建索引后仍通过同一 KB 的受控 binding 解析；跨 KB/租户迁移不能沿用原 grant。旧 `admin:kb:{name}` 等标识只在显式、幂等且验证归属的导入/映射中转换，不作为新企业授权主键。

## EduPlus2 权限对象映射

DeepTutor 内部资源授权使用内部 tenant/user/resource ID；调用 EduPlus2 权限服务时必须由 adapter 转换其外部 tid/eui/object 标识。不能把内部 UUID 直接写入外部关系模型，也不能假定两边 ID 相同。

| 内部对象 | 外部映射依据 | 约束 |
| --- | --- | --- |
| 内部 tenant | tenant registry 的 eduplus_tenant_id | 仅通过已验证绑定获得 |
| 内部 user | 本租户 identity mapping 的 eduplus_user_id | 外部身份按租户/provider 限定 |
| DeepTutor KB/model profile | 已登记应用资源映射 | 新 object/relation 必须先在 EduPlus2 受控配置/迁移后使用 |
| 班级/学生 | EduPlus2 外部记录 ID 与 tid | profile/组织缓存不是授权证据 |

relation/对象名称按目标 API 契约确认；具体拟新增应用能力与默认角色在 [12 权限矩阵](12-platform-operations-admin.md) 统一登记。外部规则决定业务权限，应用内 grants 不能绕过外部停用/撤权。

## 权限检查策略

| 操作 | 校验 |
| --- | --- |
| 访问自己的 session/memory/notebook | 可信内部 tenant/user scope、记录归属与操作权限一致 |
| 使用租户共享 KB | 租户/用户有效、平台及租户策略/grant 允许，再签发受限调用上下文并路由 LightRAG workspace；引用下载重验，Server key 不下放 |
| 上传/删除租户共享 KB | 本租户资源归属 + 经验证的管理/editor 权限 |
| 配置租户模型授权 | 可信 tenant scope + 模型授权管理 permission + 平台分配范围；tenant_admin 默认拥有该能力 |
| 配置平台模型凭证 | 平台敏感管理 capability，默认仅 platform_admin；Secret 引用与脱敏 |
| 查看学生/班级数据 | EduPlus2 当前权限；组织缓存只做业务态，不替代授权 |
| 开启 exec/MCP/cron | 默认拒绝，需显式租户授权和安全评估 |

## 缓存策略

权限检查可以短期缓存：

- cache key：`tenant_id + user_id + identity_type + client_id + relation + object + policy_version`
- TTL：1-5 分钟
- 管理类操作建议更短或不缓存
- Webhook 或权限变更事件到达时清理相关 cache

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

生产审计写 PG 并同步日志平台，不新增租户文件审计后端。所有运营动作记录 actor 与 target tenant，角色、授权、Secret 引用等默认数据需版本化迁移。权限 key/前端入口/API 对齐与 DB/OpenFGA/Keycloak 迁移责任见 [12](12-platform-operations-admin.md)。

## 工作包验收归属

A1 完成本地所有权/授权存储；B1 完成首租户身份到具体权限、撤权的真实闭环；B2 扩展多租户治理及现有租户管理 UI。C1 的所有运营写操作自首版就带平台角色边界和基本审计，C2 扩展运营查询/导出，不把权限与基础审计后移。多执行者下的权限缓存/额度一致性由 H/G-H 在启用该模式前验收，单执行模式也不能放松租户隔离。
