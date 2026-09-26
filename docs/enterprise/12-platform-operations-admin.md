# 12. 租户管理界面与统一运营管理后台

## 已确认范围

管理体系不是“把所有人放进同一个超级 Admin”：

- **阶段二：TMS 租户管理系统 `/tms`**，基于现有 DeepTutor 管理界面微调获得每租户自管理体验；M1 已有管理功能在该目标入口服务固定租户。
- **阶段三：OMS 平台运营管理系统 `/oms`**，面向普通运营人员查询跨租户治理状态、Token 明细和费用，并办理授权计费事项；OMS 不指订单管理系统，也不是租户开停或供应商配置控制台。

> 2026-09-25 权责修订：`openspec/changes/add-c1-oms-operations-prototype/` 及六个实施 change 是本页 OMS 目标契约的现行来源。租户生命周期开停与欠费模型使用限制是不同状态：前者按 EduPlus2 租户 webhook 执行全入口准入，后者按独立模型资格 webhook **仅限制实际模型调用**，登录、管理和历史查询继续可用。Provider 全服务维护属于 DeepTutor 独立平台设置；OMS 治理只读、计费可按细粒度权限写。

两者共用资源服务、权限判定及数据底座，但入口、菜单、可操作对象和权限边界分开。不为每租户复制代码或部署，不重建 EduPlus2 用户、学校、组织、身份及授权主数据后台。

### 当前实现状态（2026-09-17）

TMS 与 OMS 仍未实现。当前已交付的是无 TMS/OMS 的 EduPlus2 API-only 联邦访问切片，以及独立的 EduPlus2 审计查询/导出页面 `/enterprise/audit/eduplus2`。该页面只用于查看/导出脱敏 exchange、refresh、resolve、profile/permission、revocation 与 authz denied 等审计证据，不代表 `/tms` 或 `/oms` 已具备导航、角色、菜单、client 注册治理或租户/运营管理能力。

后续 TMS/OMS 仍需分别按 B2、C1/C2 建设；不得把当前审计导出 UI 或 API-only exchange 当作 TMS/OMS 的替代。

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
| 管理对象 | 本租户共享 KB、grants、允许的模型/工具、配置、用量 | 跨租户状态只读查询、租户/用户 Token 明细与费用、授权单价/成本/欠费处理、只读审计/任务 |
| 禁止 | 跨租户访问、平台 Secret、平台角色授予 | 租户开停、client 注册、provider/Secret/策略/角色/任务写入；私有对话/附件、冒充用户、编辑 EduPlus2 主数据 |

路由、API 和权限 key 是拟定契约，不表示当前已有接口。TMS/OMS 仅统一企业入口命名，不因 URL 自动授予 `tenant.*` / `ops.*` 权限；现行 OMS 只读与计费权限以本页矩阵和 OpenSpec 为准，旧非计费 `ops.*.manage` 不再作为 OMS 目标。通用业务 API 不整体搬入管理前缀。完整命名、M1 固定租户边界与旧路由约束见 [11](11-api-and-entrypoints.md)。

## EduPlus2 client/app 管理与归口

第一阶段 TMS 先做成**单租户管理**：当前 `/tms` 只能管理与自身绑定的一个 `internal_tenant_id` / `external_tenant_id`，包括该租户下允许调用 DeepTutor 的 EduPlus2 client/app、能力策略、配额和审计。普通第三方应用运行时从一开始就按 JWT `tid` 支持多租户：`tid=A` 映射租户 A，`tid=B` 映射租户 B；前提是对应 tenant 与 client/app 已完成有效注册。

### TMS 注册规则

1. TMS 管理员在当前租户上下文输入 `client_id`。
2. DeepTutor 调 EduPlus2 通用 `POST /api/v1/open/oauth-clients/resolve` 解析 `client_id`，取得权威 `external_tenant_id`、`external_app_id`、`external_app_name`、`external_tenant_name` 和状态信息；接口需求草案见 [EduPlus2 通用 OAuth Client Resolve API 需求建议](eduplus2-oauth-client-resolve-api-proposal.md)。
3. `external_tenant_id` 必须与当前 TMS 绑定的外部租户 ID 完全一致；不一致返回拒绝，不允许“代管”其他租户 client。
4. 检查同 provider 下 active `client_id` 是否已存在，以及同租户同 app 是否已有 active client。
5. 无冲突后注册，写入 client 注册审计；冲突返回 409。

