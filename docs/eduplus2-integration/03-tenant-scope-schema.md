# 03. Tenant Scope 与身份 namespace

## 阶段定位

A1 建立固定内部 tenant 与 user ID；B1 用一个真实租户验证外部绑定及权限，B2 再开放多个租户；C1/C2 复用此边界做平台运营。**不再实施 `data/tenants` 文件型多租户过渡方案，也不通过重定义全局 admin path 偷换租户语义。**

生产隔离始终是：

```text
应用 PostgreSQL tenant_id + RLS + 用户/资源授权 + S3 对象授权
+ LightRAG workspace/数据库防线 + 缓存与任务 namespace
```

## 内外部 ID 分离

| 标识 | 来源 | 用途 |
| --- | --- | --- |
| `tenant_id` | DeepTutor 内部稳定 UUID | PG 外键/RLS、S3 key、cache/job scope；阶段一初始化后不变 |
| `user_id` | DeepTutor 内部稳定用户 ID | 资源所有权、会话、审计；本地身份绑定外部身份后不变 |
| `eduplus_tenant_id` / JWT `tid` | EduPlus2 | 外部租户身份，映射到内部 tenant；不是直接 cast 为 UUID |
| `eduplus_user_id` / JWT `eui` | EduPlus2 | 与外部 tid/provider 共同识别主体，映射内部 user |
| `eit` | EduPlus2 | 已验证激活身份；不独立授予管理员权限 |

旧讨论把 `{tid}` 同时用作外部 claim 和存储前缀，现明确废止这种歧义。**本目录生产 key 示例统一使用 `{tenant_id}/{user_id}` 表示内部 ID；认证示例中的 `tid/eui` 保留外部 claim 语义。** `eduplus2:{tid}:{eui}` 最多是外部身份显示键，不作为存储隔离机制或可变主键。

阶段一 `tenants.eduplus_tenant_id` 可为空，固定租户配置来自可信部署。阶段二通过显式、幂等、可审计绑定关联 EduPlus2 tid；已有用户也逐一确认映射，不通过同名/邮箱自动合并。新租户产生新内部 ID。不得重命名 S3 key 或重写既有用户所有权来完成接入。

## Scope 的实现归属

可信身份/资源服务位于独立 `deeptutor_enterprise` 包；core 的通用 CurrentUser/Scope/provider seam 显式传递这些字段，不能只在外壳 HTTP header 加字段却让内部继续使用全局 admin。已有 ContextVar/容器注入可复用，缺省回退、SDK/CLI 默认容器和后台执行仍须按 [13](13-deployment-and-upstream-sync.md) 收敛。

## 运行时 scope

目标上下文由认证和身份映射生成：

```text
CurrentUser
  user_id
  tenant_id
  role / permissions
  auth_provider
  eduplus_tenant_id / eduplus_user_id / identity_type（外部登录时）

ResourceScope
  tenant_id
  owner_user_id（个人资源）
  resource_kind
  resource_id

ExecutionScope
  tenant_id / user_id / request_id / turn_id / policy_version
```

- 阶段一：已认证本地用户绑定固定 tenant，客户端 tenant 参数不能覆盖部署配置。
- 阶段二：已校验外部 claims → tenant registry → identity mapping → scope；缺失、未开通、已停用一律拒绝，不回退固定 tenant。
- 阶段三：平台运营先验证具体能力和目标 tenant，再创建显式操作 scope；不能用普通用户 token + 任意 tenant 参数切换。
- HTTP、WebSocket、SDK/M2M 与持久化 job 都使用同一授权边界；ContextVar 仅为进程内传递，跨进程必须持久化并重新校验 scope。

## PostgreSQL

DeepTutor 应用租户级表从阶段一就带 `tenant_id NOT NULL`、租户复合唯一键/外键及 RLS。每次事务从可信 scope 设置事务级上下文，连接池复用不得遗留上一租户。应用连接不可是表 owner、superuser 或具有 BYPASSRLS 的角色；租户表使用 FORCE RLS。平台表/运维聚合另行最小授权，不拿平台 admin 绕过全部租户表。

RLS 只隔离租户，不自动隔离租户内用户；个人 session/KB/memory/attachment 还必须检查 owner 或显式 grant。依据见 [PostgreSQL 行安全文档](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)。

## LightRAG Server namespace

PG binding 将内部 `tenant_id/kb_id/index_version` 映射到受控 endpoint、固定 workspace 与 Secret 引用；workspace 编码使用稳定 ID、无碰撞且符合锁定版本字符约束。不同可见语料不得放入同一共享图，同名 KB 或同 URL 别名不产生隔离。原版 Server 不按请求切 workspace，默认通过受控实例池路由，不复制整套 DeepTutor。

先验证当前用户对整个 KB 的 owner/grant/策略，再下发绑定资源和操作的短期内部调用凭证；Server key 不给租户。LightRAG 独立索引表采用其 workspace schema，而非假定自带应用 tenant 列；必须补齐低权凭证绑定、数据库 RLS/图权限拒绝和迁移验证，不能只把 namespace 当 RLS。缓存/KV/vector/doc_status/graph/引用与删除共用同一 binding，详见 [06](06-postgresql-native-store-plan.md)。

## S3 namespace 与 scratch

```text
tenants/{tenant_id}/users/{user_id}/attachments/{object_id}
tenants/{tenant_id}/users/{user_id}/workspace/{object_id}
tenants/{tenant_id}/shared/kb/{kb_id}/source/{object_id}
tenants/{tenant_id}/turns/{turn_id}/outputs/{object_id}
```

对象 key 只由后端生成；bucket 私有，前缀不是访问控制的替代品。下载必须先查 PG metadata 的归属和权限，预签名 URL 短 TTL。不向租户提供可枚举 bucket 的长期凭证。

```text
scratch/{tenant_id}/{user_id}/{turn_id}/...
```

scratch 仅处理当前任务下载、解析和执行；路径编码/防穿越、清理、资源限制独立验证。正文结果持久化到 S3 后才能把任务标为成功。

## 全局 admin 调用必须显式拆分

- 平台配置：调用平台 Settings/Secret 服务。
- 租户共享 KB/设置/grants：调用显式 tenant-scoped Store。
- 个人资源：调用 owner-scoped Store。
- `PathService`：仅为本地模式或 scratch 提供路径；禁止让生产 Store 继续把路径当持久化边界。

不实施“有 tenant_id 返回租户 admin path，无 tenant_id 返回全局 data”的兼容重定向；这会让漏传 scope 隐式升级权限。生产 scope 缺失必须报错。原 `get_admin_path_service()` 的生产调用逐项替换，旧本地入口不承接企业多租户。

## 保留与不建设

保留上游已有 local/CLI 模式及只读迁移来源；不新增 tenant-local grants/profile/webhook SQLite、文件 IdentityStore 或企业 fallback 目录。开发集成测试使用 PG + S3-compatible，才能验证与生产一致的语义。

## 运行模式与隔离验收

单执行者同样必须保证 PG/对象/检索/缓存/后台任务的完整租户隔离。多执行者或高可用按独立 H 工作线实施，在实际扩容/多 worker 竞争执行前通过 G-H；它不是第二个租户才能触发的功能，也不是 B2 必须固定启用的部署模式。
