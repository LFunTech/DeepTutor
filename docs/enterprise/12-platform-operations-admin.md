# 12. 租户管理界面与统一运营管理后台

## 已确认范围

管理体系不是“把所有人放进同一个超级 Admin”：

- **阶段二：TMS 租户管理系统 `/tms`**，基于现有 DeepTutor 管理界面微调获得每租户自管理体验；M1 已有管理功能在该目标入口服务固定租户。
- **阶段三：OMS 平台运营管理系统 `/oms`**，面向平台人员管理所有租户；OMS 不指订单管理系统。

两者共用资源服务、权限判定及数据底座，但入口、菜单、可操作对象和权限边界分开。不为每租户复制代码或部署，不重建 EduPlus2 用户、学校、组织、身份及授权主数据后台。

## 外壳与前端交付边界

企业包/外壳不等于 iframe 套上原站就完成租户化。`web/app/(admin)/admin` 是现有源码路径，企业前端复用页面/组件并接入目标 `/tms`，不是声称上游已有同名目录。B2 对 tenant 标识、角色/能力字段、导航与资源请求做必要通用接入；原用户体验与完整后端能力同批验收。不为追求上游前端零 diff 复制整套页面、伪造全局 admin 或只用 CSS 隐藏敏感入口。

C1/C2 运营模块可以位于独立企业 UI 构建，通过受控路由挂到 `/oms`，或与企业前端组合发布；这只是构建边界，不创建第二套 grants/policy/审计数据库。两类界面调用同一 `deeptutor_enterprise` 治理服务，后端强制权限与资源范围；拟定包布局见 [13](13-deployment-and-upstream-sync.md)。

## 两类界面

| 维度 | 租户管理界面 | 统一运营后台 |
| --- | --- | --- |
| 阶段 | 二 | 三 |
| 基础 | 现有 `web/app/(admin)/admin` 等管理页面复用 | 新增运营模块；可复用表格/表单组件，不复用全局 admin 放行逻辑 |
| 目标入口 | `/tms`，上下文锁定当前租户 | `/oms`，平台角色专用 |
| 专属管理 API | `/api/v1/tms/*` | `/api/v1/oms/*`；B2 先交付必要治理 API |
| 用户 | `tenant_admin` 及获具体权限的自定义角色 | `platform_admin`、`platform_operator`、`platform_auditor` |
| 管理对象 | 本租户共享 KB、grants、允许的模型/工具、配置、用量 | 全部租户、开通/停用、模型及功能分配、配额、聚合用量、审计、系统任务 |
| 禁止 | 跨租户访问、平台 Secret、平台角色授予 | 默认查看私有对话/附件、静默冒充用户、编辑 EduPlus2 主数据 |

路由、API 和权限 key 是拟定契约，不表示当前已有接口。TMS/OMS 仅统一企业入口命名，原 `tenant.*` / `ops.*` 能力 key 和角色语义不变；通用业务 API 不整体搬入管理前缀。完整命名、M1 固定租户边界与旧路由约束见 [11](11-api-and-entrypoints.md)。

## B2：现有租户界面微调清单

1. 导航、工作台跳转与管理页子路由统一指向 `/tms`，专属管理请求使用 `/api/v1/tms/*`；导航/页头展示当前租户，菜单数据、表格请求、资源选择器均只取当前 tenant。首页按已有管理能力展示入口，不把 KB 权限作为所有管理角色的共同前置。KB 页面通过企业文档服务展示已选 RAG 的真实导入/索引失败和重试状态，托管删除与外部连接解绑明确区分；不跳转原始 Server 管理页绕过权限。
2. 保留现有用户资源授权、共享 KB、配置等交互，移除平台凭证、全部租户列表和全局配置入口。
3. EduPlus2 用户/组织只展示必要同步字段；DeepTutor 只编辑应用内 grants，不创建第二套用户密码/学校组织管理。自有密码账号仅用于受控固定租户 PG 身份模式，不保留 SQLite/local 认证回退。
4. 已有 API 从 `require_admin` 拆成 scope 与具体 permission 判定；不得仅改前端菜单。
5. 保存成功后配置与实际 runtime 一致，多副本缓存按版本失效；禁止页面写文件而 worker 仍读旧状态。
6. 租户管理员默认可管理自己租户；自定义角色按显式能力出现菜单，不以 `eit=adm` 单字段授予平台权限。

## C1/C2 分批交付边界

| 工作包 | 范围 | 完成要求 |
| --- | --- | --- |
| C1：运营管理闭环 | 角色/入口、全租户目录、开停、模型/功能/配额、Secret 引用/轮换、基本操作审计 | G3a；真实运行策略生效，租户/平台权限完整；可先发布运营基础版 |
| C2：运营治理完善 | 用量/费用估算、资源/错误概览、任务/同步状态、重试/取消、高级审计查询与导出 | G3；C1+C2 全部完成才标记 M3，不因 C1 可用而删去 C2 |