### OMS 查询规则

OMS 仅在 `ops.clients.read` 下按受控范围查看已归口的 client/app 及其接入状态，不提供注册、注销或暂停。跨租户 client 接入/修复若确需平台操作，应另走独立获授权的 DeepTutor/EduPlus2 管理流程及 proposal，不在 OMS 复用旧 `ops.clients.manage` 写接口。

### 唯一性与注销

同一个 EduPlus2 租户下同一个应用只能存在一个 active client 注册。唯一性以 EduPlus2 返回的权威应用 ID 为准，不以可变名称为准。若要把租户 A 的 alpha 应用从 `client-001` 切换到 `client-002`，必须先将 `client-001` 注销/retire/revoke，再注册 `client-002`。注销保留历史审计，不物理删除历史记录。

## B2：现有租户界面微调清单

1. 导航、工作台跳转与管理页子路由统一指向 `/tms`，专属管理请求使用 `/api/v1/tms/*`；导航/页头展示当前租户，菜单数据、表格请求、资源选择器均只取当前 tenant。首页按已有管理能力展示入口，不把 KB 权限作为所有管理角色的共同前置。KB 页面通过企业文档服务展示已选 RAG 的真实导入/索引失败和重试状态，托管删除与外部连接解绑明确区分；不跳转原始 Server 管理页绕过权限。
2. 保留现有用户资源授权、共享 KB、配置等交互，移除平台凭证、全部租户列表和全局配置入口。
3. EduPlus2 用户/组织只展示必要同步字段；DeepTutor 只编辑应用内 grants，不创建第二套用户密码/学校组织管理。自有密码账号仅用于受控固定租户 PG 身份模式，不保留 SQLite/local 认证回退；TMS 不提供注册用户、重置 EduPlus2 密码或创建学校组织入口。
4. 已有 API 从 `require_admin` 拆成 scope 与具体 permission 判定；不得仅改前端菜单。
5. 保存成功后配置与实际 runtime 一致，多副本缓存按版本失效；禁止页面写文件而 worker 仍读旧状态。
6. 租户管理员默认可管理自己租户；自定义角色按显式能力出现菜单，不以 `eit=adm` 单字段授予平台权限。
7. EduPlus2 client/app 管理入口使用 `tenant.clients.manage`，只显示当前租户 active/历史注册，注册时必须实时校验 EduPlus2 权威 tenant/app 信息。

## C1/C2 分批交付边界

| 工作包 | 范围 | 完成要求 |
| --- | --- | --- |
| C1：运营只读基础 | 平台角色/入口、全租户目录、client/provider/策略/任务/审计只读、权威状态与普通运营文案 | G3a；可信跨租户权限和真实数据源通过；可先发布基础版 |
| C2：Token 计费与欠费协同 | 逐调用真实 Token 明细、租户/用户费用、版本单价、OMS-only 供应商成本、独立欠费模型资格请求及 EduPlus2 生效确认 | G3；C1+C2 全部完成才标记 M3，不能用费用估算或停用整个租户代替 |

B1 先完成首租户最终身份/权限/撤权闭环，B2 完成各租户自己的管理 UI、EduPlus2 lifecycle webhook 和 OMS 治理只读后端。C1 复用 B2 权限/API，不首次建立安全边界；C2 依赖逐调用 Token 总账与计费后端。任务取消/重试仍属其原业务/运维归口，不在 OMS 提供按钮；多执行者时仍需通过 H/G-H。

## 运营功能域（按最新边界）

