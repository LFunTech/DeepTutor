# 执行证据（2026-09-27，局部切片）

## 边界与阶段

用户最新决策是 DeepTutor Enterprise 程序负责 OMS `ops.*` 与 TMS `tenant.*` 授权，PG 只保存事实、版本、审计并作隔离/事务兜底；EduPlus2 在权限链路中只提供认证与稳定身份识别，Webhook `subscription.created.actor.user_id` 是本产品一次性首位 TMS 管理员身份来源，而非外部权限判定。其仓库、Keycloak、OpenFGA 均不由本项目修改。OMS 只管理平台人员。任务 3.1 的**数据库迁移与隔离合成验证**已完成，最新事件引导迁移尚未完成；本记录不代表正式管理 API、UI 或迁移已获 test/production 放行。

2026-09-27 用户明确表示本提案已完成审阅并要求按跨提案执行计划继续推进，作为本 change 后续实施授权记录。任务 1.1 同时要求受影响的其他 OMS/TMS 提案**分别**审阅批准，故仍未勾选；本次确认不自动替代那些提案的独立批准，也不授权真实数据、生产发布、提交或归档。

## 外部能力证据矩阵（任务 1.2，缺口未闭合）

| 能力 | 已有证据与环境 | 对本 change 的结论 |
| --- | --- | --- |
| OMS 平台管理 Client ID | 2026-09-27 用户明确指定 `eduplus-platform-admin`；本仓库和已读取的公开 EduPlus2 用户数据/M2M/Webhook 文档未给出该 Client 的目标环境配置或授权码换票实测。 | 作为 OMS 预期 Client ID 进入配置与验证清单；尚不等于已核实的 token `azp`/`aud`、平台人员目录、在线账号状态或本产品 `ops.*` 授权。与每校 Webhook OAuth Client 分开。 |
| OIDC discovery/JWKS、通用 M2M/client resolve | 2026-09-18 test/本地只读与交互验证，详见 `../add-enterprise-oms-business-logic/implementation-evidence.md`；旧 profile/permission M2M POST 为 404/405 | 只能证明机制；尚不能证明指定 `eduplus-platform-admin` Client 的登录能力、实际 token audience、管理者在线状态或平台会话。 |
| Webhook 签名 demo 与真实接收 | 2026-09-26 test-cn `智能体基座` 控制台 8/8 `subscription.*` mock 204；2026-09-27 `rc.53` 后真实 terminated/created 204，学校 PG 绑定和 actor 待核验候选已落库，见 `../add-b2-eduplus2-tenant-lifecycle-webhook/implementation-evidence.md` | 真实候选仅供后续本人匹配；未验证 TMS 登录、学校管理员授权或撤权。无需重做 mock。 |
| Webhook `subscription.created.actor` | 2026-09-27 按用户指引只读核对 [事件类型](https://eduplus-test.f123.pub/docs/webhook/event-types/) 与 [Webhook 事件格式](https://eduplus-test.f123.pub/docs/webhook/)：`actor` 可选，`actor.user_id` 可为 null（系统/定时任务），表示触发事件的 Keycloak User ID；外部文档未声明其具有管理员角色。用户明确将真实 `subscription.created.actor.user_id` 定义为**本产品首位管理员身份来源**。 | 已验签非 mock、目标应用/学校绑定的真实事件可一次性登记待激活主体；本人 TMS 登录精确匹配后，DeepTutor Enterprise 程序才可作授权决策。mock/system/null/重复/恢复不得赋权。真实事件与本人激活未验收前入口关闭。 |
| Webhook OAuth Client 与机器令牌 | 2026-09-27 只读获取 [Webhook 文档](https://eduplus-test.f123.pub/docs/webhook/) 和 [Client Credentials 文档](https://eduplus-test.f123.pub/docs/oauth-oidc/client-credentials/)：事件示例含 `oauth_client.client_id/client_secret`，M2M 示例能换 `client_credentials` token 并展示 `GET /api/v1/users` 的泛用代码片段。未使用真实凭据或调用用户接口。 | 凭据下发不等于人员目录授权。`/api/v1/users` 的适用 client、权限、学校范围、返回格式与在线状态未核实，不能作为 OMS/TMS 候选来源。Secret 仅可服务端保存，不得进入前端或证据。 |
| 本人 Profile 与学校成员目录 | 2026-09-27 只读获取 [Me Profile 文档](https://eduplus-test.f123.pub/docs/user-data/me-profile-api/) 和 [User Data API 文档](https://eduplus-test.f123.pub/docs/user-data/user-data-api/)：`/api/v1/me/profile` 仅当前用户；`/api/v1/open/userdata/users` 需已审批第三方应用授权码用户 token、`azp=app_credentials.client_id`、有效学校订阅，返回受 Data/User Access Policy 约束的分页已有账号。未携令牌实测。 | TMS 可列为**待核验的条件性**成员发现能力；须实测 app/client、用户令牌、学校范围、策略、故障与失效，不得直接用 M2M 或学校后台 token。`dept_id` 当前不实际过滤，不能作隔离；目录 `user_id` 是 EduPlus2 ID，`k_user_id` 是 Keycloak `sub`，授予前仍须候选本人登录并核验 `(issuer,sub,school)`。OMS 不接学校目录。 |
| 在线账号状态、TMS 当前学校身份、权威学校 ID/绑定 | 本仓库文档只有设计；`oms.school_bindings` 目前空表迁移和合成数据测试 | 未获既存接口的适用性、调用身份、失败模式与 test 证据；不能启用管理写。 |
| 旧双负责人资格模型 | 已检查的外部文档未给出可复验合同，且用户现已明确改为真实订阅事件 actor 一次性身份引导。 | 旧学校侧提议/批准路径退役；不得用 `eit=adm`、mock 或原型身份切换替代真实事件与本人匹配。 |

任何后续外部验证须补接口版本、环境、调用身份、脱敏响应、时间、故障/撤权结果及有效期；本代理仅只读核实发送端交付，不改其仓库。

本次 `curl` 仅对上述四个公开文档 URL 返回 HTTP 200；这不是任何受保护 API 的 200/403 实测，也不证明用户目录已经对智能体基座开放。主数据中的人员即使可见，未关联登录账号时 `user_id` 可为空，不能从主数据记录直接建立授权主体。

## 入口/动作盘点（任务 1.3，待逐按钮复核）

| 表面 | 当前状态 | 放行前需确认 |
| --- | --- | --- |
| 企业 HTTP/WS | `api/application.py` 显式装配 exchange、Webhook、审计、conversation/session/health；未装配 `/api/v1/oms/*` 或 `/api/v1/tms/*` 正式管理路由。旧核心治理 router 未装配；见 OMS 业务提案 3.1 节的 18 条 404 审计。 | 新路由逐条关联后端 action/scope/owner，旧路由保持 404；WS turn/session 不能继承管理写。 |
| OMS 独立前端 | `apps/oms/app/page.tsx` 为 `notFound()`；`/oms/prototype/[[...slug]]` 仅 development，旧 `tms-bootstrap` 深链 404。开发原型有平台人员、角色、平台人员学校范围、授权审计；合成 fixture，不是实际权限 API。 | `ops.oms.access` 仅入口；`ops.tenants.read` 等逐校动作、Provider/Secret/成本/导出敏感动作与真实 API 对齐。不得出现学校账号/学校后台开通。 |
| TMS 独立前端 | `apps/tms/app/page.tsx` 为 `notFound()`；`/tms/prototype/[schoolCode]` 仅 development 且锁定 demo 学校。原型现演示订阅 actor 本人匹配/异常、成员、角色、访问关系及记录，仍全为合成交互。 | `tenant.tms.access`、`tenant.members.read`、`tenant.permissions.manage` 等须由 Enterprise 程序按当前会话学校分别判定；资格不可由演示选项或学校码自证。 |
| 本地 Web | `web/app/{oms,tms}` 是旧壳/开发原型转向，不是云端正式应用。 | 生产原型 404；不得从本地 Web 路由绕过独立会话。 |
| CLI/SDK/后台 | 目前无 OMS/TMS 管理公开写方法；见 OMS 业务提案入口审计与 `test_oms_management_entrypoints.py`。 | 后续新增任何管理命令/job 都应调用同一企业授权服务；不能借用普通用户或平台管理员 token。 |

迁移 `management.action_catalog` 已固定 OMS `ops.*` 与 TMS `tenant.*` 基线和平台/学校 scope；模板只登记，**未授予任何主体**。完整菜单、按钮、导出和资源 owner/grant 的逐条矩阵仍以 `design.md` 第 4 节为基线，正式接线前继续逐项核查。

## 本仓库已实施的局部底座

- 企业 migration runner 追加独立 `management/0001_authorization_base.sql`：主体、动作目录、不可变角色版本/动作、assignment、委托上界、审批请求、追加审计和 policy version；所有授权表启用 FORCE RLS，未默认创建主体或授予旧 admin 权限。只在临时 PG 使用合成学校 ID 验证；未对真实 DB 应用。
- 后续 `management/0002_approval_delegation_guards.sql` 不改已应用 `0001`：批准态必须有完整且不同于提议者的复核人身份与决定时间；TMS 委托学校必须等于主体学校，委托动作范围必须与当前动作目录一致。新增针对这三类缺口的失败测试后，再用新迁移变绿；另验证旧 `enterprise.users.role='tenant_admin'` 在迁移前存在时不会自动生成管理主体或授予权限、重复 assignment command ID 被拒绝、删除新增审批约束会使 verify 报 drift。该切片仍不构成完整授权变更/审批服务。
- `management/authorization.py` 为未装配的事务内决策原语：按应用域、主体/外部核验时效、本地 policy version、TMS 当前 `app.tenant_id`、权威学校绑定版本、assignment/动作/scope 判定；写时锁定主体、学校绑定/租户及 assignment。`ManagementIdentity` 必须由未来可信适配器构造，不能由请求体、header 或未验签 JWT 构造。该函数不自行调用外部在线账号/负责人接口，也不等于正式 API。
- 新迁移加角色/动作 scope 约束、最后有效平台安全管理员与学校管理员的撤权/缩短有效期/停用主体保护；角色名相同但无治理动作的空模板不算可用替代管理员。已发布动作不允许原位改变范围/敏感级别或重新启用已退役动作，核心治理动作不可退役。后续授权变更服务必须统一按主体→学校绑定→assignment 的锁顺序，并以预期版本、幂等键和追加审计提交；目前未实现，因此不能开放写入口。
- OMS `ops.oms.access` 同时支持显式平台或逐校范围；学校范围的 operator/auditor 模板可进入其获授权学校，但不能由该授权推导平台范围入口或全校列表。auditor 的本校脱敏审计读动作仍须另按目标授权复核。
- 仅调整了 `openspec/config.yaml` 中旧“平台管理员开通 TMS”描述，以当前学校侧双负责人方案为准。

## 未完成与门禁

任务 1.3 现有入口盘点与 3.1 PG 基础事实迁移已完成；1.1 因用户最新“Enterprise 程序授权 + 真实订阅 actor 首位引导”边界而重新打开，须同步受影响提案并复核。1.2 外部认证/身份及真实事件合同/实测缺口与 upstream 实际合并演练尚未完成。2.1/2.2、3.2–3.4、4.1–4.3、5.1–5.2 均未完整交付；OMS Client ID 已由用户指定，但尚缺该 Client 在目标环境的真实登录、audience 与身份有效性验证，以及真实订阅 actor/学校绑定和本人匹配、初始平台人员安全登记、完整授权/审批/委托写服务、正式管理 API、真实数据 UI 与 test 联调。正式 OMS/TMS 写路由继续不装配。任务 3.1 只证明本仓库既有迁移及测试，尚未包含事件引导记录；不得把它、合成 JWT、原型 fixture 或 Webhook demo 记作后续入口验收通过。

## 本轮验证记录

- 临时 PostgreSQL 与合成数据：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short` → **368 passed、3 skipped**。第一次全量运行的 30 个失败均由 `test_persistence.py` 固定迁移清单遗漏 `management/0001` 导致，补清单后全量重跑；其后新增平台最后管理员、动作目录漂移/退役、OMS 逐校入口和迁移事务回退用例，又完成上述最终全量重跑，没有跳过失败项。
- 新授权/迁移与既有持久化定向：45 passed（第一次修正后）；最终新授权/迁移定向 **20 passed**。最后管理员的缩短到期/停用主体、无治理动作假管理员、动作目录退役、策略版本删除、autocommit 写拒绝、逐校 OMS 入口均有红灯—绿灯验证；迁移后续版本强制失败能回退 management schema/history，再以正常 runner 成功 apply/verify。
- 独立 OMS/TMS 原型：`npm test -- --run tests/management-authorization-prototype.test.tsx` → **11 passed**；前端全量 `npm test` → **227 passed / 25 files**；OMS/TMS `tsc --noEmit`、`npm run lint` 通过。原型测试不代表正式 API 验收。
- `openspec validate --all --strict` → **27 passed、0 failed**；目标 Python `ruff check` 与 `ruff format --check`、`git diff --check` 通过。企业 wheel 构建成功并核对包含 `management/migrations/0001_authorization_base.sql`，已更新 `extensions/enterprise/pyproject.toml` 的包数据规则。
- `git ls-remote` / `git fetch upstream main` 仅更新本仓库只读上游引用，未合并：当前 `upstream/main` 为 `a053fecf`，相对本地 HEAD 为本地 64 / 上游 367 个提交。此切片只增加企业扩展包、企业 migration runner 与测试，无新增 core runtime 修改；工作区已有大量其他未提交变更，**未完成**当前上游的实际合并演练，故 G/H upstream 门禁不据此通过。
- EduPlus2 工作树 `git status --short -uall` 为 **0 项**；未修改发送端。无提交、推送、发布、归档或真实租户数据操作。

### 2026-09-27 后续切片

- `test_management_authorization_migration.py` 新增 6 个用例；审批复核人缺失/同人、TMS 跨校委托及 OMS 动作范围不符先分别得到预期失败，再由 `management/0002` 修复。目标迁移测试随后 **19 passed**，补充了合法复核人和本校委托的正例。
- 新建 [`add-b1-b2-trusted-school-integration`](../add-b1-b2-trusted-school-integration/proposal.md) 四份 OpenSpec artifact 并通过该 change 的 strict validation，作为待单独审阅的 B1/B2 实施合同；**未按新 change 实施任何真实学校接入或发布**。
- 本轮企业后端全量 `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short` → **374 passed、3 skipped**；后续正例补强后的迁移定向重跑 **19 passed**。目标 `ruff check`、目标 `ruff format --check`、`openspec validate --all --strict` → **28 passed、0 failed**，`git diff --check` 均通过。wheel 重新构建并确认包含 `management/migrations/0002_approval_delegation_guards.sql`。

### 2026-09-27 迁移任务 3.1 验收补强

- 将重复 assignment 命令测试改用**不同角色、相同 command ID**，排除仅被“同角色唯一索引”挡住的假阳性；另增加审批幂等键唯一和授权审计 append-only 的 INSERT/UPDATE/DELETE 合成测试。定向迁移测试 **21 passed**。
- 任务 3.1 对应的两版本迁移覆盖主体、OMS/TMS 域、不可变角色/动作、委托上界、有效期/范围/assignment、policy version、审批与追加审计；隔离 PG 通过默认零权、FORCE RLS、唯一性、重复 apply/verify、drift、旧 `tenant_admin` 零提升、最后管理员撤权/停用保护和失败回退。**仅此数据库任务勾选**；命令结果级幂等、安全审批、外部在线复验、实际 API 与 UI 均归 3.2 及后续任务，不由唯一索引自动实现。
- 本轮全量企业后端测试 **376 passed、3 skipped**（149.81 秒）；`ruff check`、目标 `ruff format --check`、`openspec validate --all --strict` **28 passed、0 failed**，以及 `git diff --check` 通过。未对真实学校数据库应用迁移。

### 2026-09-27 用户发现契约增补的本轮校验

- 四个公开文档 URL 的 `curl` 读取均为 HTTP 200；未取得或使用 Client Secret、用户令牌，也未调用受保护用户接口。此项只证明文档当前可读，不提升上述外部能力矩阵的实测等级。
- `openspec validate add-enterprise-management-authorization --strict`、`add-b2-tms-management-prototype --strict`、`add-c1-oms-operations-prototype --strict` 均通过；本轮 `git diff --check` 和受影响 Markdown 尾随空白/末尾换行检查通过。
- 曾有 `openspec validate --all --strict` **27 passed、1 failed**：新建中的 `add-b1-b2-trusted-school-integration` 尚无 delta spec；当时没有据此宣称全量通过。**本轮已补齐该 change 四份 artifact 并重新运行，全量为 28 passed、0 failed**，但新提案仍须独立审阅批准。

### 2026-09-27 本轮继续实施：管理决策的学校状态栅栏

- DeepTutor `AGENTS.md` 已明确禁止本代理修改 EduPlus2 或其他团队仓库、Keycloak/OpenFGA 和其运行资源；本轮只修改本仓库，未操作外部系统。
- 任务 1.3 的入口盘点继续进行：企业 API 仍未装配 `/api/v1/oms/*`、`/api/v1/tms/*` 正式管理 router；`test_enterprise_does_not_mount_legacy_management_writes` 保持旧写入口 404（`PUT /api/settings/ui` 为 405），CLI/SDK 仍无平台管理写方法。PG `management.action_catalog` 已登记 OMS 19 项、TMS 9 项动作；OMS/TMS 原型权限面板分别仅列 8/7 项合成演示动作，不是正式安全 DTO。尤其 OMS 原型将 `ops.oms.access` 写为 `platform`，而迁移允许 `both`；后续正式 UI 必须按后端有效范围修订，不能以原型判定授权。菜单、按钮、导出、后台和 owner/grant 的逐项最终矩阵尚未核完，因此 **1.3 继续未勾选**。
- 管理授权原语此前只核 `oms.school_bindings.status='verified'` 和学校 `external_eligibility='allowed'`；即使 `enterprise.tenants.local_enabled=false`、未完成 bootstrap、供应未就绪或处于隔离，TMS 仍可能通过本地管理权限判定。新增失败测试先得到 `DID NOT RAISE ManagementAuthorizationDenied`，随后在同一学校绑定查询中读取 `bootstrap_completed`、`local_enabled`、`provisioning_status`、`recovery_state`：TMS 所有管理访问及 OMS 对目标学校的写入均须学校本地状态可用；OMS 只读仍可用于排障。写事务继续 `FOR SHARE OF b,t` 持锁，学校状态更改与写入串行。合成测试分别覆盖四种不可用状态、OMS 学校写拒绝及可用学校正例。
- 定向测试 `test_management_authorization.py` **12 passed**；本轮企业后端全量 **381 passed、3 skipped**。这是隔离合成数据与未装配原语验证，不是外部在线账号/学校接口、双人负责人资格、正式 OMS/TMS 登录或写 API 验收。任务 3.2、2.1、2.2、3.3 及正式放行仍未完成，当前 OpenSpec 勾选数保持 1/14。

### 2026-09-27 本轮继续实施：学校重绑不复活旧授权

- 新增后续版本 `oms/0012_school_binding_version_guard.sql`：权威学校 ID、状态或核验证据变化须逐次递增绑定版本，不允许直接删除绑定后以初始版本重建；旧 `oms/0011` 不改写。新增 `management/0003_assignment_school_binding_version.sql`：学校范围 assignment 显式携绑定版本，既有 NULL 版本不猜测回填、权限决策一律拒绝，须重新受控核验授权；平台范围不携学校版本。迁移 runner 追加版本/触发器/列与约束的 drift 核验，企业 wheel 已核对含两份 SQL。仅在临时 PG 对合成学校 apply/verify，未迁移真实数据。
- TDD 先见两项真实缺口：绑定从外部学校 101 改指 202 后，旧 OMS 学校 grant 仍被接受；绑定 ID 不递增版本即可重定向。补迁移与决策条件后，旧 grant、无版本 grant 均拒绝；正例仅绑定版本一致时允许。另覆盖绑定直接删除拒绝、触发器漂移 verify 拒绝，及迁移重复 apply/verify。
- 此切片不提供“权威学校 ID 类型与真实外部学校核验”适配器，也不建立授权变更命令、正式会话/API/UI 或初始平台管理员登记；任务 2.2、3.2 和 1.3 仍未整体完成，OMS/TMS 正式写路由仍关闭。DB 需要且已新增上述本仓库版本化迁移；OpenFGA/Keycloak 不需要也未修改。
- 最新全量企业后端测试 `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short`：**385 passed、3 skipped**；受影响 Python 文件 Ruff check/format 通过；`openspec validate add-enterprise-management-authorization --strict`、`add-b1-b2-trusted-school-integration --strict` 与 `openspec validate --all --strict`（28 passed、0 failed）通过。两份新增 SQL 已在 wheel 中核对存在。无提交、推送、部署、真实学校数据迁移或外部仓库改动。

### 2026-09-27 本轮继续实施：事务内低风险角色授予

- 新增未装配的 `management.grants.grant_management_role`：仅接受由未来可信适配器核验的 actor/target 断言，在同一 PG 事务内复核治理动作、目标学校绑定和本地可用状态、固定角色版本的全部动作、逐动作/学校委托上界及授权到期时间；学校 grant 写入当前绑定版本。待登记候选在成功授予时才激活，assignment 触发目标策略版本递增，并追加同事务审计。命令要求预期目标版本、幂等 UUID、原因和 request ID；相同命令可回读，改写参数重放冲突。首位学校管理员、平台安全管理员及任何含 `sensitive` 动作的角色一律拒绝直授，留待独立双人审批流程；授予方的委托不产生对被委托业务动作的执行权。
- 权限矩阵（**仅内部函数，不是可访问 API**）：TMS `school_auditor` → `tenant.permissions.manage` + 同校逐动作委托 → 当前学校 `school` grant；OMS `platform_auditor` → 平台 `ops.permissions.manage` + 指定学校逐动作委托 → 该校 `school` grant。两者前端正式入口均未装配，也无 200/403 HTTP 结论；默认模板只在 PG 登记，不默认发给任何账号。自授、缺委托、敏感角色单人授予、幂等参数冲突均拒绝。OpenFGA/Keycloak 不参与本产品授权，未修改；此切片没有新增 DB 迁移，使用既有 `management/0001`–`0003` 与 `oms/0012`。
- TDD 先见缺模块、OMS 平台治理权被误按学校 scope 查询的失败，再补服务并回归。隔离合成数据定向授权测试 `5 passed`；企业后端全量 **389 passed、3 skipped**（147.60 秒）；目标 Ruff check/format 通过。角色授予仍未接真实外部身份/账号在线状态、两名学校负责人资格、审批、API 或前端，任务 3.2/3.3/3.4、4.1–4.3 **均不勾选**，写路由仍关闭。
- OMS 开发态原型另以失败测试发现 `ops.oms.access` 被错误列成纯 `platform`，导致学校 scope 自定义角色无法选择后端允许的入口动作；已把原型目录的该动作与 `ops.supply.manage` 标记为 `both`，创建角色的过滤和校验均按选定范围接受 `both`。该变更仅修正合成原型与 PG 目录的范围语义，不将其当作正式权限 DTO。前端全量 **248 passed / 25 files**，OMS/TMS TypeScript 检查与 ESLint 通过；OpenSpec 全量 strict **28 passed、0 failed**，Python Ruff check/format 与 `git diff --check` 通过。
- 后续 TDD 又发现原型敏感度低估：OMS 学校运营角色含 PG 标为敏感的权益/额度/供给写动作却可单人直授；已把这些动作及服务配置写动作的原型敏感度与 PG 对齐，学校运营授予进入双人复核演示。TMS 成员直授原型曾列出 `school_admin` 和含敏感动作的 `school_operator`；现仅向此**无复核能力的直授表单**显示低风险角色，并在提交逻辑再次拒绝敏感角色。两处均为原型防误导、失败关闭，不代表真实审批实现；高风险 TMS 角色仍待独立审批 UI/API。目标原型测试 **23 passed**；最终前端全量 **250 passed / 25 files**，OMS/TMS TypeScript 检查与 ESLint 均通过。

### 2026-09-27 后续切片：撤权串行、命令重放与入口盘点

- 在未装配的 `management.grants` 中新增低风险角色撤权：当前 OMS/TMS 治理动作与目标学校仍须事务内核验，按主体→学校绑定→授权记录锁序复核 assignment/目标策略版本，撤权触发 policy version 递增并追加同事务审计。审计 UUID 即撤权命令幂等键；不同请求参数不得借旧键重放。最后一名管理员由 PG trigger 拦截，服务以 savepoint 将其转为冲突，主事务保持可用。撤权不修改外部账号、学校权益或额度。
- TDD 定向覆盖 TMS 同校撤权、旧会话版本失效、幂等重放、另一次策略变更后仍返回原始命令结果、最后管理员保护与事务可继续、A 校管理员不能撤 B 校角色，以及在途权限写锁阻塞撤权、撤权提交后旧版本请求被拒。另发现授予/撤权命令可通过改写 `expected_version` 借相同幂等键重放，已改为审计前版本及安全摘要逐字段比对；授予重放经当前可信目标身份版本核验后返回原始审计结果，而非后续策略版本。
- 新增 [`surface-inventory.md`](surface-inventory.md) 记录当前 HTTP/WS、CLI/SDK、后台、OMS/TMS 开发原型、旧路由 404/405、PG 28 个权威动作与默认模板、owner/grant 和 upstream seam 的盘点基线。它明确标出尚未逐按钮绑定真实 API、导出/后台与正式安全 DTO 的缺口，因此 1.3 仍不勾选。
- 本轮隔离合成 PG 定向 `test_management_authorization.py` **21 passed**，企业后端全量 **401 passed、3 skipped**（148.24 秒）；目标 Ruff check 通过。此次仍无正式管理 router/外部可信适配器、首位学校管理员或高风险审批服务；3.2–3.4、4.x 继续未完整验收，完整任务勾选仍 1/14。未使用真实学校数据或修改发送端。

### 2026-09-27 任务 1.3 入口盘点验收

- 逐项扫描独立 OMS/TMS 原型的导航、按钮、行操作、确认框和详情链接，对照 PG 19+9 个动作、scope/sensitive、默认角色和自定义角色上界，补完 [`surface-inventory.md`](surface-inventory.md) 的操作组映射。对于 Agent/工具/Skills/运行资源策略和 TMS 审计读等 catalog 未定义的原型能力，明确写为**不得直接迁成正式 API**；不伪造动作或以入口动作兜底。
- 核对企业 HTTP router 白名单、旧管理写 404/405 负例、普通租户 token/伪造 `X-Scopes`、CLI/SDK 管理直写缺席、WS/后台与 owner/grant 边界。现有通用 core `GlobalScope` seam 只提供无租户事务，不携平台授权；记录其 upstream 合并风险，真正 merge/smoke 仍归 5.1。
- 因 1.3 是**盘点和合同固定任务**，当前全部现有入口及缺项均已有源文件和目标动作/禁用结论，故该项勾选。正式路由/按钮与 HTTP 403/200/409、导出、状态 descriptor 和 owner/grant 可执行验证仍归 3.2、4.1–4.3、5.1，不借此提前放行。进度从 1/14 到 **2/14**。

### 2026-09-27 任务 1.1 受影响修订版逐项确认中

- 用户已确认本授权 change 的审阅；本轮又明确分别批准按现版实施 `add-b2-oms-platform-read-governance`、`add-enterprise-tms-business-logic`、`add-c1-c2-oms-operator-interface`，以及 `add-enterprise-all-service-provider-settings`、`add-enterprise-exact-token-usage-ledger`，并分别批准 `add-c1-oms-operations-prototype` 与 `add-b2-tms-management-prototype` 的当前授权边界修订版。所有回答均针对列名 change 的现版，不以旧版批准自动延伸。
- 旧 TMS 外部管理员权限/webhook 不再是本产品开通/授权权威；EduPlus2 只提供其已交付身份、账号、学校状态，DeepTutor 自有 PG 管理 `ops.*`/`tenant.*`。随后用户又单独批准 `add-enterprise-oms-business-logic` 的 2026-09-27 权威拆分版；受影响提案当前修订版的逐项确认已齐，故勾选 **1.1，管理授权进度 3/14**。这些批准不意味着外部账号/负责人合同已交付，不授权修改 EduPlus2、真实租户数据、生产发布、提交或归档；正式管理写 API 仍未装配。

### 2026-09-27 撤销旧发送端授权客户端

- 删除未装配的 `oms/authorization.py::OmsPlatformAuthorizationClient` 及其旧端点合成测试：它固定使用已撤回的 `/v1/platform/integrations/deeptutor-oms/authorize` 与 `oms:*` 动作，不属于当前 DeepTutor PG `ops.*` 权威模型。保留通用 OIDC 验签切片，但不据此发放权限。新增退役负例，先红后绿；定向 OMS 入口与身份测试 **13 passed**，目标 Ruff check 通过。正式管理授权仍只有 `management.authorization` 原语且未装配 API；此切片不完成 3.2 或 5.1。

### 2026-09-27 用户再次明确授权控制点及首位管理员来源

- 用户明确：权限由 **DeepTutor Enterprise 程序**逐入口判定；PG 是版本化事实/事务/审计库，数据库 role、GRANT 与 RLS 不能代替业务操作者授权；EduPlus2 在权限链路中只提供认证和稳定身份识别。`management.authorization` 原语本就在 Python 应用层执行，并已补文档澄清其 `policy_version` 为本地版本；新增同一 PG runtime 用户可见动作目录但无 assignment 的身份仍被拒绝的定向负例，**1 passed**。这不等于所有正式入口已装配。
- 按用户指定，真实 `subscription.created.actor.user_id` 成为**本产品的一次性首位 TMS 管理员身份来源**；不是 EduPlus2 权限 API 判定。公开 [事件类型](https://eduplus-test.f123.pub/docs/webhook/event-types/) 与 [事件格式](https://eduplus-test.f123.pub/docs/webhook/)仍明确 `actor` 可选、system 可为 null；故正式规则限定已验签、非 mock、应用/学校/订阅绑定、`actor.type=user` 且 ID 非空，登记待激活主体，待其本人 TMS 登录精确匹配后由 Enterprise 程序激活。mock、错校、重放、恢复/重订和身份不匹配不授权；真实事件接收、一次性栅栏和本人激活尚未实现。
- 管理授权、TMS 业务、生命周期 Webhook 与 TMS 原型的 OpenSpec 合同已向此边界修订；旧学校侧双负责人首位开通不再实施。开发态 TMS 原型已撤下双负责人模拟，改为订阅 actor 待匹配、已匹配、其他人、缺失及 mock 场景；前端定向测试先红后绿 **23 passed**，仍无真实身份/事件/API。当前 1.1 须对最新受影响提案再复核，故进度 **2/14**，正式管理路由保持未装配。

### 2026-09-27 TMS actor 原型浏览器复核与文案修正

- 浏览器核对 actor 待匹配、本人匹配、其他人、无有效 actor、控制台 mock 五态；mock/无 actor 均无激活按钮，本人匹配须二次确认且标注仅合成演示。发现无 actor/mock 时仍展示“已验签真实 actor 来源”，通过测试先红后绿修正为无可激活身份。桌面 1440×900、窄屏 390×844 截图与 Console 0 errors 见 [双端原型审计](../add-c1-oms-operations-prototype/prototype-browser-audit-2026-09-27.md)。全量前端 25 文件 **250 passed**，TMS typecheck、lint、build 均成功。此证据只完成 TMS 开发原型任务 3.11，不改变正式事件、身份及 API 未交付状态。

### 2026-09-27 OMS Skill 动作目录增量迁移

- 新增 `management/0004_oms_skill_actions.sql`，仅在本仓库 `management` schema 中登记 `ops.skills.read/manage/review/publish` 的 `platform` 范围和 `ops.skills.grant` 的目标 `school` 范围；`platform_security_admin`、`platform_config_admin`、`platform_operator` 增加各自 v2 **候选模板**，v1 assignment 不自动升级、主体不自动赋权。受限数据库 owner 仍受 FORCE RLS，迁移事务显式设置 OMS 应用域；`MigrationRunner.verify()` 检查五个动作的范围/敏感度/状态及 v2 模板是否漂移。
- 测试先见新目录为空、后见受限 owner 在 RLS 下无法执行新增迁移，以及动作退役后 verify 未报错，逐项修复；临时 PG `test_management_authorization_migration.py` 与 `test_persistence.py` 合计 **64 passed**。此项是 3.2 的权限事实前置，不是应用层 PEP、正式 OMS API/UI 或外部平台登录已完成；3.2 仍未勾选。没有改 EduPlus2、OpenFGA、Keycloak 或真实学校数据。

### 2026-09-28 OMS 受保护入口局部装配

- 新增 `/api/v1/oms/me` 和模型清单/草稿的独立 Bearer 分流；每次请求调用已验签平台身份、显式在线状态检查器和 DeepTutor 本地 `ops.*` PEP。草稿写入在单 PG 事务内复核 `ops.providers.manage`、目标版本和审计，不能靠 PG role/JWT role 放行；无本产品角色或只有 `ops.oms.access` 均不能读写模型。默认 verifier/在线检查器不配置时返回 503，不复用租户会话。合成 PG/API 测试随企业套件 **521 passed、3 skipped**。真实 `eduplus-platform-admin` 授权码/账号状态合同、平台初始管理员、独立 OMS 会话和跨学校权限仍未验收，3.2/5.1 不勾选。
