# B1/B2 外部契约证据与本仓库调用路径审计（2026-09-27）

> **结论：仅完成只读契约与代码盘点；B1 真实首校、B2 双校及管理会话均未放行。**
> 环境为 EduPlus2 test 文档站及 auth-test 公共 OIDC discovery；未持有或调用学校/平台用户令牌，未触碰真实学校数据。文档页面 HTTP 200，`Last-Modified: 2026-09-24 09:38:02 GMT`（本次观察）；discovery HTTP 200。本文件中的身份/学校字段是文档结构和虚构形状，不是实测用户响应。EduPlus2 属外部团队，本次只读。

## 1. 已发布接口适用性矩阵

| 能力／来源 | 调用身份、合同与脱敏形状 | 已证实的边界／时效 | 本次状态与待补证据 |
| --- | --- | --- | --- |
| [OIDC discovery/JWKS](https://eduplus-auth-test.f123.pub/realms/eduplus/.well-known/openid-configuration)、[JWT 验证](https://eduplus-test.f123.pub/docs/oauth-oidc/jwt-verification/) | 公共 discovery 只读 GET，实测 `issuer=https://eduplus-auth-test.f123.pub/realms/eduplus`，JWKS 与 token endpoint 均位于该 realm；用户 JWT 须验签、`iss/aud/exp/iat/azp`。 | 公钥与端点可达≠OMS `eduplus-platform-admin` 或某校 client 的有效用户登录。JWT `tid` 是租户断言，不是内部学校绑定或在线状态。 | **机制可达；OMS/TMS audience、azp、用户会话及撤权实测未验证**。 |
| [OAuth Client resolve](https://eduplus-test.f123.pub/docs/oauth-oidc/client-resolve/) | `POST /api/v1/open/oauth-clients/resolve`，当前环境 Bearer JWT；按精确 client_id，`include=app,tenant,oauth,policy`。成功形状：`data.verified=true`，`client.client_id/status`，`tenant.tenant_id`（signed 64-bit 数字）/`tenant_code`/`status`/`subscription_status`，`app.app_id/status`，`version`（安全状态 SHA-256）；无密钥。 | 文档说每次服务端实时读取、`Cache-Control: no-store`；学校状态可为 `active`/`trial`，订阅为 `active`/`subscribed`，不可将 `policy.allowed_usages` 当订阅。全局 client 的 `tenant=null`，不能从它推出学校。业务失败可能 HTTP 200 + `verified=false`。 | **文档核实，实际学校 client 与 M2M/用户令牌调用尚未实测**；须用受控测试账号核验学校 ID/code/状态与订阅变更、429/503、撤权后生效时间。本次已移除本地 resolve 缓存作为准入来源，但外部实测仍未完成。 |
| [Me Profile](https://eduplus-test.f123.pub/docs/user-data/me-profile-api/)、[API 细则](https://eduplus-test.f123.pub/docs/user-data/user-data-api/) | `GET /api/v1/me/profile`，**当前登录用户** Bearer access token（或 BFF HttpOnly Cookie）；裸 JSON 形状如 `k_user_id=<sub>`、`eduplus_user_id=<eui>`、`tenant_id=<tid>`、`school_code=<code>`、`identity_types[]`。 | 不接受查询别人的参数；未给账号在线启停、学校权威状态或负责人资格的独立字段。`identity_types[].status` 是身份状态，不等于账号状态。响应 `Cache-Control: private, max-age=30` / ETag，可 304；不能拿旧缓存批准敏感写。 | **本人业务态合同可用；在线账号/学校核验合同不足**。须验证用户令牌实际响应与停用/解绑行为；不能用 M2M POST 代替该 GET。 |
| [Open User Data](https://eduplus-test.f123.pub/docs/user-data/user-data-api/) | `/api/v1/open/userdata/users` 与 `/users/{userId}` 需要**审批通过并订阅的第三方应用授权码用户令牌**，`azp=app_credentials.client_id`，且受 DataAccessPolicy ∩ UserAccessPolicy 限制；`user_id` 为 EduPlus2 ID，`k_user_id` 为 Keycloak `sub`。 | 学校管理、平台管理或 M2M token 不能直接调用。`dept_id` 虽接受但 `/users` 当前不应用过滤；数据可见不等于本产品授权候选已本人登录。第三方主数据 `account_status` 不能代替在线账号/负责人资格核验。 | **OMS 平台人员目录不可用；TMS 仅条件可用，尚未核实具体 client 审批/订阅/策略和学校隔离**。失败、空范围、无结果应分别处理。 |
| [Token Claims](https://eduplus-test.f123.pub/docs/user-data/token-claims/) | `sub`=Keycloak UUID，`eui`=EduPlus2 用户 ID，`tid`=学校租户 ID，`eit`=激活身份；`eei`=外部来源用户 ID。 | 文档明示自定义字段可选，role/组织/班级业务态不能从 JWT 推断；`eit` 不是 OMS/TMS 授权。 | **字段语义有文档；实际学校用户与平台用户 token 样本未核实**。 |
| [学校主数据](https://eduplus-test.f123.pub/docs/school-master-data/) | 该文档面向 SIS **向 EduPlus2 提供**主数据端点，不是 DeepTutor 查询学校权威状态的 API。 | 不能把它当作学校 ID、改码、停用、解绑或两名负责人资格来源。 | **不适用**；需外部团队确认现有权威学校查询及学校负责人在线资格合同。 |

**仍缺的关键合同**：①权威学校 ID 与 code 改名/重绑/解绑的线上查询与版本语义；②本人及他人的在线账号启停核验、有效期与故障时效；③两名本校负责人可复验资格；④OMS 专用 `eduplus-platform-admin` 和学校 TMS client 的实测 `iss/aud/azp`；⑤实际测试学校的订阅、撤权和失败响应。缺任何项时相应绑定、管理写入口及 B1/G2 放行均保持关闭。`/me/profile` 或 Webhook mock 不填补这些空缺。

## 2. 本仓库当前差异与已处理项

| 路径 | 现状／风险 | 处理与后续 |
| --- | --- | --- |
| `eduplus2/client.py` 的 resolve 规范化 | 旧实现从 `policy` 读订阅、缺学校或订阅状态时默认 `active`，并把任意学校/应用 ID 转为字符串；与已发布合同不符。 | 本次改为读取 `tenant.subscription_status`，缺状态/版本拒绝；学校/应用 ID 只接受 signed-64 正整数或 ASCII 十进制字符串并规范化，`verified` 必须是真布尔值；保留学校 code 作为定位快照，识别 `trial`/`subscribed`。合成测试验证。 |
| `eduplus2/client.py` 的普通 OIDC 验签 | 当前 `EduPlus2OidcJwtVerifier.verify()` 使用 `verify_aud=False`；虽然核验签名/issuer/azp 及 resolve，**尚未核验令牌目标 audience**。 | B1 2.2 前须由各应用实测 `aud` 并配置严格校验；本次未凭文档样例猜测目标值，不宣称最终换票安全门禁已通过。 |
| `eduplus2/client.py` 的 `EduPlus2ProfileClient` 与 `bootstrap.py` 默认 `/api/v1/open/profile` | 现实现为 M2M `POST` 指定用户；已发布 `/me/profile` 是用户令牌 GET 本人。二者不是同一合同。 | **未将旧客户端接到 `/me/profile`**，也不以可选客户端返回推断账号在线。需要单独的当前用户令牌适配器及真实正负例后再装配。 |
| `eduplus2/client.py` 的 `EduPlus2PermissionClient` 与默认 `/api/v1/open/permissions/check` | 目前按 M2M POST 调用，已查文档未证明该路径/响应可用。 | 暂仅视为未核实旧接口；不把它当 OMS/TMS `ops.*`／`tenant.*` 决策权威。 |
| `eduplus2/service.py`、`bootstrap.py` | 普通换票沿用固定内部学校与 allowlist；原 `resolve_cache_seconds=60` 会使新换票复用旧学校/订阅状态。可选 Profile/Permission 快照的 `revocation_cache_seconds=30` 仍未达到 B1 当前状态门禁。 | 本次让换票、注册和权限复核的 `_resolve` 始终在线查询，不再读写旧授权缓存（表/构造参数仅作已应用迁移兼容）；需要首校独立绑定与当前外部账号/学校状态交集。 |

## 3. 入口／数据面盘点及应新增的上游中立 seam

| 面 | 已查代码与当前保护 | B1/B2 缺口或拒绝条件 |
| --- | --- | --- |
| 联邦换票与身份 | `eduplus2/service.py`、`api/application.py` exchange：验 JWT、resolve、固定部署内部学校及普通 `dt_token`；`identity_bindings` 绑定用户。 | 尚无受控版本化学校权威 ID→内部 UUID 与 code/撤权栅栏；`tid` 不可直接映射。普通 token 不得变管理会话。 |
| HTTP/WS/refresh | `api/application.py` 的 `AuthenticationMiddleware`、`SocketAuthentication` 对普通 token 做本地验证及 EduPlus2 快照/撤权查询，企业 app 只挂限定核心路由；WS 新命令/refresh 路径需逐项覆盖。 | 需通用可信学校 scope/epoch provider，令新 turn、资源下载、WS 命令复核同一绑定；过期/停用/远端故障失败关闭。不能仅靠连接建立时检查。 |
| SDK/CLI/后台 | `runtime.py` 的 `StoreProvider`/`TurnEnvironment` 以当前身份设租户；`executor.py`、`bootstrap.py` 管执行者，CLI 有本地操作路径。 | 新任务/重试必须带可信发起主体、学校绑定版本并重验；CLI 本地身份不获跨校操作。没有批准通用 seam 前不改 core。 |
| PG/RLS、个人资源 | `deeptutor/persistence/postgres` scoped store/connection 与企业迁移 runner；会话及资源按 `tenant_id`、多处再按 `owner_id` 查询。合成测试已证明 Store 显式条件隔离，但**当前单库表 owner 连接绕过 core 非 FORCE RLS**。 | 用户已确定迁移/运行共用一个 PG 账号；后续版本 `FORCE RLS` 须按下方严格审阅覆盖全部适用表及维护路径，且仅可称正常应用查询的纵深防御，不可声称抵御同凭据恶意直连。双校连接池、grant、撤权并发仍缺证据。 |
| S3/ObjectStore、KB/LightRAG、缓存 | `bootstrap.py` 配 S3；`knowledge_bases.py` 依据 PG 对象元数据列 owner KB 并调 LightRAG；`eduplus2` resolve/撤权缓存存在。 | 对象键、短链、LightRAG namespace/索引/图查询、缓存键均需校验服务端学校+owner 范围；直接访问后端和双校同名 KB 仍未验收。 |
| OMS/TMS 授权及旧旁路 | `management/authorization.py` 仅未装配的本产品 PG 决策；`api/application.py` 仍有 `tenant_admin` 审计路由，完整核心 settings/admin 未装配。 | 需独立 OMS/TMS 会话及 `ops.*`/`tenant.*` 管理路由；旧 `tenant_admin` 审计入口须审阅关闭/替换，旧管理路由不装配并做 404/403 负例。OMS 不管理学校账号。 |

### 逐入口调用与资源所有权清单

| 入口／执行点 | 当前可信范围及已经覆盖的负例 | 必须增加的门禁；归属 |
| --- | --- | --- |
| `POST /api/v1/auth/eduplus2/exchange` → `eduplus2/service.py:exchange_user_jwt` → `identity_bindings` | 现有验签、`azp`/client resolve、外部 `tid/eui/sub` 一致性、重放/速率审计；`test_eduplus2_federated_access.py` 覆盖合成 JWT 和固定学校。 | `aud`、当前本人账号/权威学校 ID、学校绑定 epoch、失败时效；联邦适配与普通用户绑定由本 change 持有，`oms.school_bindings` 权威写入归管理授权 change。 |
| HTTP `AuthenticationMiddleware` → `Enterprise.authorize` / `GuardedTurns._service` → session/turn | middleware 拒绝 `x-tenant-id`/query 租户覆盖并验本地 token；`StoreProvider.get` 固定 `tenant_id,user_id`，`PostgresSessionStore` 查询带 owner；`test_application.py:test_m1_fixed_tenant_rejects_b2_escape_attempts` 与 `test_sdk_and_http_share_owner_guard` 为当前负例。 | 新 turn、敏感读、取消/答复、事件订阅每个新命令均对当前学校绑定 epoch 与外部状态复验；HTTP 身份／scope provider 放企业扩展，core 只接通用可信 scope seam。 |
| `/api/v1/ws` → `SocketAuthentication.authenticate/revalidate/refresh/validate_start_turn` | 同身份 refresh，WS 新命令复验本地身份；资源引用走 PG owner 检查，禁止 payload 租户覆盖；现有 `test_application.py` WS/资源测试。 | 断线重连、旧连接新命令、撤权并发、已接受 turn 的自然到期界限都需同一绑定版本；不得用建连时身份或 Webhook mock 延长权限。 |
| `Enterprise.sdk(token)`、远程 CLI `session`、本地 CLI `schema/recovery/account` | SDK 持有身份 ContextVar + scoped store，退出后不可回退本地；远程 CLI 走服务器 token；维护 CLI 另有 maintenance/停机确认。 | SDK 新敏感操作与后台重试需刷新学校 epoch；维护身份只具迁移/恢复用途，不是普通用户或 OMS 跨校会话。CLI 不得允许学校码切换可信 scope。 |
| `Database.transaction(TenantScope)` / `PostgresSessionStore` / RLS | 每次 checkout 事务 `SET LOCAL app.tenant_id/app.user_id`，受限连接禁 RLS bypass 角色；会话、消息、操作、事件及对象数据按学校与 owner 查询。 | 合成双校同名资源、同校双 owner、连接池交错/取消、直接低权 SQL、ID 猜测、owner/显式 grant、撤权与写事务同锁序尚需 3.1 全套负例；不能把学校成员或管理角色视为私有正文 grant。 |
| `/api/v1/resources/upload-intents`、`/complete`、`/files/resources/...` → `PostgresObjectResourceStore` | PG 元数据与对象 key 含 `tenant_id` 和 owner hash，代理读/引用按 owner 校验；现有 `test_application.py` 外校资源 ID 在触碰 ObjectStore 前拒绝。 | 预签名直传、短链、低权直接访问 S3 与清理重试需要服务端学校/owner 授权和 epoch；不能仅靠 key 前缀或 UI 隐藏。 |
| `TurnEnvironment.prepare_request` → `resolve_requested_knowledge_bases` → `EnterpriseLightRAGTool.execute` | PG KB 元数据按学校+owner 列表，未授权 KB 名不可装载。**但实际 `LightRagServerClient.query_context(query, mode)` 未传 `kb_name`/学校 workspace**。 | 3.2 前必须有执行侧强制学校/KB/index-version/图命名空间或独立实例隔离，并测试受限身份直连检索后端；只用 PG 列表过滤不构成远端隔离。 |
| 历史 `eduplus2.resolve_cache`/Profile 快照/撤权、`bootstrap.recover`、coordinator、对象清理/OMS attempt | resolve 旧表保留但准入不读写，其他快照与后台仍持有限时本地事实；恢复按当前固定学校/用户扫描，attempt 有独立幂等事实。 | 新安全决策不读缓存允许结果；所有持久任务携带可信学校/owner/绑定 epoch、派发与重试时重验，远端不确定进入待核对，不以默认学校或高权连接续写。 |

**应新增且不硬编码学校业务的 seam**：①验签后统一 `TrustedScopeProvider`（学校稳定 UUID、owner、绑定 epoch、client/app、correlation），由企业扩展实现、HTTP/WS/SDK/任务共用；②通用操作前与事务内 epoch guard，可在 RLS/owner 查询前及副作用前调用；③对象与检索的服务端 namespace/owner 参数及低权直连校验；④持久 job 的不可变发起 scope/版本与重试门禁。核心只接受上述通用上下文/钩子；任何必须改 core 的 patch 都需另留上游合并风险和 CLI/HTTP/WS/SDK 回归证据。

**受控后续顺序**：先确认缺失外部合同和真实登录主体，接着新增 DeepTutor 后续版本学校绑定迁移/受控登记（不改 `oms/0011`），再将可信 scope/epoch 逐入口接入并做双校 PG/S3/LightRAG/任务负例。只有首校真实登录/撤权及 G2 双校证据齐全后才开放第二所真实学校；此表不构成发布批准。

### 必须回归的旧旁路清单

| 入口 | 目标拒绝行为 |
| --- | --- |
| 企业 app 的核心 `/api/settings` 完整写路由、核心 admin/plugin 管理路由 | 不装配，深链 404；只保留明确选择的 `/api/settings/ui` 公共界面设置，不将本地 Web 设置写能力迁给云端。 |
| 尚未装配的 `/api/v1/oms/*`、`/api/v1/tms/*` | 404，而不是回退旧 `tenant_admin` 或普通换票路由；正式上线后再按各自会话/动作返回 401/403。 |
| `/api/v1/enterprise/audit/eduplus2/events`、`/exports` | 当前代码仍查旧 `tenant_admin`，不得视为 `ops.audit.*` 或 `tenant.*`；正式管理接入前需替换或禁用，并加无权/越校/导出负例。 |
| 普通 `dt_token`、`eit=adm`、`tenant_admin`、header/query 学校覆盖 | 不得获得 OMS/TMS 权限；`x-tenant-id` 等头与 `tenant_id` 等 query 在当前企业 middleware 已拒绝，仍需服务端直调与 WS/SDK 回归。 |
| `/oms/prototype/*`、`/tms/prototype/*` 生产入口 | 继续 404；开发态 fixture 不能挂真实管理 API。 |

已存在的路由负例：`test_application.py:test_enterprise_does_not_mount_legacy_management_writes` 对认证用户验证旧设置/Skill/Provider/TMS/OMS 写路由 404（`PUT /api/settings/ui` 为 405），`test_enterprise_management_route_allowlist_is_narrow` 固定仅 `/api/settings/ui` 在设置前缀，`test_m1_does_not_expose_tms_or_oms_surfaces` 与 `test_m1_fixed_tenant_rejects_b2_escape_attempts` 覆盖未装配管理入口及伪造范围。以上是**当前基线**，不是正式 OMS/TMS 401/403/200 授权验收。

### B2 合成 PG 负例与未解决的 RLS 运行身份缺口

`test_b1_b2_school_isolation.py` 在临时 PostgreSQL 中建立两所学校、重复外部用户 ID、同名 KB 和同校第二用户，交错查询 `PostgresSessionStore` 与 KB 清单：Store 的显式学校/owner 条件阻止跨校与跨 owner 读取。使用临时**非表 owner** 角色直查 `enterprise.sessions`、`enterprise.resource_objects` 时，RLS 分别只返回当前学校/owner 行，跨学校或跨 owner 的会话写入被拒。**反例**：按当前 `single_database_user_dsn` 模拟的应用表 owner 角色，哪怕 `Database.transaction(TenantScope(学校 B))` 设置了 `SET LOCAL`，不带谓词的 `SELECT enterprise.sessions` 仍读到学校 A 两条会话。原因不是连接池串 scope，而是 core 迁移只有 `ENABLE ROW LEVEL SECURITY`，没有 `FORCE`，且 core runner `_verify_schema` 明确要求 `relforcerowsecurity=false`；PostgreSQL 官方 [RLS 规则](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) 明确表 owner 通常绕过策略。

这与 `docs/enterprise/03-tenant-scope-schema.md`、`04-kubernetes-postgresql-architecture.md` 要求非 owner／FORCE 的目标不同，也与 `06-postgresql-native-store-plan.md` 当前单 owner 模式「RLS 仅作未来防线」的说明一致。企业 `bootstrap.py:Enterprise.__init__` 目前把**同一 DSN**交给运行 `Database`、`MigrationRunner` 和 `ExecutorLease`。**3.1 和 G2 仍未通过**；不得以 Store 条件或上述非 owner 合成角色测试代替实际部署证明。用户已明确排除迁移/运行账号分离；因此不再实施原候选 A，按下节审阅单账号 `FORCE RLS` 的可行范围与无法消除的风险。本轮未擅自修改 core 迁移或现有生产配置。

### 单账号 FORCE RLS 严格审阅及实施门禁

**确定的边界。**一个 PG 登录/角色承担迁移、业务运行和受控维护，不引入第二个迁移或运行账号。后续版本 core 迁移可对 `enterprise` 租户表启用 `FORCE ROW LEVEL SECURITY`，企业扩展后续版本迁移可对 `eduplus2` 尚未 FORCE 的租户表做同样处理；`oms`/`management` 已 FORCE 的表不原位改写。须同步 core/extension runner 的**按历史版本**目录预期与 drift 校验，保持旧迁移 checksum，不允许跳过或放宽校验。新租户表从创建版本开始 FORCE。此机制能让正常、受控 `TenantScope` 事务里漏写 `WHERE tenant_id` 的查询仍受策略限制。

**不能获得的保证。**[PostgreSQL RLS 文档](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)说明 `FORCE` 可让表 owner 受策略约束，但 owner 本人仍可更改/关闭策略；[对象所有权规则](https://www.postgresql.org/docs/current/ddl-priv.html)说明修改对象的权利不能从 owner 身上撤销。本仓库 `app.tenant_id`/`app.user_id` 是连接可设置的自定义配置，不是数据库验签的主体事实；合成测试已实测同一非 owner 连接在学校 B 事务中自行 `set_config('app.tenant_id', 学校 A)` 后可读到学校 A 的同 owner 会话。同一账号的恶意 SQL 既可改变这些配置，若为表 owner 还可 DDL；所以 `FORCE` **不构成抵御该凭据持有者的跨校安全边界**。账号泄露、任意 SQL/DDL 执行及数据库级受限直连测试不能由 FORCE 单独证明安全。G2 的威胁模型若包含同凭据恶意直连，必须另行调整身份架构或明确此项不能验收；不能悄悄把原要求降为“WHERE 漏写保护”。

**已识别的兼容影响。**core `migrations/runner.py` 当前要求所有 `enterprise` 租户表 `relforcerowsecurity=false`，故不能只加 SQL、不改版本化目录校验。企业 `eduplus2` runner 对其租户表亦要求 `false`。`Database.transaction(TenantScope)` 使用事务级 scope，正常 Store 可作为迁移回归基线；`GlobalScope` 不授跨校读权。`offline_import/{chat_sqlite,pocketbase_import,matrix_sqlite,learning_reading_sqlite,runtime_sqlite,id_mapping,cutover}.py` 和 `verify_report.py` 存在直接 `psycopg` 连接访问 `enterprise` 租户表的维护路径，当前未统一设置事务级学校/owner scope；启用 FORCE 后可能空读或拒写。维护/导入须从可信 `migration_stage.batches.target_tenant_id` 或明确受控参数派生 scope，逐事务设置并验证，不得用运行时 `NO FORCE`、关闭 RLS 或全局默认学校绕过。跨校校验应逐校受控迭代，不假设同一个无 scope 查询可扫全表。

**实施与回退门禁。**先为单账号 owner 模式编写期望的双校 RLS 读写、连接复用、无 scope 拒绝、旧库升级/重复 apply/verify/drift 及离线导入/切换回归；看见现行失败后，再新增不可变后续版本迁移和必要的上游中立 scope seam。迁移应在隔离合成 PG 事务中完整验证，失败原子回滚；已成功应用的版本不靠修改旧 SQL 或删除历史回退，后续应用回退必须检查 schema 兼容性，必要时用新的前向迁移。运行入口不能获得任意 SQL/DDL 或可控 scope 参数。以上 review 记录只是影响分析，不是核心改动批准、同凭据直连风险接受或 G2 验收。