| 功能 | 操作与要求 |
| --- | --- |
| 租户目录 | 按内部 ID/外部 tid、名称、状态检索；分页、详情；只列授权范围的租户管理元数据 |
| 生命周期 | 只读展示 EduPlus2 外部租户资格、本地隔离、初始化状态、版本及同步异常；非计费开停/恢复由租户 lifecycle webhook 驱动 |
| 策略与配额 | 只读展示允许范围、生效状态与影响；修改仍走各自 DeepTutor/TMS 授权入口 |
| 模型与凭证 | 只读展示各服务 provider readiness；连接、LLM、task、embedding、search、TTS/STT、image/video、解析/RAG 等完整维护在独立 DeepTutor 平台设置，Secret 不回传明文 |
| Token 与费用 | 按租户→用户→调用展示供应商真实 usage、待核算、调用时有效每百万 Token 价格及 Decimal 费用；成本拆分仅授权 OMS 查看 |
| 欠费 | 可按权限记录欠费并请求 EduPlus2 限制/恢复独立模型资格；未收到模型资格 webhook 前显示待外部确认。生效后只拦新模型调用，登录、TMS/OMS 管理、历史查询及非模型操作仍可用 |
| 运行治理 | 只读展示导入/同步/Webhook/turn/任务状态和脱敏诊断；重试/取消归原业务/运维入口 |
| 审计 | 查询操作者、目标租户、脱敏变更、结果、request ID 与时间；导出单独授权 |
| 外部应用 / client | TMS 管理本租户已归口 client/app；OMS 仅跨租户查询注册与状态 |

## 权限矩阵：入口到后端必须闭环

以下 `ops.*` / `tenant.*` 是 DeepTutor 拟新增能力 key，不声称 EduPlus2 已有同名 relation。对接时映射现有 EduPlus2 权限；缺失能力通过其版本化 OpenFGA/角色迁移补齐。DeepTutor 使用 FastAPI dependency/权限服务，不照搬其他仓库的 Java 注解。

| 入口 / API（拟定） | 后端校验 | 能力 key / 外部权限映射 | 默认授权角色 | 前端入口 key |
| --- | --- | --- | --- | --- |
| `/tms` 下的 KB 管理入口、`/api/v1/tms/kbs` | 已认证、当前 tenant、`require_tenant_permission`、资源归属 | `tenant.kb.manage` → 租户资源管理权限 | 本租户 `tenant_admin`；显式授权自定义角色 | `tenant.kb.manage` |
| 本租户授权/模型配置 | 当前 tenant、禁止越过平台分配范围 | `tenant.grants.manage` | 本租户 `tenant_admin`；显式授权自定义角色 | `tenant.grants.manage` |
| `/api/v1/tms/eduplus2/clients` 注册/列表/注销 | 当前 tenant、`require_tenant_permission`、EduPlus2 client 校验、external tenant 完全一致、唯一约束 | `tenant.clients.manage` → 租户外部应用管理权限 | 本租户 `tenant_admin`；显式授权自定义角色 | `tenant.clients.manage` |
| `/api/v1/auth/eduplus2/exchange` | EduPlus2 JWT 验签、active client registration、tenant/app/client 状态、用户映射 | `eduplus2.token.exchange` / 已注册 app 策略 | 已注册 app 下的合法 EduPlus2 用户；不提供前端管理入口 | 第三方 SDK/前置应用透明处理 |
| `/api/v1/ws` / `/api/v1/external/turns` start_turn | `dt_token`、当前 user/tenant/client scope、owner/grant、capability allowlist、quota | `turn.start` / app capability policy | 当前用户及获授权 app | 聊天/外部能力入口 |
| `/oms` 入口、租户目录与 `GET /api/v1/oms/tenants` | 可信平台身份、目标范围 | `ops.oms.access` + `ops.tenants.read` | admin/operator/auditor（按显式授权） | 同后端能力 key |
| 租户 lifecycle 状态 | 只读；变更由 EduPlus2 签名 webhook | `ops.tenants.read` | admin/operator/auditor | `ops.tenants.read` |
| `/api/v1/oms/eduplus2/clients` 列表 | 只读、受控 tenant 范围 | `ops.clients.read` | admin/operator/auditor | `ops.clients.read` |
| provider/策略状态与任务 | 只读、脱敏 | `ops.providers.read` / `ops.policy.read` / `ops.jobs.read` | 按显式授权 | 同后端能力 key |
| 用量/审计 API | 平台只读权限，导出独立授权 | `ops.usage.read` / `ops.audit.read` | admin/operator/auditor | 同后端能力 key |
| Token 费用查询 | 平台身份、显式目标租户、成本字段排除 | `ops.billing.read` | 按显式授权 | `ops.billing.read` |
| 价格/欠费管理 | 版本与动作权限、目标租户、审计 | `ops.billing.manage` + `ops.billing.price.manage` 或 `ops.billing.arrears.manage` | 价格默认 admin；欠费可显式授权 operator | 同后端能力 key |
| 成本价与拆分 | 后端字段白名单、审计 | 读 `ops.billing.cost.read`；写另需 `ops.billing.manage` + `ops.billing.cost.manage` | 默认 admin | 同后端能力 key |
| 独立 DeepTutor 平台 Provider 设置 | 非 OMS 路由；Secret 仅受控解析 | `platform.providers.manage` / `platform.credentials.manage` | 默认 admin | 平台设置入口 |
| TMS 审计查询 | 当前 tenant scope，审计只读，禁止跨租户 | `tenant.audit.read` | 本租户 tenant_admin/auditor 或显式授权角色 | `tenant.audit.read` |
| 任务重试/取消 | 不属于 OMS；由原业务/运维入口按其权限执行 | 非 OMS `ops.jobs.manage` | 原业务/运维授权主体 | OMS 无按钮 |

