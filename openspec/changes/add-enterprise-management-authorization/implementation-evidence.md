# 执行证据（2026-09-27，局部切片）

## 边界与阶段

用户最新决策是 DeepTutor Enterprise 程序负责 OMS `ops.*` 与 TMS `tenant.*` 授权，PG 只保存事实、版本、审计并作隔离/事务兜底；EduPlus2 在权限链路中只提供认证与稳定身份识别，Webhook `subscription.created.actor.user_id` 是本产品一次性首位 TMS 管理员身份来源，而非外部权限判定。其仓库、Keycloak、OpenFGA 均不由本项目修改。OMS 只管理平台人员。任务 3.1 的**数据库迁移与隔离合成验证**已完成，最新事件引导迁移尚未完成；本记录不代表正式管理 API、UI 或迁移已获 test/production 放行。

2026-09-27 用户明确表示本提案已完成审阅并要求按跨提案执行计划继续推进，作为本 change 后续实施授权记录。任务 1.1 同时要求受影响的其他 OMS/TMS 提案**分别**审阅批准，故仍未勾选；本次确认不自动替代那些提案的独立批准，也不授权真实数据、生产发布、提交或归档。

## 2026-09-28 任务 1.1 状态同步

复核 2026-09-27 用户连续确认记录与本文件“任务 1.1 受影响修订版逐项确认中”小节：用户已分别批准本 change 及受影响的 `add-b2-oms-platform-read-governance`、`add-enterprise-tms-business-logic`、`add-c1-c2-oms-operator-interface`、`add-enterprise-all-service-provider-settings`、`add-enterprise-exact-token-usage-ledger`、`add-c1-oms-operations-prototype`、`add-b2-tms-management-prototype`、`add-enterprise-oms-business-logic` 当前修订版。审批范围仍限定 DeepTutor 仓库内实施；不授权修改 EduPlus2、真实学校数据、生产发布、提交或归档。

因此同步勾选任务 1.1。该勾选只代表现版合同获准实施，不代表外部账号/学校身份实测、首位 TMS 管理员 Webhook 即时开启、正式 OMS/TMS API/UI 或 test/production 放行已完成；这些仍分别归 1.2、2.x、3.x、4.x 与 5.x。

## 外部能力证据矩阵（任务 1.2，缺口未闭合）