B1 先完成首租户最终身份/权限/撤权闭环，B2 完成各租户自己的管理 UI 和治理后端。B2 的跨租户治理 API 已具备可信平台授权、目标租户校验及审计，C1 复用并完善运营角色/默认授权，而不是首次建立安全边界。C1 复用 B2 API；C2 可以在 C1 契约稳定后并行开发，但所有写操作的基本审计、鉴权不得推迟。任务取消/重试在当前运行模式下必须有效，多执行者时还需先通过 H/G-H。

## 运营功能域（完整范围保留）

| 功能 | 操作与要求 |
| --- | --- |
| 租户目录 | 按内部 ID/外部 tid、名称、状态检索；分页、详情；只列授权范围的租户管理元数据 |
| 生命周期 | 展示外部资格、本地启停、初始化状态及派生 provisioning/active/suspended/failed；来源独立更新、初始化幂等、审计/失败重试，不提供一键物理删库/删 bucket |
| 策略与配额 | 模型白名单、功能开关、并发/token/存储额度；版本化更新、并发冲突提示，复用阶段二执行检查 |
| 模型与凭证 | 平台模型目录、供应商配置、Secret 引用和受控轮换；区分 desired/active 版本，由对应执行方确认生效/排空/失败回退，见 [07](07-resource-isolation.md#模型-secret-轮换的生效与失败契约)；API 不回传明文，不向整个后台授予 Kubernetes cluster-admin |
| 用量 | 租户/时间维度 token、请求、对象/索引/图容量、导入/查询并发与失败率；远端模型成本单列，费用估算不冒充计费结算系统；不展示私有实体/正文或增加通用 Gremlin 控制台 |
| 运行治理 | 导入/同步/Webhook/turn 状态，含索引版本、图写不确定/待恢复与成套恢复结果；授权后的重试/取消遵守 06 的停写/对账约束，不以普通按钮清 pending fence 或重启绕过，不重复执行已完成操作 |
| 审计 | 操作者、平台角色、目标租户、动作、资源、脱敏变更摘要、结果、request ID、时间；只读导出单独授权 |

## 权限矩阵：入口到后端必须闭环

以下 `ops.*` / `tenant.*` 是 DeepTutor 拟新增能力 key，不声称 EduPlus2 已有同名 relation。对接时映射现有 EduPlus2 权限；缺失能力通过其版本化 OpenFGA/角色迁移补齐。DeepTutor 使用 FastAPI dependency/权限服务，不照搬其他仓库的 Java 注解。

| 入口 / API（拟定） | 后端校验 | 能力 key / 外部权限映射 | 默认授权角色 | 前端入口 key |
| --- | --- | --- | --- | --- |
| `/tms` 下的 KB 管理入口、`/api/v1/tms/kbs` | 已认证、当前 tenant、`require_tenant_permission`、资源归属 | `tenant.kb.manage` → 租户资源管理权限 | 本租户 `tenant_admin`；显式授权自定义角色 | `tenant.kb.manage` |
| 本租户授权/模型配置 | 当前 tenant、禁止越过平台分配范围 | `tenant.grants.manage` | 本租户 `tenant_admin`；显式授权自定义角色 | `tenant.grants.manage` |
| `/oms` 下的租户目录入口、`GET /api/v1/oms/tenants` | `require_platform_permission` | `ops.tenants.read` → 平台角色/能力 | admin/operator/auditor | `ops.tenants.read` |
| 租户开通/暂停/恢复 API | 平台权限、目标租户校验、状态机、幂等 | `ops.tenants.manage` | admin/operator | `ops.tenants.manage` |
| 租户模型/配额 API | 平台权限、限额、版本校验 | `ops.policy.manage` | admin/operator（仅已授权日常范围） | `ops.policy.manage` |
| 平台 Secret 引用/轮换 API | 平台敏感操作权限、确认、审计 | `ops.credentials.manage` | admin | `ops.credentials.manage` |
| 运营账号/角色授权 API | 平台角色管理权限，禁止自助提权 | `ops.roles.manage` | admin | `ops.roles.manage` |
| 用量/审计 API | 平台只读权限，导出独立授权 | `ops.usage.read` / `ops.audit.read` | admin/operator/auditor | 同后端能力 key |
| 任务重试/取消 API | 平台操作权限、目标 tenant/job/实际 cancel_scope 绑定；无文档级能力拒绝扩大到 workspace | `ops.jobs.manage` | admin/operator | `ops.jobs.manage` |

“admin/operator/auditor”在本表分别指 `platform_admin/platform_operator/platform_auditor`。平台角色通过可审计的可信授权维护，不能由学校管理员身份、任意客户端 claim 或本地用户名自动推导。M2M 运维调用也受相同 scope/permission 限制。

## 租户生命周期与策略生效

按 [03 独立状态来源](03-tenant-scope-schema.md#租户状态的独立来源) 保存外部资格、本地启停和初始化状态。`provisioning/active/suspended/failed` 是派生展示，不是外部同步与运营共写的字段。

```text
外部资格有效 ∧ local_enabled ∧ 必要租户资源就绪 → 允许业务准入
```

- 开通：校验 EduPlus2 应用资格，幂等建内部 tenant、默认策略和授权；必要资源就绪才 active。DeepTutor 不能自行把 EduPlus2 已停订租户标为可用。
- 停用：拒绝新登录/新 turn/下载授权/后台派发；对已有 WS/运行任务发撤销并在权限检查点终止，不删除历史。已签发直传/下载 URL 最长存活到短 TTL；要求即时撤权的内容使用后端代理，不承诺 presigned URL 可即时撤销。
- 恢复：只修改本地启停状态；重新验证外部资格和策略，版本比较并重算最终准入。外部资格无效/未知或资源未就绪时不能显示已可用；外部 active/完整同步也不能覆盖本地暂停，更新版本使各 Pod 缓存失效。
- 配额修改：复用 [07 的两侧模型/预算执行契约](07-resource-isolation.md#聊天模型与检索模型分离)，区分策略保存、检索 profile 发布/重建与实际生效版本；业务 PG 记账，LightRAG 执行内部限额。本地取消/超时不直接释放远端预留，缺用量显示待核算；阶段三不能只改显示数字。

### 任务操作与基础设施运维分开

OMS 复用 [06 的业务/远端任务契约](06-postgresql-native-store-plan.md#业务任务远端索引与取消边界)，分别显示业务状态、远端观察状态/时效、取消意图/确认和用量核算。`cancel_requested` 不显示“已停止”，取消不等于撤销已索引内容；不支持文档级取消时明确不可执行，不能扩大为整个 workspace，C2 必需能力仍待服务适配验收后才可完成。

`ops.jobs.manage` 仅覆盖已授权 job 的实际操作范围，不授予整 workspace 停止、实例销毁、检索队列管理或图屏障恢复权。KB 页面只展示资源申请/绑定结果；池补充、部署/Secret 和回收走独立运维，池耗尽/半开通不得靠普通后台直调 Kubernetes 修复。

## 数据与越权边界

运营列表使用最小化平台元数据/聚合视图；租户资源操作先校验平台能力、显式绑定目标租户，再用受 RLS 约束的事务执行。不对普通请求开放任意 tenant override 或 BYPASSRLS 连接。

租户用户继续依赖已验证身份 scope；URL/body 的租户 ID 不是授权证据。运营人员无默认私有内容读取或冒充登录能力；如将来需要支持访问，另立审批、授权、时效、用户告知及审计方案，不能在本期用“超级 admin”绕过。

OMS 的图容量/待恢复信息来自 LightRAG 受控状态或运维观测结果，只展示必要元数据；`ops.jobs.manage` 仍仅授权服务级任务操作，不授予图凭证、直连 Gremlin 或图屏障恢复权。LightRAG 内部维护由独立运维身份/流程完成，不在 DeepTutor 中另建图管理后端。

## 状态迁移与运维边界

- **本次文档修改**：同步六类职责边界、租户分源状态与私有资源鉴权，保留 TMS/OMS 目标 URL、角色/能力 key；不修改 DB、OpenFGA、Keycloak 运行态，不新增可执行 migration。后续若实际修改已注册的工作台目标或 redirect 白名单，再走所属系统受控流程；不因 URL 改名自动迁移角色数据。
- **后续 DeepTutor DB**：租户生命周期、策略版本、运营角色默认数据和审计结构走版本化迁移 Job；已存在用户/角色映射需显式回填与验证；租户分源状态回填保留本地暂停、未知外部资格拒绝放行，不从旧 active 推断外部许可。
- **后续 EduPlus2**：只有新增 relation/tuple/client/scope/redirect 等才需要对应 OpenFGA/Keycloak provider migration；由 EduPlus2 仓库受控流程负责，不用手工改库或启动脚本替代。
- **验证闭环**：迁移 dry-run/apply/verify、重复执行幂等和 drift 检查；默认管理员、自定义角色正例及 403 负例；菜单/路由/按钮/API 对齐。

## 验收

以 [02 的 G2/G3](02-rollout-testing-and-migration.md) 和 [OpenSpec platform-operations](../../openspec/changes/replace-rollout-with-three-production-stages/specs/platform-operations/spec.md) 为准。至少验证 `/tms`、`/oms` 导航/深链接与各自 API 前缀一致，默认管理员/获授权自定义角色可达、无权限直调返回 403；租户管理员不能访问运营 API、auditor 不能写、operator 不能管理 Secret/角色、admin 正常操作，以及管理变更确实影响运行时。旧前缀和原生未适配路由不得成为鉴权旁路。
