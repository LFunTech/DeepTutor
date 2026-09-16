# 03. Tenant Scope 与身份 namespace

## 阶段定位

A1 建立固定内部 tenant 与 user ID；B1 用一个真实租户验证外部绑定及权限，B2 再开放多个租户；C1/C2 复用此边界做平台运营。**不再实施 `data/tenants` 文件型多租户过渡方案，也不通过重定义全局 admin path 偷换租户语义。**

生产隔离始终是：

```text
应用 PostgreSQL tenant_id + RLS + 用户/资源授权 + S3 对象授权
+ LightRAG 的 tenant/KB/index-version/workspace 映射
+ 检索 PG 隔离 + HugeGraph scope 与独立服务端权限 + 缓存与任务 namespace
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

## 租户状态的独立来源

`tenant registry` 不能由外部同步和本地运营共同覆盖一个可写 `status`。A1 预留以下独立状态与来源版本，B1 接入外部资格，B2 开放运营 API；字段为待实现建模契约：

| 字段 | 唯一更新责任 | 规则 |
| --- | --- | --- |
| external_eligibility / external_version / verified_at | 经验证的 EduPlus2 适配器、Webhook/完整对账 | eligible/ineligible/unknown；仅可信固定单租户部署允许 not_required，客户端不能指定，外部模式不得使用 |
| local_enabled / local_version | DeepTutor 受授权的初始化/运营启停服务 | 外部事件不得覆盖本地暂停；恢复只修改本地状态并重新验证外部资格 |
| provisioning_status / provisioning_version | DeepTutor 初始化协调者，消费受控资源就绪结果 | pending/provisioning/ready/failed；业务必要资源未就绪不得标 ready，单个新 KB 等待实例不自动暂停已就绪租户 |
| status / effective_access / policy_version | 服务端派生及版本失效 | 仅供展示/执行检查，不作为三个来源都可写的状态字段 |

`effective_access = 外部资格有效 ∧ local_enabled ∧ 必要租户资源就绪`；此外仍须用户有效、资源 owner/grant 和具体操作权限。资格 unknown 或超过已确认的新鲜度窗口不得放行；固定 M1 的 not_required 只豁免外部资格，不豁免本地启停、owner 或资源检查。

每个来源独立做幂等/版本比较，拒绝旧事件覆盖；外部无可靠顺序时重新拉取权威快照核验，不按到达时间强行覆盖。外部订阅能力也与本地平台分配/租户开关分开保存，运行取交集，外部恢复不得重开本地已禁用功能。派生状态变化原子推进 policy_version，并通知缓存/WS/后台任务失效。

实施时字段、约束、来源版本及旧状态回填走 DeepTutor 版本化 migration/dry-run/verify：保留现有本地暂停；外部资格无可信证据置 unknown，不从旧 active 推断已获外部许可；M1→B1 切换不得携带 not_required 旁路。此轮仅改方案，不执行 DB 或外部身份系统迁移。

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

## RAG provider namespace

PG binding 将内部 `tenant_id/kb_id/index_version` 映射到 provider、受控 endpoint、固定 workspace、服务契约版本、受控检索部署引用与 LightRAG API Secret 引用。企业首发 provider 为 `lightrag-server`，使用固定 workspace Server 实例池；编码稳定、无碰撞且符合锁定版本字符约束。既有其他 provider 的绑定不由默认值强改。不同可见语料不得混入同一可相互遍历的逻辑图；允许共享物理 HugeGraph graph 的前提是独立 scope、服务端 ACL 与遍历范围均通过隔离验证，同名 KB 或同 URL 别名不产生隔离，不复制整套 DeepTutor。

先验证当前用户对整个 KB 的 owner/grant/策略，再下发绑定资源和操作的短期内部调用凭证；远端 key 不给租户。LightRAG API key 不等于个人默认私有授权，workspace 也不等于应用 tenant 列。由所选 fork 及其部署运维补齐检索低权身份绑定、PG RLS/写检查及 HugeGraph 服务端权限拒绝和受控迁移验证；缓存/文本块/向量/状态/图/引用与删除共用同一 binding，详见 [06](06-postgresql-native-store-plan.md)。

HugeGraphStorage 将 workspace + storage namespace 编码为 scope，逻辑分区不是 ACL，也不会使固定 workspace Server 获得动态多租户路由。按 KB 授权边界划分 graph/受限身份或验证共享 graph 资源 ACL，禁止把租户内个人 KB 因共用 tenant 账号而公开；graphspace 可用性依目标存储部署验证，不强制每租户一个 graphspace。M1/G1 就覆盖双租户、同租户双用户、同名实体、跨库遍历/删除、直连 REST/Gremlin 越权负例，M2/G2 再复验真实外部身份及治理。

LightRAG 部署配置负责 workspace→检索 PG/HugeGraph scope 的物理映射和存储凭证，DeepTutor 只持有服务级 binding，不保存/解析 graph locator 或直连图数据库。上述直连存储负例属于 LightRAG 侧隔离测试；DeepTutor 通过服务 API 验证授权、检索和错误闭环，且其工作负载无 HugeGraph 网络访问及检索 PG 数据库权限；应用/检索 PG 共集群时不要求不同 TCP 地址。

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
- `PathService`：不得提供 SQLite 运行库或以路径推断数据库归属；企业仅用于受控 scratch/只读资源，普通已有文件载荷遵守各域契约，不能混淆 PG-only 与 A2 文件替换。

不实施“有 tenant_id 返回租户 admin path，无 tenant_id 返回全局 data”的兼容重定向；这会让漏传 scope 隐式升级权限。生产 scope 缺失必须报错。原 `get_admin_path_service()` 的生产调用逐项替换，旧本地入口不承接企业多租户。

## 保留与不建设

用户已取消无 PG 的 local/SQLite 模式；保留连接 PG 的默认 Web/CLI/SDK、本机部署以及独立只读旧格式导入。不新增 tenant-local grants/profile/webhook SQLite、文件 IdentityStore 或企业 fallback 目录。开发业务测试必须使用 PG，企业集成另需 HugeGraph + S3-compatible。

## 运行模式与隔离验收

单执行者同样必须保证 PG/对象/检索/缓存/后台任务的完整租户隔离。多执行者或高可用按独立 H 工作线实施，在实际扩容/多 worker 竞争执行前通过 G-H；它不是第二个租户才能触发的功能，也不是 B2 必须固定启用的部署模式。