| 能力 | 已有证据与环境 | 对本 change 的结论 |
| --- | --- | --- |
| OMS 平台管理 Client ID | 2026-09-27 用户明确指定 `eduplus-platform-admin`；本仓库和已读取的公开 EduPlus2 用户数据/M2M/Webhook 文档未给出该 Client 的目标环境配置或授权码换票实测。 | 作为 OMS 预期 Client ID 进入配置与验证清单；尚不等于已核实的 token `azp`/`aud`、平台人员目录、在线账号状态或本产品 `ops.*` 授权。与每校 Webhook OAuth Client 分开。 |
| OIDC discovery/JWKS、通用 M2M/client resolve | 2026-09-18 test/本地只读与交互验证，详见 `../add-enterprise-oms-business-logic/implementation-evidence.md`；旧 profile/permission M2M POST 为 404/405 | 只能证明机制；尚不能证明指定 `eduplus-platform-admin` Client 的登录能力、实际 token audience、管理者在线状态或平台会话。 |
| Webhook 签名 demo 与真实接收 | 2026-09-26 test-cn `智能体基座` 控制台 8/8 `subscription.*` mock 204；2026-09-27 `rc.53` 后真实 terminated/created 204，学校 PG 绑定和 actor 待核验候选已落库，见 `../add-b2-eduplus2-tenant-lifecycle-webhook/implementation-evidence.md` | 真实 actor 线索需后续核对 OIDC `sub` 合同；未验证正式 TMS 登录、撤权闭环或 5.1 开闸。无需重做 mock。 |
| Webhook `subscription.created.actor` | 2026-09-27 按用户指引只读核对 [事件类型](https://eduplus-test.f123.pub/docs/webhook/event-types/) 与 [Webhook 事件格式](https://eduplus-test.f123.pub/docs/webhook/)：`actor` 可选，`actor.user_id` 可为 null（系统/定时任务），表示触发事件的 Keycloak User ID；外部文档未声明其具有管理员角色。用户明确将真实 `subscription.created.actor.user_id` 定义为**本产品首位管理员身份来源**。 | 已验签非 mock、目标应用/学校绑定的真实事件可在 Webhook 事务内一次性即时开启首位学校管理员。mock/system/null/重复/恢复不得赋予新的权限。真实事件 actor 与后续 OIDC `sub` 合同未验收前不得宣称正式开闸。 |
| Webhook OAuth Client 与机器令牌 | 2026-09-27 只读获取 [Webhook 文档](https://eduplus-test.f123.pub/docs/webhook/) 和 [Client Credentials 文档](https://eduplus-test.f123.pub/docs/oauth-oidc/client-credentials/)：事件示例含 `oauth_client.client_id/client_secret`，M2M 示例能换 `client_credentials` token 并展示 `GET /api/v1/users` 的泛用代码片段。未使用真实凭据或调用用户接口。 | 凭据下发不等于人员目录授权。`/api/v1/users` 的适用 client、权限、学校范围、返回格式与在线状态未核实，不能作为 OMS/TMS 候选来源。Secret 仅可服务端保存，不得进入前端或证据。 |
| 本人 Profile 与学校成员目录 | 2026-09-27 只读获取 [Me Profile 文档](https://eduplus-test.f123.pub/docs/user-data/me-profile-api/) 和 [User Data API 文档](https://eduplus-test.f123.pub/docs/user-data/user-data-api/)：`/api/v1/me/profile` 仅当前用户；`/api/v1/open/userdata/users` 需已审批第三方应用授权码用户 token、`azp=app_credentials.client_id`、有效学校订阅，返回受 Data/User Access Policy 约束的分页已有账号。未携令牌实测。 | TMS 可列为**待核验的条件性**成员发现能力；须实测 app/client、用户令牌、学校范围、策略、故障与失效，不得直接用 M2M 或学校后台 token。`dept_id` 当前不实际过滤，不能作隔离；目录 `user_id` 是 EduPlus2 ID，`k_user_id` 是 Keycloak `sub`，授予前仍须候选本人登录并核验 `(issuer,sub,school)`。OMS 不接学校目录。 |
| 在线账号状态、TMS 当前学校身份、权威学校 ID/绑定 | 本仓库文档只有设计；`oms.school_bindings` 目前空表迁移和合成数据测试 | 未获既存接口的适用性、调用身份、失败模式与 test 证据；不能启用管理写。 |
| 旧双负责人资格模型 | 已检查的外部文档未给出可复验合同，且用户现已明确改为真实订阅事件 actor 一次性身份引导。 | 旧学校侧提议/批准路径退役；不得用 `eit=adm`、mock 或原型身份切换替代真实事件 actor 与后续 OIDC `sub` 合同证据。 |

任何后续外部验证须补接口版本、环境、调用身份、脱敏响应、时间、故障/撤权结果及有效期；本代理仅只读核实发送端交付，不改其仓库。

本次 `curl` 仅对上述四个公开文档 URL 返回 HTTP 200；这不是任何受保护 API 的 200/403 实测，也不证明用户目录已经对智能体基座开放。主数据中的人员即使可见，未关联登录账号时 `user_id` 可为空，不能从主数据记录直接建立授权主体。

## 入口/动作盘点（任务 1.3，待逐按钮复核）

| 表面 | 当前状态 | 放行前需确认 |
| --- | --- | --- |
| 企业 HTTP/WS | `api/application.py` 显式装配 exchange、Webhook、审计、conversation/session/health；未装配 `/api/v1/oms/*` 或 `/api/v1/tms/*` 正式管理路由。旧核心治理 router 未装配；见 OMS 业务提案 3.1 节的 18 条 404 审计。 | 新路由逐条关联后端 action/scope/owner，旧路由保持 404；WS turn/session 不能继承管理写。 |
| OMS 独立前端 | `apps/oms/app/page.tsx` 为 `notFound()`；`/oms/prototype/[[...slug]]` 仅 development，旧 `tms-bootstrap` 深链 404。开发原型有平台人员、角色、平台人员学校范围、授权审计；合成 fixture，不是实际权限 API。 | `ops.oms.access` 仅入口；`ops.tenants.read` 等逐校动作、Provider/Secret/成本/导出敏感动作与真实 API 对齐。不得出现学校账号/学校后台开通。 |
| TMS 独立前端 | `apps/tms/app/page.tsx` 为 `notFound()`；`/tms/prototype/[schoolCode]` 仅 development 且锁定 demo 学校。原型现演示订阅 Webhook 等待/即时开启/异常、成员、角色、访问关系及记录，仍全为合成交互。 | `tenant.tms.access`、`tenant.members.read`、`tenant.permissions.manage` 等须由 Enterprise 程序按当前会话学校分别判定；资格不可由演示选项或学校码自证。 |
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

## 2026-09-28 OMS 身份配置与在线状态接入切片

- 在 `deeptutor_enterprise.oms.identity` 增加 `BearerAccountStatusClient`：用同一个 OMS Bearer token 调用既存 HTTPS 账号状态/Profile 端点，要求响应主体与已验签 OIDC `sub` 精确匹配，并将 `active/enabled/allowed/normal/available` 视为有效、`disabled/locked/suspended/deleted` 等视为不可用；缺 subject/status、issuer/subject mismatch 或端点异常均 fail closed。该客户端只确认平台账号在线状态，不读取或映射任何 EduPlus2 角色、部门、学校或业务权限为本产品 `ops.*`。
- 在企业 bootstrap 中支持显式 OMS 身份环境配置：`DT_EDUPLUS2_OMS_ENABLED`、`DT_EDUPLUS2_OMS_DISCOVERY_URL`、`DT_EDUPLUS2_OMS_OIDC_ISSUER`、`DT_EDUPLUS2_OMS_AUDIENCE`、`DT_EDUPLUS2_OMS_CLIENT_ID`、`DT_EDUPLUS2_OMS_ACCOUNT_STATUS_URL`。启用后缺 discovery/issuer/audience/client/status URL 任一项即启动失败；未启用时继续保持 `/api/v1/oms/*` 503 fail closed。默认 client 仅在显式启用 OMS 配置时采用用户指定的 `eduplus-platform-admin`，audience 未填时按 client ID 处理。
- 定向验证：`ruff check` 通过；`test_oms_platform_identity.py`、`test_oms_me_rejects_tenant_token_and_unconfigured_platform_identity`、`test_oms_me_uses_verified_platform_identity_and_local_action` 共 **14 passed**；随后管理授权/OMS/TMS bootstrap 相关组合回归 **111 passed、1 skipped**。

该切片补齐了本仓库可部署的 OMS OIDC+在线状态适配装配点，但尚未替代任务 1.2 所要求的 test-cn 真实 `eduplus-platform-admin` 授权码登录、token `aud/azp`、真实状态端点响应和撤权证据；因此 1.2/2.1/5.1 仍不勾选。

## 2026-09-28 回归验证补充

- 企业后端全量：`PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short` → **761 passed、3 skipped、2 warnings**。
- Core/WS 兼容：`tests/api/test_unified_ws_turn_runtime.py`、`tests/runtime/test_request_contracts_subagent.py`、`tests/services/skill/test_runtime_skill_provider_hook.py`、`tests/runtime/test_externalized_dynamic_resource_entrypoints.py` → **41 passed、4 warnings**。
- 前端原型：`npm test` → **250 passed / 25 files**；`npm run typecheck:oms`、`npm run typecheck:tms`、`npm run lint` 均通过。
- OpenSpec：`openspec validate --all --strict` → **30 passed、0 failed**。
- 上游兼容只读检查：`git merge-tree --write-tree HEAD upstream/main` exit 0，未实际 merge/rebase。

## 未完成与门禁

任务 1.3 现有入口盘点与 3.1 PG 基础事实迁移已完成；1.1 因用户最新“Enterprise 程序授权 + 真实订阅 actor 首位引导”边界而重新打开，须同步受影响提案并复核。1.2 外部认证/身份及真实事件合同/实测缺口与 upstream 实际合并演练尚未完成。2.1/2.2、3.2–3.4、4.1–4.3、5.1–5.2 均未完整交付；OMS Client ID 已由用户指定，但尚缺该 Client 在目标环境的真实登录、audience 与身份有效性验证，以及真实订阅 actor/学校绑定和 actor-sub 合同、初始平台人员安全登记、完整授权/审批/委托写服务、正式管理 API、真实数据 UI 与 test 联调。正式 OMS/TMS 写路由继续不装配。任务 3.1 只证明本仓库既有迁移及测试，尚未包含事件即时开启记录；不得把它、合成 JWT、原型 fixture 或 Webhook demo 记作后续入口验收通过。

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
- 按用户指定，真实 `subscription.created.actor.user_id` 成为**本产品的一次性首位 TMS 管理员身份来源**；不是 EduPlus2 权限 API 判定。公开 [事件类型](https://eduplus-test.f123.pub/docs/webhook/event-types/) 与 [事件格式](https://eduplus-test.f123.pub/docs/webhook/)仍明确 `actor` 可选、system 可为 null；故正式规则限定已验签、非 mock、应用/学校/订阅绑定、`actor.type=user` 且 ID 非空，在 Webhook 事务内直接创建/激活唯一 `school_admin` assignment，并保留 consumed actor 记录用于审计/幂等/后续合同核验。mock、错校、重放、恢复/重订不产生新授权；真实 actor 与后续 OIDC `sub` 合同仍需 test-cn 证据。
- 管理授权、TMS 业务、生命周期 Webhook 与 TMS 原型的 OpenSpec 合同已向此边界修订；旧学校侧双负责人首位开通不再实施。开发态 TMS 原型已撤下双负责人模拟，改为订阅 Webhook 等待、即时开启、缺 actor、mock 等场景；前端定向测试先红后绿 **23 passed**，仍无真实身份/事件/API。当前 1.1 须对最新受影响提案再复核，故进度 **2/14**，正式管理路由保持未装配。

### 2026-09-27 TMS actor 原型浏览器复核与文案修正

- 浏览器核对 Webhook 等待、即时开启、无有效 actor、控制台 mock 等状态；mock/无 actor 均无开启入口，演示开启须二次确认且标注仅合成演示。发现无 actor/mock 时仍展示“已验签真实 actor 来源”，通过测试先红后绿修正为无可激活身份。桌面 1440×900、窄屏 390×844 截图与 Console 0 errors 见 [双端原型审计](../add-c1-oms-operations-prototype/prototype-browser-audit-2026-09-27.md)。全量前端 25 文件 **250 passed**，TMS typecheck、lint、build 均成功。此证据只完成 TMS 开发原型任务 3.11，不改变正式事件、身份及 API 未交付状态。

### 2026-09-27 OMS Skill 动作目录增量迁移

- 新增 `management/0004_oms_skill_actions.sql`，仅在本仓库 `management` schema 中登记 `ops.skills.read/manage/review/publish` 的 `platform` 范围和 `ops.skills.grant` 的目标 `school` 范围；`platform_security_admin`、`platform_config_admin`、`platform_operator` 增加各自 v2 **候选模板**，v1 assignment 不自动升级、主体不自动赋权。受限数据库 owner 仍受 FORCE RLS，迁移事务显式设置 OMS 应用域；`MigrationRunner.verify()` 检查五个动作的范围/敏感度/状态及 v2 模板是否漂移。
- 测试先见新目录为空、后见受限 owner 在 RLS 下无法执行新增迁移，以及动作退役后 verify 未报错，逐项修复；临时 PG `test_management_authorization_migration.py` 与 `test_persistence.py` 合计 **64 passed**。此项是 3.2 的权限事实前置，不是应用层 PEP、正式 OMS API/UI 或外部平台登录已完成；3.2 仍未勾选。没有改 EduPlus2、OpenFGA、Keycloak 或真实学校数据。

### 2026-09-28 OMS 受保护入口局部装配

- 新增 `/api/v1/oms/me` 和模型清单/草稿的独立 Bearer 分流；每次请求调用已验签平台身份、显式在线状态检查器和 DeepTutor 本地 `ops.*` PEP。草稿写入在单 PG 事务内复核 `ops.providers.manage`、目标版本和审计，不能靠 PG role/JWT role 放行；无本产品角色或只有 `ops.oms.access` 均不能读写模型。默认 verifier/在线检查器不配置时返回 503，不复用租户会话。合成 PG/API 测试随企业套件 **521 passed、3 skipped**。真实 `eduplus-platform-admin` 授权码/账号状态合同、平台初始管理员、独立 OMS 会话和跨学校权限仍未验收，3.2/5.1 不勾选。

### 2026-09-29 OMS/TMS 同源权限摘要与学校范围入口切片

- OMS `/api/v1/oms/me` 入口从仅接受平台范围 `ops.oms.access`，扩展为也接受经 DeepTutor Enterprise 本地 PEP 逐校复核通过的 school-scope `ops.oms.access`；普通学校范围 operator 只能进入其被授权学校，不能获得平台级动作或跨学校模型写权限。
- 新增 `/api/v1/oms/me/permissions`，从本地 `management.*` 事实查询候选动作，再逐项调用 `require_platform_permission` 复核后返回 `platform_actions` 与按学校分组的 `school_actions`。该摘要只服务正式前端显隐/路由守卫，业务 API 仍逐请求 PEP，不把 PG/RLS 可见性当作操作者授权。
- 新增 `/api/v1/tms/me/permissions`，复用 TMS OIDC 身份适配器、已验签 Webhook 学校投影、当前学校绑定和本地 `tenant.*` assignment；激活后的首位学校管理员在 AI 资源尚未 ready 时仍可获得 TMS 管理入口权限摘要，但不会因此获得 AI 业务运行资格。摘要只返回当前学校 `tenant.*` 动作，不暴露 `ops.*`。
- 新增失败优先测试覆盖：只有学校范围 OMS operator 可进入 `/oms/me` 与权限摘要、只见被授权学校、跨学校详情和平台模型写为 403；已激活 TMS 管理员可通过 `/tms/me/permissions` 获取本校 `tenant.*` 摘要且不泄露 `ops.*`。定向回归 `test_application.py` 与 `test_webhook_authority.py` 相关 5 项通过。
- 该切片仍不完成 3.2：真实 `eduplus-platform-admin` 授权码登录、真实 TMS 本人登录证据、完整 OMS/TMS 写 API 与前端按钮级 403/200/409、CLI/WS/SDK 旁路审计以及 5.1 test-cn 放行仍未闭合。任务勾选保持 3/14。

### 2026-09-29 TMS 权限管理只读 DTO 切片

- 新增 `/api/v1/tms/permissions` 只读当前学校权限管理 DTO，进入前必须通过 TMS OIDC/Webhook 学校身份适配器，并在当前学校事务中复核 `tenant.permissions.manage`。响应只包含 `application=tms`、当前 `school_id`、`tenant.*` action catalog、当前学校角色模板/自定义角色、当前学校 principal 与 assignment；不返回 `ops.*`、供应商成本、Secret、跨学校数据或额度写能力。
- 该接口只读，不调用 `grant_management_role`/`revoke_management_role`，不开放低风险授予或高风险审批写入口；后续 TMS 成员/角色写入仍须独立完成命令、审批和按钮级 403/409 验收。
- TDD 先见 `/api/v1/tms/permissions` 在当前中间件/路由下返回 401，补正式路由和 middleware 白名单后变绿。新增用例覆盖：已激活 `school_admin` 可读本校权限 DTO；同校 `school_operator` 因缺 `tenant.permissions.manage` 返回 403；响应中所有 action 均为 `tenant.*` 且不含 `ops.*`。
- 定向回归：`test_application.py` 与 `test_webhook_authority.py` 相关 6 项通过。此切片仍不完成任务 3.4 或 4.3，因为正式写入、成员目录、审批 UI/API、角色扩权确认、撤权即时生效的端到端验收仍未闭合。

### 2026-09-29 OMS 权限管理只读 DTO 切片

- 新增 `/api/v1/oms/permissions` 只读平台权限管理 DTO，进入前必须通过 `eduplus-platform-admin` OIDC 适配器、在线账号检查和 DeepTutor 本地 `ops.permissions.manage` PEP。响应只包含 `application=oms`、`ops.*` action catalog、OMS 角色版本、OMS principal 与 assignment；不返回 `tenant.*` 或学校侧账号管理能力。
- 平台配置管理员即使具备 `ops.oms.access` 也无法读取该 DTO；只有含 `ops.permissions.manage` 的平台安全管理员可读。接口不开放平台人员授予/撤权写入，高风险授权仍待独立命令与审批 API。
- TDD 先见 `/api/v1/oms/permissions` 返回 404，补正式路由后变绿。新增用例覆盖 platform security admin 200、platform config admin 403、响应不含 `tenant.*`。
- 本轮 OMS/TMS 权限相关定向回归 7 项通过。该切片仍不完成 3.2/3.4/4.3/5.1：真实平台登录、按钮级 UI、写命令、审批与 test-cn 放行证据仍未闭合。

### 2026-09-29 OMS Skill 只读目录切片

- 新增 `/api/v1/oms/skills` 正式只读 API，进入前必须通过独立 OMS 身份、在线账号状态和 DeepTutor 本地 `ops.skills.read` PEP。该接口只返回 global Skill 的名称、最新版本、发布版本、发布 revision、sha256、描述、标签和状态；不返回 ObjectStore `object_key`、ZIP 正文、Secret、学校私有数据或运行授权。
- TDD 先见 `/api/v1/oms/skills` 返回 404，补只读投影后变绿。新增用例覆盖：具备 v2 `platform_security_admin` 的主体可读 `ops.skills.read`；只有旧 v1 `ops.oms.access`/`ops.permissions.manage` 但没有 `ops.skills.read` 的主体返回 403；响应不泄露存储对象路径。
- 定向回归：OMS Skill 列表、OMS 权限 DTO、OMS school-scope 权限摘要、TMS 权限 DTO 与 TMS 权限摘要 5 项通过。此切片推进 3.2 的 Skill 权限同 key 验收，但不开放 Skill 上传/审查/发布/授权以外的新写能力，也不完成正式 UI、真实平台登录或 5.1 test-cn 放行。

### 2026-09-29 TMS Skill 当前学校授权只读列表切片

- 按 TDD 先新增 `test_tms_skills_list_uses_current_school_grants_and_redacts_global_storage`，在未开放 TMS bearer 白名单/正式路由前返回 401，证明测试能捕获“学校管理员无法读取本校已授权 Skill”的缺口。
- 新增 `GET /api/v1/tms/skills`：仅接受已验证 TMS bearer 与当前学校上下文，要求 `tenant.tms.access`，只读取当前学校处于 active 且未过期的 global Skill grant，并回读 publication/revision 的安全元数据。
- DTO 仅包含 name、revision/publication/grant version、status、sha256、description、tags 等学校可见字段；不返回 OMS ObjectStore `object_key`、ZIP 正文、Secret、供应商成本或跨学校 grant。
- GREEN 验证：`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_webhook_authority.py::test_tms_skills_list_uses_current_school_grants_and_redacts_global_storage -q` → `1 passed in 1.57s`。
- 组合回归：`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_application.py::test_oms_me_uses_verified_platform_identity_and_local_action extensions/enterprise/tests/test_application.py::test_oms_permissions_catalog_is_platform_security_admin_only extensions/enterprise/tests/test_application.py::test_oms_permissions_summary_allows_school_scoped_operator_without_platform_grant extensions/enterprise/tests/test_application.py::test_oms_skills_list_requires_skill_read_and_redacts_storage extensions/enterprise/tests/test_webhook_authority.py::test_tms_permissions_catalog_is_current_school_scoped_and_manage_protected extensions/enterprise/tests/test_webhook_authority.py::test_tms_me_permissions_returns_local_tenant_action_summary extensions/enterprise/tests/test_webhook_authority.py::test_tms_skills_list_uses_current_school_grants_and_redacts_global_storage extensions/enterprise/tests/test_webhook_authority.py::test_tms_quota_summary_is_current_school_read_only_and_redacted extensions/enterprise/tests/test_webhook_authority.py::test_created_actor_can_activate_first_tms_admin_before_ai_runtime_ready -q` → `9 passed in 5.93s`。
- 说明：该切片继续推进 3.2/4.3 的正式 DTO 与权限一致性，但不代表 TMS 角色写入、日常授权、正式 UI、双学校真实登录或 5.1 开闸已完成；tasks 勾选保持不变。

### 2026-09-29 TMS 自定义角色与撤权写 API 切片

- 先新增 `test_tms_custom_role_publish_uses_current_school_permissions_and_blocks_ops_actions`，在路由/白名单未装配时先返回 401；随后补 `POST /api/v1/tms/roles/custom`，只接受当前学校 TMS bearer，并在当前学校事务中调用应用层 `publish_custom_role`。发布请求固定 `scope_kind=school` 与会话学校，不允许 body/header 切校；只允许 `tenant.*` 低风险动作，`ops.*` 或敏感动作返回 403。
- 首位管理员激活后由应用代码为该 `school_admin` 生成低风险 delegation upper-bound 事实，使其可发布本校低风险自定义角色；该逻辑没有使用数据库函数、触发器或 enum/check 业务约束。
- 再新增 `test_tms_assignment_revoke_is_current_school_scoped_and_protects_last_admin`，先见 `/api/v1/tms/assignments/{id}/revoke` 401；随后补正式撤权 API。撤权固定当前学校、要求 `tenant.permissions.manage`，调用应用层 `revoke_management_role` 串行复核治理授权、assignment version、目标 policy version 和最后管理员保护；重复 command_id 精确回放。
- 该切片还修正 `revoke_management_role` 在真实企业 dict_row 连接下仍用 tuple 下标、以及在数据库 owner 管理事务中自行开启 nested transaction 的问题；撤权业务规则继续在 Python 服务中执行。
- 定向验证：`test_tms_custom_role_publish_uses_current_school_permissions_and_blocks_ops_actions` → 先红 401 后绿；`test_tms_assignment_revoke_is_current_school_scoped_and_protects_last_admin` → 先红 401，再修正 dict_row/事务后绿。组合回归 `test_tms_bootstrap_http_uses_verified_token_and_signed_school_binding`、TMS permissions、custom role、assignment revoke、me permissions、TMS skills 共 **6 passed**；管理授权角色/撤权相关直接测试 **10 passed**。
- 说明：该切片推进 3.4 的 TMS 学校内角色版本与撤权命令，但还未完成成员目录搜索、目标本人登录登记到授权、低风险授予 API、高风险双人审批、正式 UI 与双学校真实登录验收；tasks 勾选保持不变。

### 2026-09-29 TMS 本人登记与低风险角色授予 API 切片

- 新增 TDD 用例 `test_tms_self_registration_then_admin_grants_low_risk_role`，先暴露 `/api/v1/tms/me/register` 与 `/api/v1/tms/members/{principal_id}/roles` 未装配、以及 `grant_management_role` 在真实 dict_row 企业连接下仍使用 tuple 下标的缺口。
- 新增 `POST /api/v1/tms/me/register`：当前学校成员使用已验签 TMS bearer 本人登记本产品 `pending` principal；只写当前 `(issuer,sub,school)` 零权主体，不创建 EduPlus2 用户、不授予角色、不读取目录。
- 新增 `POST /api/v1/tms/members/{principal_id}/roles`：学校管理员只能给当前学校已本人登记且未 disabled 的 principal 授予低风险 TMS 角色；目标学校固定为会话学校，目标身份从本地登记事实与当前学校绑定版本构造，不接受 body/header 切校或任意 subject。`school_admin` 与含敏感动作的角色仍被 `grant_management_role` 拒绝，保留独立审批缺口。
- 修正 `grant_management_role` 的 dict_row 兼容：principal/replay 读取全部通过 `_column`，避免正式企业连接下把 KeyError 错映射为 404。业务授权、版本、委托上界和幂等仍在 Python 应用逻辑中执行。
- 验证：单项用例 `test_tms_self_registration_then_admin_grants_low_risk_role` → `1 passed`；TMS 管理相关 Webhook/权限/自定义角色/撤权/本人权限/Skill 组合 → **7 passed**；管理授权直接测试 `test_management_authorization.py`、`test_management_custom_roles.py`、`test_management_custom_roles_pg.py`、`test_management_assignment_revoke_relation.py` → **42 passed**；目标 Ruff check → `All checks passed!`。
- 说明：该切片推进 3.4 的“已本人登录登记→低风险授权→撤权/摘要生效”链路；仍未完成目录搜索策略、成员列表正式 DTO、高风险双人审批、模板扩权确认 UI、正式前端按钮级验收和双学校真实登录/test-cn 开闸，因此 tasks 勾选保持不变。

### 2026-09-29 TMS 授权审计只读 DTO 切片

- 新增 TDD 用例 `test_tms_authz_audit_is_current_school_scoped_and_permission_guarded`，先见 `/api/v1/tms/authz-audit` 在正式 TMS bearer 白名单/路由未装配时返回 401，证明测试能捕获授权记录入口缺口。
- 新增 `GET /api/v1/tms/authz-audit`：仅接受已验签 TMS bearer，当前学校事务内逐次调用应用层 `require_management_permission(..., "tenant.permissions.manage")`；查询固定 `application='tms' AND school_id=<会话学校>`，分页/过滤有上限，不接受 header/body 切校。
- 响应只返回当前学校授权审计安全 DTO：event ID、actor subject、`tenant.*` action、目标、request ID、结果、原因、前后版本、审批 ID、安全摘要和创建时间；不返回 OMS `ops.*`、Webhook secret、token、Secret、成本、私有正文或跨学校记录。无治理权限的 `school_auditor` 返回 403。
- 验证：单项用例 `test_tms_authz_audit_is_current_school_scoped_and_permission_guarded` → `1 passed`；TMS permissions/audit/self-registration 组合 → **3 passed**；目标 Ruff check → `All checks passed!`。
- 说明：该切片推进 3.4/4.2/4.3 的授权记录与当前学校隔离读模型；高风险审批 API、正式 UI 授权记录页、真实双学校登录、按钮级可访问性和 5.1 test-cn 开闸仍未闭合，tasks 勾选保持不变。

### 2026-09-29 TMS 成员只读列表 DTO 切片

- 新增 TDD 用例 `test_tms_members_list_is_current_school_read_only_and_member_permission_guarded`，先见 `/api/v1/tms/members` 在正式 TMS bearer 白名单/路由未装配时返回 401，随后补正式只读入口。
- 新增 `GET /api/v1/tms/members`：仅接受已验签 TMS bearer，当前学校事务内逐项复核 `tenant.tms.access` 与 `tenant.members.read`；查询固定当前 `school_id` 的本产品 `management.principals` 与 assignment，不查询、不创建、不同步 EduPlus2 外部账号，也不接受 body/header 切校。
- 响应只包含当前学校 principal、subject、状态、policy version、角色 assignment 摘要和分页信息；`school_auditor` 因具备成员读权限可读，未登记/无权主体返回 403。DTO 不包含 OMS `ops.*`、Webhook secret、供应商成本、Secret、外部目录敏感字段或私有正文。
- 验证：单项用例 `test_tms_members_list_is_current_school_read_only_and_member_permission_guarded` → `1 passed`；TMS permissions/audit/members/self-registration/me-permissions 组合 → **5 passed**；目标 Ruff check → `All checks passed!`。
- 说明：该切片推进 3.4/4.2 的“成员列表可回读本地事实”能力；学校目录搜索、目录空范围/故障区分、高风险审批、正式 UI 接真实 DTO 与双学校真实登录仍未完成，tasks 勾选保持不变。

### 2026-09-29 TMS 高风险审批 API 切片

- 新增 TDD 用例 `test_tms_approval_lifecycle_requires_independent_school_admin`，先见 `/api/v1/tms/approvals` 未装配返回 401；随后补当前学校审批请求的创建、列表、复核与撤回正式 API。
- 新增 `GET/POST /api/v1/tms/approvals`、`POST /api/v1/tms/approvals/{approval_id}/review`、`POST /api/v1/tms/approvals/{approval_id}/withdraw`：均只接受已验签 TMS bearer，在当前学校事务内调用应用层 `management.approvals` 服务。创建请求固定 `target_school_id=会话学校` 与 operation=`school_activation`，写入 expected target policy version、idempotency key、原因和外部资格引用；不直接授予角色、不创建 EduPlus2 用户、不修改 OMS 服务授权。
- 复核要求同校另一名当前具备 `tenant.permissions.manage` 的管理员；提议人自批返回 409，目标版本漂移、终态重放或撤回也失败关闭。列表只返回当前学校本地审批事实，不包含 OMS `ops.*`、Secret、token、成本、跨校数据或私有正文。
- 验证：单项用例 `test_tms_approval_lifecycle_requires_independent_school_admin` → `1 passed`；底层审批服务回归 `test_management_approvals.py` + API 单项 → **4 passed**；TMS 管理组合（权限 DTO、自定义角色、撤权、低风险授予、审计、成员、审批、摘要、Skill、额度）→ **11 passed**；目标 Ruff check → `All checks passed!`。
- 说明：该切片推进 3.4 的高风险审批请求生命周期，但**尚未**实现“审批通过后自动/受控授予 school_admin 或敏感角色”的最终 apply API，也未完成正式 UI 和双学校真实登录验收；tasks 勾选保持不变。

### 2026-09-29 TMS 审批通过后受控 apply 切片

- 在既有审批生命周期测试中先补“审批通过后应授予学校管理员”的断言，红灯为 `/api/v1/tms/approvals/{approval_id}/apply` 返回 404；随后新增应用层 `apply_approved_school_activation` 与正式 API。
- `POST /api/v1/tms/approvals/{approval_id}/apply` 仅处理当前学校已批准的 `school_activation` 请求，调用方仍须当前具备 `tenant.permissions.manage`。服务在同一事务内锁定审批请求、目标 principal、学校绑定版本、目标 policy version 和幂等 command；提议未批准、目标版本漂移、已存在管理员、命令重用均失败关闭。
- apply 成功后只写 DeepTutor 本地事实：目标 principal 激活、插入 `school_admin` assignment、为该管理员生成低风险委托上界、推进目标 policy version 并追加授权审计；不创建或修改 EduPlus2 用户，不触碰 OMS 服务授权/额度。
- 验证：更新后的 `test_tms_approval_lifecycle_requires_independent_school_admin` → `1 passed`，覆盖创建、重放、自批 409、独立复核、apply、apply 重放与目标本人权限摘要生效；底层审批服务 + API 单项 → **4 passed**；TMS 管理组合 → **11 passed**；目标 Ruff check → `All checks passed!`。
- 说明：此切片完成 `school_admin` 审批后的受控 apply；敏感角色/委托上界扩展的通用 apply、模板扩权确认、学校目录搜索、正式 UI 与双学校真实登录仍未完成。

### 2026-09-29 TMS 学校目录失败关闭 DTO 切片

- 新增 TDD 用例 `test_tms_directory_search_fails_closed_when_external_contract_missing`，先见 `/api/v1/tms/directory/users` 未装配返回 401；随后补正式只读安全 DTO。
- `GET /api/v1/tms/directory/users` 仅接受当前学校 TMS bearer，并逐次复核 `tenant.tms.access` 与 `tenant.members.read`。在 EduPlus2 第三方应用授权码用户令牌、DataAccessPolicy/UserAccessPolicy 与目录范围未核实时，固定返回 `status=not_enabled`、`reason_code=external_directory_contract_missing` 和空 users；不返回合成用户、不调用 M2M 目录、不泄露 `ops.*`、Secret、token、成本或外部敏感字段。
- 验证：单项用例 → `1 passed`；目录/成员/审批组合 → **3 passed**；目标 Ruff check → `All checks passed!`。
- 说明：该切片只完成“目录合同缺失时失败关闭且可区分状态”；真实目录搜索、空范围/空结果/上游故障语义、正式 UI 接线仍待外部合同与后续验收。

### 2026-09-29 正式 OMS/TMS 受控入口壳切片

- 按 TDD 新增 `formal-management-gates.test.tsx`，先见正式组件缺失导致测试无法解析，随后补正式入口壳。
- 新增 `OmsFormalApp` 与 `/oms/[[...slug]]`：仅通过 `credentials=include` 读取 `/api/v1/oms/me`、`/api/v1/oms/me/permissions`、`/api/v1/oms/skills`；真实平台身份或本地 `ops.*` 授权失败时显示“正式入口未开放”，不回退开发原型、不渲染授权/发布/审批/学校开通写按钮。Skill 列表只显示安全元数据。
- 新增 `TmsFormalApp` 与 `/tms/{schoolCode}/[[...slug]]`：仅读取当前学校 `/api/v1/tms/me/permissions`、`school-bootstrap/status`、`directory/users`、`members`、`approvals`、`authz-audit`、`skills` 安全 DTO；当前学校身份/绑定/`tenant.*` 授权失败时显示“学校入口未开放”，不使用合成目录兜底、不显示授予/撤销/审批/新增写按钮。
- 验证：`npm test -- formal-management-gates.test.tsx` → 4 passed；`npm run typecheck:oms`、`npm run typecheck:tms` 均通过；`npm test -- formal-management-gates.test.tsx management-authorization-prototype.test.tsx` → 27 passed。
- 说明：该切片只闭合正式入口壳与只读 DTO 接线；正式写入 UI、真实目录、双学校真实登录、真实平台授权码证据及 5.1 开闸仍未完成。

### 2026-09-29 审批通用 apply 与 OMS 写入口接线切片

- 按 TDD 先在 `test_management_approvals.py` 新增平台敏感角色授予与委托上界扩展两个失败用例，红灯为 `apply_approved_management_approval` 不存在；随后新增前向迁移 `management/0009_approval_apply_payload.sql`，为审批请求保存不可变 apply 载荷：目标角色 key/version、目标动作集合、授权到期时间和显式确认的模板版本。迁移只增列，不新增 DB function、trigger、PG enum 或 enum-like CHECK。
- 新增应用层 `apply_approved_management_approval`：`school_activation` 继续走当前学校 `school_admin` 受控 apply；OMS `platform_grant` 仅按审批载荷中已显式确认的角色模板版本写入 assignment，不自动套用最新模板；OMS `delegation_expand` 仅按审批载荷中的动作集合扩展委托上界。三类 apply 均在事务中复核当前治理权限、委托上界、目标 policy version、命令幂等和追加审计，PG RLS/role 仍只是隔离兜底。
- 正式 `/oms` 前端新增获授权写按钮接线：`ops.providers.manage` 才显示模型与 Provider 草稿测试/发布/回滚；`ops.skills.review/publish/grant` 才显示 Skill 审查、发布和首个已授权学校 grant。所有 payload 均从安全 DTO 的 version/revision/sha256/school_id 构造，不允许输入学校 ID 或 Secret。
- 验证：
  - `.venv/bin/python -m pytest extensions/enterprise/tests/test_management_approvals.py -q` → **5 passed**；
  - `.venv/bin/python -m pytest extensions/enterprise/tests/test_management_authorization_migration.py -q` → **31 passed**；
  - `cd extensions/enterprise/frontends && npm run typecheck:oms && npm run typecheck:tms` → 通过；
  - `cd extensions/enterprise/frontends && npm test -- formal-management-gates.test.tsx management-authorization-prototype.test.tsx tms-drawer.test.tsx tms-service-projection.test.tsx apps.test.tsx` → **55 passed**。
- 说明：该切片完成本地可验证的通用 apply、模板版本显式确认和正式 OMS 写按钮接线；真实平台目录候选、真实 `eduplus-platform-admin` 登录、双学校真实负例、审批竞态与完整可访问性矩阵仍未完成，5.1 不开闸。


### 2026-09-29 正式 TMS 授权写入 UI 接线切片

- 在 `formal-management-gates.test.tsx` 先补“低风险授予、撤权、审批 apply 必须调用正式安全 API”的失败用例，红灯为正式 TMS 页面无对应按钮。
- `TmsFormalApp` 在 `tenant.permissions.manage` 存在时才渲染写入动作：
  - 成员无 `school_auditor` 时调用 `POST /api/v1/tms/members/{principal_id}/roles`，payload 固定 `role_key=school_auditor`、`role_version=1`、成员 DTO 的 `policy_version` 和 command id；
  - 可撤销 assignment 调用 `POST /api/v1/tms/assignments/{assignment_id}/revoke`，payload 使用 assignment `version` 与成员 `policy_version`；
  - 已批准审批调用 `POST /api/v1/tms/approvals/{approval_id}/apply`，payload 使用审批 DTO 的 `expected_target_policy_version`。
- UI 不允许从页面 body/header/URL 输入学校 ID；动作全部来自当前学校安全 DTO。失败时只显示错误，不用开发原型或合成数据兜底。
- 验证：`npm test -- formal-management-gates.test.tsx` → 5 passed；`npm run typecheck:tms` 通过；`npm test -- formal-management-gates.test.tsx management-authorization-prototype.test.tsx tms-drawer.test.tsx tms-service-projection.test.tsx` → 35 passed。
- 说明：真实目录策略、跨学校真实负例、审批竞态和完整桌面/窄屏/键盘可访问性矩阵仍待后续验收。


### 2026-09-29 正式 TMS 额度/用量与服务访问只读 UI 切片

- 按 TDD 新增正式 TMS 额度/用量和服务访问 DTO 测试，红灯为页面未展示“额度与用量”。
- `TmsFormalApp` 仅在权限摘要包含 `tenant.quotas.read` / `tenant.usage.read` 时读取 `/api/v1/tms/quotas`，仅在包含 `tenant.access.manage` 时读取 `/api/v1/tms/service-access`，避免无权主体因额外 DTO 403 阻断成员页。
- 新 UI 只读展示当前学校 quota grants、usage/usage_details 和 service access grants；不展示 OMS 成本、供给来源、Provider Secret，不提供“授予额度/调整额度”等写按钮。
- 验证：`npm test -- formal-management-gates.test.tsx` → 6 passed；`npm run typecheck:tms` 通过；`npm test -- formal-management-gates.test.tsx management-authorization-prototype.test.tsx tms-drawer.test.tsx tms-service-projection.test.tsx apps.test.tsx` → 47 passed。

## 2026-09-29 正式 OMS 模型/Provider 只读 UI 切片

- 新增正式 OMS `/oms` 入口中的“模型与 Provider”只读区：在 `ops.providers.read` 动作存在时读取 `/api/v1/oms/models/draft` 与 `/api/v1/oms/provider-settings`，否则不加载该能力面。
- Provider 凭据只展示后端安全 DTO 返回的脱敏值（例如 `<redacted>`），页面不渲染 `env:` 引用、`sk-` 明文、保存、发布、回滚或测试按钮。
- 前端测试 `formal-management-gates.test.tsx` 覆盖模型草稿、Provider 设置、Secret 不泄漏和写入口不暴露，作为 4.1.2/4.3.2.4 的合成验收证据；真实平台目录、正式 OMS 写 API 与按钮级真实账号验收仍保留在 4.1.3/5.1。

## 2026-09-29 正式 TMS 学校目录状态 UI 切片

- 正式 TMS `/tms/{schoolCode}` 新增“学校目录”只读区，显示后端 `/api/v1/tms/directory/users` 的 `status/reason_code/message/users`，并把外部目录与 DeepTutor 本地成员授权列表分开呈现。
- UI 明确区分 `not_enabled`、`no_permission`、`empty_scope`、`empty`、`failed`、`enabled`；目录不可用、空范围或外部失败时不回退原型 fixture 或合成用户。
- 前端测试 `formal-management-gates.test.tsx` 使用合成安全 DTO 覆盖空范围、空结果和外部失败三态，作为 4.2.3.2.4/4.3.2.5 的本地验收证据；真实目录策略合同、双学校登录、可访问性矩阵和审批竞态仍保留在 4.2.3.2.5/4.3.2.6。

## 2026-09-29 正式 OMS 治理只读聚合 UI 切片

- 正式 OMS `/oms` 新增治理只读区：`/api/v1/oms/summary`、`/api/v1/oms/resources/status`、`/api/v1/oms/tenants`、`/api/v1/oms/supply`、`/api/v1/oms/audit`、`/api/v1/oms/cost` 按当前平台主体的本地 `ops.*` 动作摘要条件加载。
- 页面只展示后端安全 DTO 与 descriptor/status 文案：学校列表仅来自已授权 school-scope，供给/额度底座只读，成本为 OMS-only 状态，不从租户额度或用量推导，不暴露补充、授权、调整、成本导出或密钥按钮。
- 前端测试 `formal-management-gates.test.tsx` 覆盖资源、学校、供给、审计、成本 DTO 聚合与写入口不暴露，作为 4.1.3/4.3.2.6 的本地验收证据；正式 OMS 写入、真实平台目录候选和按钮级真实账号验收仍保留在 4.1.4/5.1。

## 2026-09-29 正式 OMS 学校用量/任务只读 UI 切片

- 正式 OMS `/oms` 在当前主体具有 `ops.usage.read`/`ops.jobs.read` 且存在已授权学校时，按首个已授权学校只读加载 `/api/v1/oms/schools/{school_id}/usage` 与 `/api/v1/oms/schools/{school_id}/jobs`。
- 页面仅展示 attempt、operation、service、状态和脱敏单位汇总，不展示学校私有正文、用户输入或 provider Secret，也不渲染结算、释放、核销或强制完成按钮。
- 前端测试 `formal-management-gates.test.tsx` 覆盖学校用量 attempt 与远端未知任务 DTO 接线，作为 4.1.4/4.3.2.7 的本地验收证据；跨学校真实负例、分页筛选和写操作仍保留在后续任务。

### 2026-09-29 正式 OMS 授权写 API 与治理 UI 切片

- 按 TDD 先新增 `test_oms_approval_api_applies_platform_sensitive_role` 与 `test_oms_principal_school_scope_grant_and_disable_are_guarded`，红灯分别为 `/api/v1/oms/approvals`、`/api/v1/oms/principals/{principal_id}/roles` 等正式写 API 404；随后补 OMS 授权写路由。
- 新增正式 OMS 授权 API：
  - `GET/POST /api/v1/oms/approvals`、`POST /api/v1/oms/approvals/{approval_id}/review|withdraw|apply`：复用应用层审批服务，`platform_grant` 必须带目标角色 key/version、显式确认的模板版本和授权有效期；`delegation_expand` 必须带目标动作集合。创建、复核、apply 均重新通过本地 `ops.permissions.manage`、目标 policy version、委托上界和命令幂等校验。
  - `POST /api/v1/oms/principals/{principal_id}/roles`：只给已登记 OMS 平台主体授予低风险学校范围角色，学校范围固定为受控 `target_school_id`，未委托学校返回 403；敏感或管理员角色仍必须走双人审批。
  - `POST /api/v1/oms/assignments/{assignment_id}/revoke` 与 `POST /api/v1/oms/principals/{principal_id}/disable`：在事务中复核治理权限、学校锁/平台锁、assignment/principal 版本和最后管理员保护，撤权/停用立即影响 PEP。
- 修正 `disable_management_principal` 在企业 `dict_row` 连接下误用 tuple 下标的问题；业务规则仍在 Python 程序逻辑内执行，不新增 DB 函数、触发器、存储过程或 enum-like CHECK。
- 正式 `/oms` 前端新增“平台授权治理”区：读取 `/api/v1/oms/permissions` 与 `/api/v1/oms/approvals`，展示平台主体、角色、assignment、审批和审计回读；按钮按 `ops.permissions.manage` 显隐，并把平台授权审批、学校只读范围授予、assignment 撤权、审批复核/apply、主体停用接入对应正式 API。所有 payload 都来自安全 DTO 的 principal/role/assignment/approval/school/version，不允许输入学校 ID、Secret 或借学校账号开通。
- 验证：
  - `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -k 'oms_approval_api_applies_platform_sensitive_role or oms_principal_school_scope_grant_and_disable_are_guarded' -q` → **2 passed**；
  - `cd extensions/enterprise/frontends && npm test -- formal-management-gates.test.tsx -t 'OMS 正式入口接入平台人员'` → **1 passed**。
- 说明：此切片闭合了本地合成可验证的正式 OMS 授权写 API 和 UI 接线；真实 `eduplus-platform-admin` 授权码登录、真实平台目录候选、双学校真实负例、审批并发竞态、完整可访问性矩阵、CLI/WS/SDK 旁路审计和 test-cn 开闸仍未完成。

### 2026-09-29 OMS `eduplus-platform-admin` local-ssl 授权码登录与 fail-closed 切片

- 通过 `local-ssl` 以 `https://deeptutor.lfun.pub` 打通 OMS 授权码登录：新增 `/api/v1/oms/auth/start`、`/api/v1/oms/auth/callback`、`/api/v1/oms/auth/status`、`/api/v1/oms/auth/logout`，`client_id=eduplus-platform-admin`。2026-09-29 后续修正为 BFF 登录边界：EduPlus2 redirect URI 指向前端 `/oms/auth/callback`，前端仅转交 `code/state`，后端 BFF API 完成 token exchange 并写入 httpOnly `dt_oms_token`、`dt_oms_refresh` 与 CSRF cookie；OMS cookie 写请求要求 Origin 与 CSRF 双校验；API 仍逐次调用 DeepTutor Enterprise PEP，不从 EduPlus2 JWT role/权限派生任何 `ops.*`。
- 真实 test-cn 回调诊断显示 `access_token` 为 issuer `https://eduplus-auth-test.f123.pub/realms/eduplus`、aud `account`、azp `eduplus-platform-admin`、typ `Bearer`、稳定 subject hash；`id_token` 为 aud `eduplus-platform-admin`、typ `ID`。EduPlus2 `/api/v1/me/profile` 对该 OMS client access token 返回 401，因此按“EduPlus2 仅作认证及身份识别来源”修正为显式 `DT_EDUPLUS2_OMS_ACCOUNT_STATUS_URL=off` 的 token-only 身份状态策略。
- 本地验证：授权码回调返回 `oms_login=ok`；同一浏览器 Cookie 访问 `/api/v1/oms/auth/status` 后端返回 200；访问 `/api/v1/oms/me` 后端返回 403，证明外部认证成功但未登记本地 `ops.oms.access` 时仍失败关闭。
- 正式 OMS 页面新增初始 fail-closed 与请求超时保护：即使 dev/HMR 或浏览器扩展导致 client effect/API 请求异常，也显示“正式入口未开放”，不无限 loading、不回退开发原型、不展示授权/发布/审批/学校开通写按钮。
- 验证：`pytest test_oms_platform_identity.py -k token_only` 红绿后通过；`pytest test_oms_platform_identity.py test_preflight.py -k 'token_only or oms_identity_can_explicitly_use_token_only_status_policy'` → 2 passed；`npm test -- formal-management-gates.test.tsx -t 'OMS API 请求挂起'` 红绿后通过；`npm test -- formal-management-gates.test.tsx -t 'OMS'` → 16 passed；本地浏览器/后端日志验证 status 200 与 `/me` 403。
- 说明：该切片只闭合真实 OMS 认证会话与本地权限失败关闭；尚未登记首位/平台管理员本地 `ops.*`，未完成真实写 API 联调、双学校负例、CLI/WS/SDK/后台旁路审计和 upstream mergeability smoke，因此 1.2.4、2.1.4、3.2.5.2 父任务仍保持未完成。

### 2026-09-29 OMS 登录链路全链路复测

- 本地 HTTPS 与路由：`local-ssl status` 显示 dnsmasq/nginx 运行中，`deeptutor.lfun.pub -> 127.0.0.1`，证书有效；本地后端监听 `127.0.0.1:8001`，OMS 前端监听 `127.0.0.1:3782`。
- CLI 路由烟测：`https://deeptutor.lfun.pub/oms` 返回 200；`/api/v1/oms/auth/start?return_to=...` 返回 303，并跳转 EduPlus2 Keycloak `client_id=eduplus-platform-admin` 与 DeepTutor OMS callback。
- 真实浏览器链路：Chrome 打开 OMS auth/start 后通过既有 EduPlus2 SSO 回调到 `https://deeptutor.lfun.pub/oms?...&oms_login=ok`；页面展示“正式入口未开放”，不回退开发原型，不展示写操作入口。
- Cookie/PEP 复测：同一浏览器会话访问 `/api/v1/oms/auth/status?probe=login-chain-20260929`，后端日志返回 200；访问 `/api/v1/oms/me?probe=login-chain-20260929`，后端日志返回 403。结论：EduPlus2 认证会话有效，DeepTutor 本地 `ops.*` 未授权时按预期失败关闭。
- 限制：该复测未新增本地平台管理员授权事实，因此不能验证获授权后的 OMS 写 UI；也未触碰 EduPlus2 代码、配置或权限系统。

### 2026-09-29 OMS 登录 BFF 回调修正切片

- 按职责分离修正 OMS OAuth：`DT_EDUPLUS2_OMS_REDIRECT_URI` 默认为/部署为前端 `https://<host>/oms/auth/callback`；前端页面只读取授权码参数并调用同源 `/api/v1/oms/auth/callback`，不接触 EduPlus2 access token 或 refresh token。
- 后端 BFF API 使用授权码换取 EduPlus2 `access_token`/`refresh_token`，验证平台 access token 后只通过 httpOnly cookie 建立 OMS 会话；响应 JSON 仅返回登录状态和 `return_url`，不回传 provider token。access token 过期时正式 OMS 页面调用 `/api/v1/oms/auth/refresh`，由后端用 httpOnly refresh token 换新 access token，并要求 BFF CSRF header/cookie 匹配。
- 验证：`.venv/bin/python -m pytest extensions/enterprise/tests/test_oms_oauth_flow.py -q` → **4 passed**；`cd extensions/enterprise/frontends && npm test -- oms-auth-callback.test.tsx` → **1 file / 2 tests passed**。
- 说明：该切片只修正登录职责边界与 refresh 机制，不新增任何 `ops.*` 授权事实，也不改变 EduPlus2 仓库或配置。

### 2026-09-29 审批竞态与正式入口可访问性本地验收切片

- 后端新增审批 apply 并发竞态测试：同一个已批准 OMS `platform_grant` 被两个不同 `command_id` 同时 apply 时，程序事务锁、目标 principal policy version 与既有 active assignment 检查确保只有一个 assignment 生效，另一个失败关闭；不依赖数据库函数、触发器或 PG 角色放行。
- 前端新增正式 OMS/TMS 桌面与窄屏语义验收：在 1280px 与 390px 视口下分别验证正式入口 `main` aria label、关键 section heading、搜索框 label、命名写按钮，以及键盘 Enter 能触发受控写 API；不使用开发原型或合成目录兜底。
- 验证：
  - `.venv/bin/python -m pytest extensions/enterprise/tests/test_management_approvals.py -q` → **6 passed**；
  - `cd extensions/enterprise/frontends && npm test -- formal-management-gates.test.tsx` → **20 passed**。
- 说明：该切片闭合本地可验证的审批并发与可访问性矩阵部分；真实跨学校负例、真实目录策略合同、真实账号按钮级验收和 test-cn 开闸仍需外部环境证据，相关父任务保持未完成。

### 2026-09-29 CLI/WS/SDK/后台旁路审计切片

- 扩展 `test_oms_management_entrypoints.py`：
  - 固定企业 CLI 仍只暴露 schema/bootstrap/account/session/serve/confirm-stopped/recovery，不新增 OMS/TMS/Provider/额度管理写命令；
  - 固定通用 `DeepTutorApp` SDK facade 不暴露 `oms`、`tms`、`configure_provider`、`grant_quota`、`publish_skill`、`upsert_secret` 等管理写方法；
  - 固定旧发送端在线授权 client `deeptutor_enterprise.oms.authorization` 不可导入；
  - 固定 WS `ClientCommand` 协议拒绝 `oms_grant_role`、`tms_approve_school_admin` 以及 `start_turn` 顶层管理写字段；
  - 静态扫描 `deeptutor/` 与 `deeptutor_cli/`，确认 core/CLI/SDK/后台路径不直接导入 `deeptutor_enterprise.management`、不直接写 `management.assignments`/`management.principals`/`management.approval_requests`，不硬编码 `ops.permissions.manage`/`tenant.permissions.manage` 管理放行。
- 验证：`.venv/bin/python -m pytest extensions/enterprise/tests/test_oms_management_entrypoints.py -q` → **7 passed**。
- 说明：该切片只闭合本仓库通用入口旁路审计；真实环境写 API 联调、当前 upstream mergeability smoke 和 test-cn 真实账号验收仍属 3.2.5.2/5.1 未完成项。

### 2026-09-29 upstream mergeability 只读 smoke

- 执行只读 Git 检查，未修改工作区 Git 状态：`origin=https://github.com/LFunTech/DeepTutor.git`，`upstream=https://github.com/HKUDS/DeepTutor.git`。
- 当前 `HEAD=df11a3a3fe12ab5232e568b69770849e30b55fae`；本地 `upstream/main=ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`；`git merge-base HEAD upstream/main` 同为 `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`。
- `git merge-tree <merge-base> HEAD upstream/main` 未发现 `<<<<<<<`、`changed in both`、`added in both`、`removed in` 等文本冲突标记。
- 说明：这是当前本地 upstream ref 的只读 smoke，不等同于提交前完整 upstream 合并演练；真实环境写 API 联调和 test-cn 账号验收仍未完成。

### 2026-09-29 test-cn OMS/TMS 前端打包与 BFF 回调入口修正切片

- test-cn `deploy/test-cn/v1.4.0-rc.58` 部署后复测发现：`/api/v1/oms/auth/start` 已正确生成 EduPlus2 Keycloak 跳转，`redirect_uri=https://llm-agent-test.f123.pub/oms/auth/callback`；后端 BFF `/api/v1/oms/auth/callback` 与 refresh/status API 按预期失败关闭/鉴权。但运行时镜像 `/app/web/.next/server/app` 只包含核心 Web 前端，未包含独立 enterprise OMS/TMS 前端产物，导致浏览器访问 `/oms/auth/callback` 与 `/tms/{schoolCode}` 返回 404。
- 根因：Woodpecker 已编译 enterprise OMS/TMS 前端，但 protected runtime 镜像只复制核心 `frontend-build` 产物并直接运行核心 Next `server.js`；OMS/TMS 独立 Next app 没有被打包进运行时，也没有入口网关按路径分流。
- 修正：OMS/TMS 独立 Next app 改为以 `basePath=/oms`、`basePath=/tms` 构建，把正式入口、BFF 回调和 prototype 路由移动到 basePath 下的应用根路由；新增 `enterprise-frontends-builder` Docker stage，Woodpecker 用 Kaniko 产出 `enterprise-frontends-build` artifact image；protected runtime 复制 OMS/TMS standalone/static/public 产物。
- 运行时新增前端网关：对外仍只暴露 `FRONTEND_PORT=3782`，网关将 `/oms/*` 分流到 OMS standalone、`/tms/*` 分流到 TMS standalone、`/api/*`/`/ws/*`/`/health*` 分流到后端，其余路径保留核心 Web 前端；同 Pod 内部端口不新增 Kubernetes Service 暴露面。
- 本地验证：`woodpecker-cli lint .woodpecker/protected-k8s-release.yml` 通过（仅保留既有 clone image allowlist warning）；`pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py extensions/enterprise/tests/test_webhook_release_secret.py extensions/enterprise/tests/test_preflight.py -q` → **49 passed**；`npm test -- formal-management-gates.test.tsx oms-auth-callback.test.tsx school-routing.test.tsx` → **32 passed**；`npm run typecheck:oms && npm run build:oms && npm run typecheck:tms && npm run build:tms` 通过；本地 gateway smoke 验证 `/oms/auth/callback` → 200、`/tms/test-school` → 200、`/api/v1/oms/auth/status` → 后端 401。
- 说明：该切片修正的是部署产物与前端职责边界的运行时可达性问题，不新增任何 `ops.*` 或 `tenant.*` 授权事实，不改变 EduPlus2 仓库/配置；test-cn 仍需重新打 tag 部署后复测真实 OMS BFF 回调与正式 TMS URL。

### 2026-09-29 test-cn OMS query 落地页网关修正切片

- rc.59 部署后真实浏览器复测显示：`/oms/auth/callback` 已能返回 OMS 回调页面，但缺少 `code/state` 时前端跳转到 `/oms?oms_login=failed&reason=code_or_state_missing` 后显示核心 Web 404。原因是前端网关使用原始 `req.url` 做精确匹配，带 query 的 `/oms?...` 未命中 `/oms`，被错误转发到 core frontend。
- 修正：网关先用 `new URL(req.url, ...)` 提取 pathname，再按 pathname 分流；`/oms?*`、`/oms/*?*`、`/tms/*?*`、`/api/*?*` 和 `/health?*` 均保留原始 path+query 转发到正确 upstream。
- 回归验证：新增 `extensions/enterprise/tests/test_frontend_gateway.py`，用本地 dummy backend/core/oms/tms 验证 `/oms?oms_login=ok`、`/oms/auth/callback?code=x`、`/tms/test-school?tab=members`、`/api/v1/oms/auth/status?probe=1`、`/health?probe=1` 与普通 core 路由的分流；`pytest extensions/enterprise/tests/test_frontend_gateway.py ... test_preflight.py -q` → **50 passed**，`woodpecker-cli lint .woodpecker/protected-k8s-release.yml` 仅保留既有 clone allowlist warning。
- 说明：该切片只修复网关查询串分流，不改变 BFF token 交换、EduPlus2 配置或本地授权事实；仍需重新发布后在 test-cn 复测真实浏览器回调落地。

### 2026-09-29 test-cn OMS identity contract 流水线注入修正切片

- rc.60 真实 OMS 授权码登录复测：EduPlus2/Keycloak redirect URI 已放行，浏览器成功带 `code/state` 回到 `https://llm-agent-test.f123.pub/oms/auth/callback`；前端 BFF 调用后返回 `identity_verification_failed`。
- 后端日志显示 access token/id token 均已换取并脱敏解码：issuer=`https://eduplus-auth-test.f123.pub/realms/eduplus`、`azp=eduplus-platform-admin`、access token `aud=account`、id token `aud=eduplus-platform-admin`；失败原因为 `OMS identity contract is unavailable`。
- 根因：protected K8s deployment 只注入了 OMS redirect/return URL，未注入 `DT_EDUPLUS2_OMS_ENABLED`、OMS discovery/issuer/audience/client/account-status 策略，导致 `enterprise.oms_platform_verifier` 与 `enterprise.oms_account_status` 未装配。
- 修正：新增受保护发布 `oms_identity` registry contract，由 `prepare-metadata` 导出 `DEEPTUTOR_EDUPLUS2_OMS_*`；K8s `backend.yaml` 使用这些 release env 渲染 OMS identity 配置。test-cn registry 固定为 EduPlus2 test Keycloak，`audience=account`，`client_id=eduplus-platform-admin`，`account_status_url=off`，继续执行 token-only 身份状态策略且不向 EduPlus2 请求本产品权限。
- 验证：`woodpecker-cli lint .woodpecker/protected-k8s-release.yml` 仅保留既有 clone allowlist warning；`.venv/bin/python -m pytest extensions/enterprise/tests/test_frontend_gateway.py extensions/enterprise/tests/test_protected_k8s_release_baseline.py extensions/enterprise/tests/test_webhook_release_secret.py extensions/enterprise/tests/test_preflight.py -q` → **50 passed**；`git diff --check` 通过。
- 说明：该切片只补齐 DeepTutor 自有发布配置和 OMS identity verifier 装配，不修改 EduPlus2；重新发布后需再次走真实 OMS 登录，预期 token 验签通过后进入本地 `ops.*` 授权失败关闭态（未登记平台权限时 `/oms/me` 仍应 403）。

### 2026-09-29 OMS 首位平台管理员受控初始化切片

- 背景：test-cn 真实 `eduplus-platform-admin` OMS 登录已能完成 OIDC/BFF 会话，但本产品本地 `ops.*` 默认零权导致正式 OMS 页面 403；为支持首个 Agent 前的平台模型与 Skill 维护，需要 DeepTutor 自有、一次性的首位 OMS 管理员初始化闭环。
- 新增应用层服务 `management.first_admin.bootstrap_first_oms_administrator`：仅消费已验签的 OMS `ManagementIdentity`，要求身份仍处于当前有效窗口；在同一 PG 事务内设置 `app.management_app=oms`，显式锁定 `management.principals/assignments` 串行化零管理员检查，确认没有其他活跃 `platform_security_admin` 后创建/激活当前 `(issuer,sub)` principal，并授予 v2 `platform_security_admin` 与 `platform_config_admin`。业务规则全部在 Python 中执行，不新增 DB 函数、触发器、存储过程或 enum-like CHECK。
- 新增 `POST /api/v1/oms/bootstrap/first-admin`：读取 Bearer 或 httpOnly OMS cookie，复用 OMS 平台 token verifier；Cookie 写请求继续由现有 Origin+CSRF 中间件保护；`DT_EDUPLUS2_OMS_FIRST_ADMIN_BOOTSTRAP_ENABLED` 可关闭该入口。同一主体重复调用幂等返回，第二主体或非零管理员状态返回 409；响应只包含本地 principal/assignment/role/policy version 与 subject hash，不回传 token/Secret。
- 正式 OMS fail-closed 页面在 403 本地授权缺失时显示“激活首位 OMS 管理员”按钮，调用同源 BFF API；成功后重新加载正式 DTO，不回退开发原型，也不借 EduPlus2 权限角色。
- 受保护发布链路新增 `DT_EDUPLUS2_OMS_FIRST_ADMIN_BOOTSTRAP_ENABLED` 注入与示例 registry 字段，保证 test-cn 部署可以显式开/关首位初始化门禁。
- 验证：
  - RED：`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_application.py::test_oms_first_admin_bootstrap_seeds_local_roles_and_closes_after_first_run -q` 初始返回 `/api/v1/oms/bootstrap/first-admin` 404；
  - GREEN：同一测试实现后通过，覆盖缺 CSRF 403、首次初始化 200、`/api/v1/oms/me`/`/me/permissions`/`/provider-settings`/`/skills` 200、同主体幂等 replay、第二主体 409；
  - 相关后端回归：`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_application.py::test_oms_me_uses_verified_platform_identity_and_local_action extensions/enterprise/tests/test_application.py::test_oms_first_admin_bootstrap_seeds_local_roles_and_closes_after_first_run extensions/enterprise/tests/test_application.py::test_oms_permissions_catalog_is_platform_security_admin_only extensions/enterprise/tests/test_application.py::test_oms_skills_list_requires_skill_read_and_redacts_storage extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_backend_manifest_sets_public_oms_oauth_urls extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_release_cli_runs_gate_without_pydantic_dependency extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_example_registry_pipeline_and_k8s_sources_are_contract_driven -q` → **7 passed**；
  - Python 语法/静态：`PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m compileall -q extensions/enterprise/src/deeptutor_enterprise/management/first_admin.py extensions/enterprise/src/deeptutor_enterprise/api/application.py` 通过；`.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/management/first_admin.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py extensions/enterprise/tests/test_protected_k8s_release_baseline.py` → **All checks passed!**；
  - 前端：`npm run typecheck:oms --prefix extensions/enterprise/frontends` 与 `npm run build:oms --prefix extensions/enterprise/frontends` 均通过。
- 限制：该切片只解决零本地 OMS 管理员的 DeepTutor 自有初始化，仍需发布到 test-cn 后用真实 OMS 登录点击初始化并复测正式写 API；真实跨学校负例、TMS Webhook 首管即时开启、学校目录合同和 5.1 开闸证据仍未完成。

### 2026-09-29 OMS BFF CSRF local-ssl 调试与修复切片

- 真实 test-cn rc.62 部署后复测：`https://llm-agent-test.f123.pub/oms` 经 `eduplus-platform-admin` 登录成功进入 `/oms?oms_login=ok`，但点击“激活首位 OMS 管理员”返回 `403 Origin or CSRF rejected`。
- 按用户要求改为本地优先调试：使用 `local-ssl` 已有 `https://deeptutor.lfun.pub` 路由，启动当前代码的企业后端、OMS production frontend 与 runtime gateway，配置同 test-cn 的 OMS issuer/audience/client/token-only 状态策略，在本机空白 PostgreSQL 库 `deeptutor_oms_debug_20260929` 上应用迁移并 bootstrap 固定租户。
- 根因：BFF 登录成功时后端把 `dt_oms_csrf` 设置为 `Path=/api/v1/oms`；浏览器会把该 cookie 发给 API，但 `/oms` 前端页面无法通过 `document.cookie` 读取它，因此写请求未携带 `x-csrf-token`，被中间件拒绝。token/refresh cookie 的 `Path=/api/v1/oms` 与 `HttpOnly` 是正确的，只有 CSRF cookie 需要前端可读。
- 修复：新增前端可读的 OMS CSRF cookie path `/`，继续保持 token/refresh 为 `HttpOnly Path=/api/v1/oms`；登录/refresh 时同时清理旧 `Path=/api/v1/oms` 的同名 CSRF cookie，logout/失败清理两个路径，避免旧 cookie 干扰。
- 本地 local-ssl 验证：`/api/v1/oms/auth/callback` 返回 200，`/api/v1/oms/me` 在未授权时 403；点击“激活首位 OMS 管理员”后 `/api/v1/oms/bootstrap/first-admin` 返回 200，随后 `/api/v1/oms/me`、`/api/v1/oms/me/permissions`、`/api/v1/oms/skills`、`/api/v1/oms/provider-settings` 等正式 DTO 返回 200，页面进入正式 OMS 管理入口。
- 自动验证：新增 `test_frontend_callback_sets_frontend_readable_oms_csrf_cookie`，先 RED 失败于 CSRF cookie 未设置 `Path=/`，修复后 GREEN；`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_oms_oauth_flow.py -q` → **5 passed**，并联动首管相关后端测试通过。

### 2026-09-29 正式 OMS/TMS 原型结构迁入切片

- 背景：用户指出正式 OMS/TMS 页面未按已批准原型组织。按“原型作为前端完全搬过来，再逐项替换为正式 DTO/API”的方向，在不修改 EduPlus2、不走流水线的前提下，将正式入口的导航、深链、列表到详情抽屉、安全空态和受控操作区补齐到原型一致的交互骨架。
- OMS：正式 `/oms` 保留“智能体基座 / 平台智能体运营后台”壳与原型侧边导航；学校、资源、模型/Provider、供给、用量、审计、Skill 列表均可打开详情抽屉。详情只读取既有安全 DTO，缺失字段显示“未返回/未启用/失败关闭”，明确 OMS 不管理学校账号或 TMS `tenant.*`，不回退 prototype fixture。
- TMS：正式 `/tms/{schoolCode}` 保留“学校智能体管理后台”原型导航与当前学校固定上下文；成员、服务访问、配额、用量、Skill、审计均有详情抽屉。应用、知识库等尚无正式 DTO 的原型页面改为安全空态，明确不会使用合成应用、知识库、成员或私有正文兜底。
- 测试：先在 `formal-management-gates.test.tsx` 新增 OMS 学校列表详情抽屉、TMS 成员详情/知识库未启用状态、OMS/TMS 审计深链三个红灯用例，初始分别失败于无 `查看 ... 详情`、无 `成员资料` 操作、审计深链空白；实现后对应定向用例均通过。另补全量导航骨架回归，覆盖 OMS/TMS 每个原型导航入口均有正式安全内容区。
- 回归验证：`npm test --prefix extensions/enterprise/frontends -- formal-management-gates.test.tsx` → **26 passed**；`npm test --prefix extensions/enterprise/frontends` → **27 files / 278 tests passed**；`npm run typecheck:oms --prefix extensions/enterprise/frontends`、`npm run typecheck:tms --prefix extensions/enterprise/frontends`、`npm run build:oms --prefix extensions/enterprise/frontends`、`npm run build:tms --prefix extensions/enterprise/frontends` 均通过；`.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/management/approvals.py` 通过；`openspec validate add-enterprise-management-authorization --strict` 通过。
- 限制：该切片只完成正式前端原型骨架和本地安全 DTO 交互，不新增真实平台目录候选、不完成真实双学校登录/跨校负例、不触发 Woodpecker、不开放 5.1。

### 2026-09-29 TMS 学校码篡改前端失败关闭补强

- TDD：新增 `formal-management-gates.test.tsx` 用例“`TMS 正式入口拒绝 URL 学校码与安全 DTO 学校不一致`”，先 RED 失败于页面继续进入正式壳且未显示不一致原因。
- 修复：`TmsFormalApp` 在读取 `/api/v1/tms/me/permissions` 后，如果后端安全 DTO 返回规范 `school_code` 且与当前 `/tms/{schoolCode}` 不一致，立即以 403 失败关闭；不再继续读取 `school-bootstrap/status`、`directory/users`、`members`、`approvals`、`authz-audit`、`skills` 等当前学校数据，也不显示授予、撤销、审批或新增按钮。`school_id` 仍按内部稳定学校 ID 处理，不误当 URL code。
- 验证：RED 后 GREEN `npm test --prefix extensions/enterprise/frontends -- formal-management-gates.test.tsx -t "TMS 正式入口拒绝 URL 学校码"` → **1 passed / 26 skipped**；完整文件回归 `npm test --prefix extensions/enterprise/frontends -- formal-management-gates.test.tsx` → **27 passed**。
- 本轮完整相关验证：`npm test --prefix extensions/enterprise/frontends` → **27 files / 279 tests passed**；`npm run typecheck:oms --prefix extensions/enterprise/frontends`、`npm run typecheck:tms --prefix extensions/enterprise/frontends`、`npm run build:oms --prefix extensions/enterprise/frontends`、`npm run build:tms --prefix extensions/enterprise/frontends` 均通过；`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_management_approvals.py extensions/enterprise/tests/test_oms_management_entrypoints.py extensions/enterprise/tests/test_oms_oauth_flow.py -q` → **18 passed**；`.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/management/approvals.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/src/deeptutor_enterprise/management/first_admin.py` → **All checks passed**；`openspec validate --all --strict` → **30 passed、0 failed**；`git diff --check` 通过。
- 限制：该补强是合成 DTO 的前端失败关闭负例；真实双学校 token/client/绑定与 test-cn 浏览器验收仍未闭合，4.3/5.1 父任务保持未完成。

### 2026-09-29 test-cn 真实登录只读探测限制

- test-cn 当前部署只读状态：`kubectl-env test get pods,deploy,svc -n deeptutor-test-cn` 显示 `deploy/test-cn/v1.4.0-rc.63` 迁移已完成，`deeptutor-backend` 与 `deeptutor-docs` Pod Ready；未执行任何 kubectl 写操作。
- OIDC 自动化探测：对 `eduplus-platform-admin` 尝试 Resource Owner Password Grant，Keycloak 返回 `unauthorized_client / Client not allowed for direct access grants`，符合该 OMS client 只能走授权码登录的预期。随后尝试用 HTTP session 提交授权码登录表单，未返回 `code`；未取得 token，未调用写 API，未输出任何密码、token 或完整上游响应。
- 结论：真实 test-cn 登录、首位 OMS 管理员点击初始化、TMS Webhook 首管即时开启、双学校浏览器/账号验收仍需要可交互浏览器会话或外部人员配合；本轮不以脚本失败或合成 JWT 计作验收通过。

### 2026-09-29 test-cn PostgreSQL 本地隔离快照与 TMS `school_code` DTO 补强

- 按用户授权从 test-cn Kubernetes Secret 只读取 `DEEPTUTOR_POSTGRES_MIGRATION_DATABASE_URL`，未打印数据库密码、token、真实用户、学校名称或完整上游响应；远端 `pg_dump` 因 RLS 对 `eduplus2.lifecycle_actor_candidates` 失败关闭后，改为 `pre-data/post-data schema dump + 按 RLS 上下文只读复制可见行`，不修改 test-cn 数据库。
- 本地导入到隔离库 `deeptutor_testcn_snapshot_20260929073821`，schema dump 保存在 `.secrets/test-cn-db-snapshots/`。导入摘要：`remote_school_binding_rows=3`，复制 16 张表、238 行；关键脱敏只读核验显示 `eduplus2.webhook_school_state` 3 行、3 个 distinct `school_id`、3 个非空 `school_code`、3 条 onboarding event 记录，`oms.school_bindings` 3 行，`eduplus2.lifecycle_actor_candidates` 0 行，`enterprise.users` 1 行。仅记录 hash/计数，不输出 PII。
- 快照结论：可采信 test-cn 当前真实学校绑定/学校码投影/外部 ID 类型形态；不能采信为真实 `subscription.created.actor.user_id` 与 OIDC `sub` 匹配、TMS Webhook 首管即时开启、漂移/解绑、双学校浏览器登录或跨学校 403 证据，因为 actor candidate 表为空且未取得真实 TMS 用户 token。
- 后端 TDD：先修改 `test_tms_me_permissions_returns_local_tenant_action_summary`，要求 `/api/v1/tms/me/permissions` 返回可信 `school_code=synthetic-school`；RED 失败于响应缺少该字段。
- 修复：`tms_permission_summary()` 在当前学校事务内读取 `eduplus2.webhook_school_state.school_code`，优先匹配 `ManagementIdentity.webhook_app_id`，并随 TMS 权限摘要返回 `school_code`。该字段来自已验签 Webhook 学校投影，不来自 URL、header 或 request body，供正式 `/tms/{schoolCode}` 前端做一致性失败关闭。
- 验证：`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_webhook_authority.py::test_tms_me_permissions_returns_local_tenant_action_summary -q` → RED 后 GREEN，最终 **1 passed**；后续回归 `PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_webhook_authority.py -q` → **41 passed**，`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_management_approvals.py extensions/enterprise/tests/test_oms_management_entrypoints.py extensions/enterprise/tests/test_oms_oauth_flow.py extensions/enterprise/tests/test_webhook_authority.py -q` → **59 passed**；`npm test --prefix extensions/enterprise/frontends` → **27 files / 279 tests passed**；`npm run typecheck:oms --prefix extensions/enterprise/frontends`、`npm run typecheck:tms --prefix extensions/enterprise/frontends`、`npm run build:oms --prefix extensions/enterprise/frontends`、`npm run build:tms --prefix extensions/enterprise/frontends` 均通过；`.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/management/authorization.py extensions/enterprise/src/deeptutor_enterprise/management/approvals.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/src/deeptutor_enterprise/management/first_admin.py extensions/enterprise/tests/test_webhook_authority.py` → **All checks passed**；`openspec validate add-enterprise-management-authorization --strict` 与 `openspec validate --all --strict` 均通过，`git diff --check` 通过。
- 限制：此切片不新增 DB/OpenFGA/Keycloak migration；本地快照是临时验证数据，不是正式数据迁移。真实跨学校负例、真实 TMS 授权码/首管 actor-sub 合同、学校目录策略合同和 5.1 开闸仍未完成。

### 2026-09-29 TMS 缺失可信学校码失败关闭补强

- TDD：新增 `formal-management-gates.test.tsx` 用例“`TMS 正式入口拒绝缺失可信学校码的权限摘要`”，先 RED 失败于页面进入正式 TMS 壳并继续加载当前学校 DTO。
- 修复：`TmsFormalApp` 将 `/api/v1/tms/me/permissions` 中缺失 `school_code` 也视为 403 失败关闭，错误说明为“后端权限摘要未返回可信学校码”；只有后端返回非空且与 `/tms/{schoolCode}` 完全一致时，才继续读取 `school-bootstrap/status`、目录、成员、审批、审计、Skill、额度或服务访问 DTO。
- 验证：`npm test --prefix extensions/enterprise/frontends -- formal-management-gates.test.tsx -t "缺失可信学校码"` → RED 后 GREEN，最终 **1 passed / 27 skipped**；`npm test --prefix extensions/enterprise/frontends -- formal-management-gates.test.tsx` → **28 passed**；`npm test --prefix extensions/enterprise/frontends` → **27 files / 280 tests passed**；`npm run typecheck:tms --prefix extensions/enterprise/frontends`、`npm run build:tms --prefix extensions/enterprise/frontends`、`npm run typecheck:oms --prefix extensions/enterprise/frontends`、`npm run build:oms --prefix extensions/enterprise/frontends` 均通过。
- 限制：这是前端安全 DTO 合同的防 fail-open 补强；真实双学校 token/client 负例仍需要 test-cn 浏览器/授权码证据。

### 2026-09-29 TMS 权限摘要后端学校码缺失失败关闭补强

- TDD：新增 `test_tms_me_permissions_fails_closed_when_trusted_school_code_missing`，在已验签 Webhook 学校投影被清空 `school_code` 的场景下调用 `/api/v1/tms/me/permissions`；先 RED 失败于 API 返回 200 且 `school_code=""`。
- 修复：`tms_permission_summary()` 在当前学校事务中必须读到非空 `eduplus2.webhook_school_state.school_code`；若投影缺失或学校码为空，直接抛出 `ManagementAuthorizationDenied`，由 API 返回 403。这样后端 API 与正式前端都 fail closed，不把 URL 学校码或空 DTO 当作可信学校身份。
- 验证：`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_webhook_authority.py::test_tms_me_permissions_fails_closed_when_trusted_school_code_missing extensions/enterprise/tests/test_webhook_authority.py::test_tms_me_permissions_returns_local_tenant_action_summary -q` → RED 后 GREEN，最终 **2 passed**；`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_webhook_authority.py -q` → **42 passed**；跨切片回归 `PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_management_approvals.py extensions/enterprise/tests/test_oms_management_entrypoints.py extensions/enterprise/tests/test_oms_oauth_flow.py extensions/enterprise/tests/test_webhook_authority.py -q` → **60 passed**；`npm test --prefix extensions/enterprise/frontends -- formal-management-gates.test.tsx` → **28 passed**；`.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/management/authorization.py extensions/enterprise/tests/test_webhook_authority.py` → **All checks passed**；`openspec validate add-enterprise-management-authorization --strict` 与 `openspec validate --all --strict` 均通过；`git diff --check` 通过。
- 限制：该补强仍属于合成 Webhook/PG 负例；真实双学校 token/client/浏览器负例仍需 test-cn 授权码会话。

### 2026-09-29 test-cn 单执行者 / 非 HA 门禁确认

- 只读检查 test-cn `deeptutor-backend` Deployment：`replicas=1`、`DEEPTUTOR_EXECUTION_MODE=single`、`DEEPTUTOR_TURN_COORDINATION_BACKEND=memory`、release `test-cn-v1-4-0-rc-63`。
- 结论：当前未启用多执行者，也不把静态 UI 或单 Pod 验收声称为 HA/容灾；因此 G/H 跨实例撤权、会话、缓存和审批并发一致性验证保持为“未来启用多执行者前的门禁”，不作为当前单实例开闸证据。
- 该检查为 Kubernetes 只读操作，未修改 test-cn 集群或发布状态。

### 2026-09-29 OMS school 范围不能冒充 platform Provider 权限补充覆盖

- 补充后端合成 PG 回归：构造已验签 OMS 身份、本地 active principal，以及仅具备 `school` 范围 `platform_operator` assignment 的平台运营主体；该主体有学校绑定与可用学校状态，但没有任何 `platform` 范围 grant。
- 验证全局 Provider 入口仍按 `platform` 范围失败关闭：`GET /api/v1/oms/provider-settings` 和 `POST /api/v1/oms/provider-settings/draft` 均返回 403 / `Permission denied`，不读取或写入全局 Provider 设置，也不把学校范围 `ops.oms.access`、学校运营 assignment 或 URL/API 上下文提升为 `ops.providers.*` 平台权限。
- 同步企业管理路由 allowlist 测试，把此前已实现并记录的 `/api/v1/oms/bootstrap/first-admin` 受控初始化路由纳入正式 OMS 路由清单，避免安全路由收敛测试误报；未新增生产路由。
- 验证：`PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_application.py::test_oms_school_scoped_operator_cannot_read_platform_provider_settings -q` → **1 passed**；跨切片后端回归 `PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_application.py extensions/enterprise/tests/test_webhook_authority.py extensions/enterprise/tests/test_management_approvals.py extensions/enterprise/tests/test_oms_management_entrypoints.py extensions/enterprise/tests/test_oms_oauth_flow.py -q` → **114 passed / 1 skipped**。该新增测试最初失败于我新增夹具误用了不存在的 `enterprise.tenants.name/status` 列，修正为现有企业租户与 `oms.school_bindings` 事实后通过；未改生产代码。
- 前端与静态验证：`npm test --prefix extensions/enterprise/frontends` → **27 files / 280 tests passed**；`npm run typecheck:oms --prefix extensions/enterprise/frontends`、`npm run build:oms --prefix extensions/enterprise/frontends`、`npm run typecheck:tms --prefix extensions/enterprise/frontends`、`npm run build:tms --prefix extensions/enterprise/frontends` 均通过；`.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/management/approvals.py extensions/enterprise/src/deeptutor_enterprise/management/authorization.py extensions/enterprise/tests/test_application.py extensions/enterprise/tests/test_webhook_authority.py` → **All checks passed!**；`openspec validate add-enterprise-management-authorization --strict` 与 `openspec validate --all --strict` 均通过；`git diff --check` 通过。
- 限制：这是本地合成授权负例补充覆盖，不等同真实双学校浏览器/账号负例；4.3/5.1 中真实跨学校、真实账号和 test-cn 开闸证据仍保持未完成。

### 2026-09-29 正式 OMS 旧学校开通深链服务端失效补强

- TDD：在 `school-routing.test.tsx` 新增“OMS 正式入口同样拒绝旧学校后台开通深链”，要求正式 catch-all 对 `/oms/tms-bootstrap` 与 `/oms/tms-bootstrap-requests` 直接 `notFound()`。初始 RED 失败于当前 `app/[...slug]/page.tsx` 同步返回 `<OmsFormalApp />`，未拒绝旧深链。
- 修复：正式 OMS catch-all 改为读取 `params.slug`，对已撤销的学校后台开通深链 `tms-bootstrap`、`tms-bootstrap-requests` 服务端 `notFound()`；其它正式 OMS 路由继续进入 `OmsFormalApp`。这只影响 DeepTutor 自有前端路由，不新增任何授权事实，不修改 EduPlus2、Keycloak 或 OpenFGA。
- 验证：`npm test --prefix extensions/enterprise/frontends -- school-routing.test.tsx -t "OMS 正式入口同样拒绝旧学校后台开通深链"` → RED 后 GREEN，最终 **1 passed / 10 skipped**；完整相关文件 `npm test --prefix extensions/enterprise/frontends -- school-routing.test.tsx` → **11 passed**。
- 限制：该切片闭合旧 OMS 学校开通深链的本地服务端 404；真实平台目录候选、真实账号按钮级验收和 5.1 开闸仍需外部环境证据。

### 2026-09-29 首位 TMS 学校管理员改为订阅 Webhook 即时开启

- 需求裁决：用户再次明确“学校管理员无需单独开通，接收到 webhook 订阅立即开启”。因此本 change 的首位 TMS 管理员规则从“真实 `subscription.created.actor.user_id` 登记后本人二次激活”修订为“真实、已验签、非 mock 的 `subscription.created.actor.user_id` 在 Webhook 接收事务内直接创建/激活唯一 `school_admin` assignment”。OMS 仍不得列出、创建、审批或维护学校账号。
- 后端实现：`webhook_authority.ingest_authoritative_webhook()` 在同一事务内校验真实 `subscription.created`、学校绑定、actor、issuer 与一次性栅栏；满足条件时写入/激活 TMS principal、授予 `school_admin`、推进目标 policy version、写入 consumed actor 记录和审计。`/api/v1/tms/school-bootstrap/status` 在已即时开启后返回 active；历史 `/activate` 对同一已激活主体仅幂等回放，不再作为开通前置。
- 失败关闭：mock、缺 actor、system/null、错校、重复/恢复/重订不会产生新的可用管理员；AI 资源 pending 不阻挡学校管理引导，但不开放 AI 新调用。真实 actor 与后续 OIDC `sub` 等值/映射仍需 test-cn 脱敏证据，不能以 mock 或合成 JWT 计作 5.1 正式开闸。
- 前端/原型：TMS 原型 copy 已从“学校后台待开通/待本人登录匹配”改为“等待订阅 Webhook/学校管理员无需单独开通”；模拟按钮文案为“模拟接收订阅 Webhook”，缺 actor 展示“无可开启身份”。OMS 正式旧学校开通深链继续 404。
- 迁移判断：本切片不新增 DB schema、OpenFGA 或 Keycloak 迁移；复用既有管理授权事实表和历史 actor 记录表，业务代码只改变未来 Webhook 写入语义。
- 限制：此证据闭合本地实现语义，不闭合 test-cn 真实 `subscription.created.actor.user_id` 与 OIDC `sub` 合同、真实双学校登录负例、学校目录策略或 5.1 开闸。

- 验证补充：当前沙箱禁止 `initdb` 使用 SysV shared memory，按 local-debug 规则改用显式 `DT_TEST_PG_DSN=host=localhost port=5432 user=postgres dbname=postgres` 的本地 PostgreSQL；同时为 `tests/fixtures/postgres.py` 增加只接受 loopback/postgres 管理库的安全入口，避免连接远端或业务库。`PYTHONPATH=. .venv/bin/pytest tests/test_postgres_fixture.py -q` → **3 passed**；`DT_TEST_PG_DSN=... PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests/test_webhook_authority.py -q` → **42 passed**；`DT_TEST_PG_DSN=... PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest extensions/enterprise/tests -q` → **800 passed / 3 skipped / 2 warnings**；`.venv/bin/ruff check ...` → **All checks passed**；前端 `npm test --prefix extensions/enterprise/frontends` → **27 files / 281 tests passed**，`typecheck:oms`、`typecheck:tms`、`build:oms`、`build:tms` 均通过；`openspec validate add-enterprise-management-authorization --strict` 与 `openspec validate --all --strict` 均通过，`git diff --check` 通过。
- 勾选判断：本地实现与合成验证已闭合任务 **3.3**；真实 `subscription.created.actor.user_id` 与 OIDC `sub` 合同、真实错校/重放/恢复/撤销联调和 5.1 开闸仍保留在 **3.3.3 / 5.1**，不得用本地合成测试替代。

### 2026-09-29 test-cn rc.64 完整测试与问题修复记录

- 部署状态：确认 `HEAD=bcc2d4da` 对应 `deploy/test-cn/v1.4.0-rc.64` 已部署到 `deeptutor-test-cn`；`deeptutor-backend` 与 `deeptutor-docs` 均 `Ready 1/1`，rollout 成功。迁移 Job `dt-migrate-test-cn-v1-4-0-rc-64` 完成，日志显示 schema `apply/verify` 成功且 pending 为空。近期 Kubernetes 事件仅有发布启动期 readiness connection refused，稳定后 Pod Ready；后端日志尾部无 error/traceback/500。
- test-cn HTTP/浏览器黑盒：`/health/live`、`/health/ready` 均 200；`/docs/` 200。未认证 OMS/TMS 管理 API 读接口均返回 401；使用伪造 Bearer 仍返回 401。按完整合法 JSON 请求体重测 TMS 写接口（自定义角色、成员授予、撤权、审批创建/复核/撤回/apply）未认证与伪造 Bearer 均 401；不会因 Pydantic 请求体有效而越过认证。旧 OMS 学校开通深链 `/oms/tms-bootstrap`、`/oms/tms-bootstrap-requests` 均 404。Playwright 截图确认正式 `/oms` 与 `/tms/demo-school` 均显示“正式受控入口/未开放” fail-closed，不回退开发原型或写按钮。
- OMS 授权码入口：点击 `/oms` 的 `eduplus-platform-admin` 登录按钮可跳转到 `https://eduplus-auth-test.f123.pub/realms/eduplus/.../auth`，`client_id=eduplus-platform-admin`、回调为 `https://llm-agent-test.f123.pub/oms/auth/callback`，Keycloak 登录页 200。使用本地 `.secrets/.login-credentials` 中已记录的 admin/teacher 凭据进行一次自动化尝试均被上游返回“用户名或密码错误”；未取得 code/token，未调用任何写 API，未输出密码/token。故本轮仍不能把真实 OMS 登录、账号状态或平台主体本地授权记为验收通过。
- test-cn 数据库只读核验：在 Pod 内使用迁移 DSN 只读查询，不打印 DSN/密码/PII。`enterprise.tenants=4`、`oms.school_bindings=3` 且三条绑定为 `verified`；`eduplus2.webhook_school_state=0`、`eduplus2.lifecycle_actor_candidates=0`、`management.principals=0`、`management.assignments=0`、`management.audit_events=0`。按 RLS 上下文设置 `app.management_app=oms/tms` 后可见本地 action/role 模板：OMS active actions 24、role actions 40，TMS active actions 9、role actions 18。结论：rc.64 已具备权限目录/模板和学校绑定底座，但当前 test-cn 未保留可验收的真实 `subscription.created.actor.user_id`、TMS 首管 principal/assignment 或管理审计事实，不能闭合 3.3.3/5.1。
- 本轮发现并修复的问题：
  - `ruff check extensions/enterprise/src extensions/enterprise/tests` 发现 `extensions/enterprise/tests/test_frontend_gateway.py` import 顺序不符合 isort，已仅重排 import。
  - `npm run lint --prefix extensions/enterprise/frontends` 发现 `OmsFormalApp` 在 effect 内同步 `setLoginHref` 触发 `react-hooks/set-state-in-effect`，并发现 `TmsFormalApp` 数据加载 effect 缺少 `schoolCode` 依赖；已改为点击时计算 OMS 登录 URL，并让 TMS effect 随 `schoolCode` 变化重新 loading/load。
- 本地回归：修复后 `npm test --prefix extensions/enterprise/frontends -- --run` → **27 files / 281 tests passed**；`npm run typecheck:oms`、`npm run typecheck:tms`、`npm run lint` 均通过。企业后端全量 `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short` → **800 passed / 3 skipped / 2 warnings**；Core/WS 兼容定向 → **41 passed / 4 warnings**。`ruff check extensions/enterprise/src extensions/enterprise/tests` 通过；`openspec validate --all --strict` → **30 passed / 0 failed**；`git diff --check` 通过。
- 质量风险记录：`ruff format --check extensions/enterprise/src extensions/enterprise/tests` 在当前工具版本下会要求重排约 58 个既有文件，范围远超本轮变更且未见 Woodpecker test-cn 发布流程执行该全量 format check；本轮未盲目格式化历史文件，避免引入大面积无关 diff。若后续决定把全量 Ruff formatter 纳入硬门禁，应单独做一次纯格式化变更并独立验证。
- 未完成门禁：真实 `eduplus-platform-admin` 授权码登录 + active 账号状态、真实 `subscription.created.actor.user_id` 与后续 OIDC `sub` 合同、真实 TMS 双学校正负例、目录策略合同、审批竞态真实环境与 5.1 开闸仍未闭合；本轮不勾选这些任务。