“admin/operator/auditor”在本表分别指 `platform_admin/platform_operator/platform_auditor`。平台角色通过可审计的可信授权维护，不能由学校管理员身份、任意客户端 claim 或本地用户名自动推导。M2M 运维调用也受相同 scope/permission 限制。

## 租户生命周期与策略生效

按 [03 独立状态来源](03-tenant-scope-schema.md#租户状态的独立来源) 保存外部租户资格、本地启停和初始化状态。`provisioning/active/suspended/failed` 是租户生命周期派生展示，不是外部同步与运营共写的字段；欠费模型资格另列，不得渲染成租户 `suspended`。

```text
外部租户资格有效 ∧ local_enabled ∧ 必要租户资源就绪 → 允许登录与业务准入
允许业务准入 ∧ 独立模型资格有效 → 允许实际模型调用
```

- 非计费开通/停用/恢复：仅接收并验证 EduPlus2 租户生命周期 webhook，保留本地恢复隔离的独立状态；按其资格重算全入口准入。OMS 只读查看结果与异常。
- 欠费限制/恢复：使用独立的 EduPlus2 模型资格 webhook；未确认不得宣称“模型使用已受限”。生效也只在 LLM、task、embedding、语音、图像/视频等实际模型调用前拦截，不撤销登录会话、不阻断管理与非模型操作；结清后恢复模型资格不自动恢复其他原因停用的租户。
- 停用生效后拒绝新登录/新 turn/下载授权/后台派发；对已有 WS/运行任务在权限检查点撤权，不删除历史。已签发直传/下载 URL 最长存活到短 TTL；要求即时撤权的内容使用后端代理。
- 策略/配额在各自获授权 DeepTutor/TMS 入口版本化管理，OMS 只读展示生效结果；本地取消/超时不直接释放远端预留，缺用量显示待核算。

### 任务操作与基础设施运维分开

OMS 复用 [06 的业务/远端任务契约](06-postgresql-native-store-plan.md#业务任务远端索引与取消边界) 只读显示业务状态、远端观察状态/时效、取消意图/确认和用量核算。`cancel_requested` 不显示“已停止”；取消/重试由原业务/运维入口执行，不在 OMS 新增执行能力。

原业务/运维的 job 操作仍不授予整 workspace 停止、实例销毁、检索队列管理或图屏障恢复权。KB 页面只展示资源申请/绑定结果；池补充、部署/Secret 和回收走独立运维，池耗尽/半开通不得靠普通后台直调 Kubernetes 修复。

## 数据与越权边界

运营列表使用最小化平台元数据/聚合视图；租户资源操作先校验平台能力、显式绑定目标租户，再用受 RLS 约束的事务执行。不对普通请求开放任意 tenant override 或 BYPASSRLS 连接。

租户用户继续依赖已验证身份 scope；URL/body 的租户 ID 不是授权证据。运营人员无默认私有内容读取或冒充登录能力；如将来需要支持访问，另立审批、授权、时效、用户告知及审计方案，不能在本期用“超级 admin”绕过。

OMS 的图容量/待恢复信息来自 LightRAG 受控状态或运维观测结果，只展示必要元数据；OMS 不持有图凭证、直连 Gremlin 或图屏障恢复权。LightRAG 内部维护由独立运维身份/流程完成，不在 DeepTutor 中另建图管理后端。

## 状态迁移与运维边界

- **本次文档修改**：同步最新 OMS 只读治理/计费边界，保留 TMS/OMS 目标 URL；旧 `ops.*.manage` 中非计费 OMS 写能力不再作为 OMS 目标。仅文档变化，不修改 DB、OpenFGA、Keycloak 运行态，不新增可执行 migration。
- **后续 DeepTutor DB**：租户生命周期、策略版本、运营角色默认数据和审计结构走版本化迁移 Job；已存在用户/角色映射需显式回填与验证；租户分源状态回填保留本地暂停、未知外部资格拒绝放行，不从旧 active 推断外部许可。
- **后续 EduPlus2**：只有新增 relation/tuple/client/scope/redirect 等才需要对应 OpenFGA/Keycloak provider migration；由 EduPlus2 仓库受控流程负责，不用手工改库或启动脚本替代。
- **验证闭环**：迁移 dry-run/apply/verify、重复执行幂等和 drift 检查；默认管理员、自定义角色正例及 403 负例；菜单/路由/按钮/API 对齐。

### EduPlus2 client/app 与 token exchange 的迁移判断

本轮仍是文档更新；后续实现需要 DeepTutor DB migration，至少新增或扩展：

1. `external_client_registrations`
2. `external_tenant_bindings`
3. `external_user_bindings`
4. `token_exchange_audit` 或统一 audit event 类型/索引
5. `client_policy_versions` 与 app capability allowlist
6. `auth_sessions` 的 `auth_provider/client_registration_id/client_id/external_app_id/external_tenant_id/external_user_id/identity_type` 等字段
7. client/app 状态、能力策略、quota 与审计索引

阶段一可暂不修改 EduPlus2 OpenFGA/Keycloak，条件是只开放指定管理入口、client/app 策略由 DeepTutor DB 控制、不开放第三方自助注册、不新增 EduPlus2 relation/scope。后续若纳入 EduPlus2/OpenFGA/Keycloak 权限模型，需要按真实使用范围受控新增 `tenant.clients.manage`、`ops.clients.read`、`tenant.audit.read`、`ops.audit.read`、`external.turn.start` 等能力，并通过对应 provider migration 执行；不新增 OMS client 写能力。

## 验收

以 [02 的 G2/G3](02-rollout-testing-and-migration.md) 及六个实施 OpenSpec change 为准。至少验证 `/tms`、`/oms` 导航/深链接与各自 API 前缀一致，默认管理员/获授权自定义角色可达、无权限直调返回 403；租户管理员不能访问运营 API、auditor 不能写、operator 不能管理 Secret/角色；欠费模型资格限制生效后用户仍可登录、管理和查询历史，仅新模型调用受阻；provider 配置仅在独立平台设置真实生效。旧前缀和原生未适配路由不得成为鉴权旁路。

EduPlus2 client/app 首批验收还必须覆盖：TMS 注册当前 tenant client 成功、TMS 注册其他 tenant client 被拒绝、OMS 跨租户只读查看已归口 client、OMS 注册/注销写请求 403、同 tenant+same app 第二个 active client 返回 409、revoke 旧 client 后允许新 client、重复 `client_id` 409、未绑定 tenant 要求 provisioning、已注册 client JWT exchange 成功、未注册/撤销/暂停 client 403、JWT `tid` 与 registration tenant 不一致 403、非法/过期 JWT 401、WS `auth_refresh` 透明续期、已接受 turn 不因 token 自然过期中断、新 turn 必须重校验、审计包含 client/app/tenant/user/session/turn 且不包含 token/secret/完整私密正文。
