# OMS v1 实施证据

## 2026-09-30 收敛建档

- 已按用户指令建立 `deliver-oms-test-cn-management-v1` 作为新的 OMS 执行主线。
- 已 archive 完成 proposal：
  - `2026-09-30-add-b2-eduplus2-tenant-lifecycle-webhook`
  - `2026-09-30-relocate-database-business-rules-to-application`
  - `2026-09-30-add-ws-required-context-controls`
  - `2026-09-30-add-third-party-capacity-development-guides`
- 当前本地 `local-ssl` 链路恢复证据：
  - `https://deeptutor.lfun.pub/oms` 返回 307 到 OMS auth start，不再 502。
  - `https://deeptutor.lfun.pub/api/v1/oms/auth/start?...` 返回 303 到 EduPlus2 Auth。
  - `https://deeptutor.lfun.pub/oms/_next/static/chunks/0.qfcr9oeii_b.js` 返回 404。
  - 有效 chunk `0k~u_jyibvj9b.js` 返回 200 `application/javascript`。

## 待补证据

- 旧未完成 proposal 已冻结/替代标记：8 个 OMS 相关 proposal 转为 `deliver-oms-test-cn-management-v1` 证据来源，5 个非当前 OMS 主线 proposal 暂停。
- OpenSpec strict validation 已通过：`openspec validate deliver-oms-test-cn-management-v1 --strict`；`openspec validate --all --strict` 显示 31 passed, 0 failed。
- 本地 admin 浏览器验收。
- test-cn 部署后 admin-only 验收。

## 2026-09-30 模型与服务 / 供应商连接补强

- OMS 正式入口的“模型与服务”“供应商连接”已从临时“模型与 Provider”合并区块收敛回原型骨架：
  - `模型与服务` 页面使用原型 PageHead 文案“按基座服务语义管理平台目录；配置与实际生效分离。”，保留“全部服务 / 文档识别与解析”Tab、`搜索服务`、以及“服务概况 / 服务配置 / Provider 配置 / 模型清单 / 关联记录 / 发布记录”行级入口。
  - 服务详情继续以抽屉承载；`服务配置` 中保留正式模型草稿与 Provider 草稿 test/publish/rollback 写入口，写入仍走正式 OMS API、版本号和原因。
  - `供应商连接` 页面使用原型 PageHead 文案“连接与服务配置分层维护；凭据由高权限角色处理。”，保留 `搜索连接`、列“连接 / 适用服务 / 凭据状态 / 状态”和“连接资料”入口。
- 模型草稿读取展示后端 DTO 返回的草稿版本和状态，并在服务、Provider Profile、模型清单/详情中使用 status catalog 展示语义化状态与来源字段；服务目录只由正式 DTO 派生，不回退原型 fixture。
- Provider 设置读取展示设置版本和状态，供应商连接列表/详情一律以 `<redacted>` 展示凭据；前端状态和表格搜索均不保留/匹配 `env:*`、`sk-*` 或其它 `api_key` 原文。
- 逐连接“配置凭据/轮换凭据”原型入口仅在有 `ops.providers.manage` 时展示为禁用，并提示“逐连接凭据配置 API 尚未纳入 OMS v1”，避免用假表单替代受控 Secret 写入。
- 新增/更新回归测试：`OMS 正式入口只读展示模型与服务目录和供应商连接且不泄露 Secret`、`OMS 模型与服务和供应商连接保留原型交互骨架且始终脱敏凭据引用`、`OMS 正式入口在 manage 权限下接入模型与 Provider 写入 API 并回读审计`。
- 已通过验证：
  - `npm test -- tests/formal-management-gates.test.tsx`（46 passed）
  - `npm test -- tests/formal-management-gates.test.tsx -t "模型与服务和供应商连接|模型草稿和 Provider|manage 权限下接入模型"`
  - `npm run typecheck:oms`
  - `npm run build:oms`
  - `npm run lint`
  - `git diff --check -- extensions/enterprise/frontends/apps/oms/src/OmsFormalApp.tsx extensions/enterprise/frontends/tests/formal-management-gates.test.tsx openspec/changes/deliver-oms-test-cn-management-v1/implementation-evidence.md`
  - `openspec validate deliver-oms-test-cn-management-v1 --strict`
  - `openspec validate --all --strict`（31 passed, 0 failed）

## 2026-09-30 学校列表回归加固

- 后端修复：OMS 平台身份没有 school app id 时，学校范围授权复核改为只在 `application=oms` 下使用已验签 Webhook 学校投影、`oms.school_bindings` 版本和本地 `eduplus2.webhook_school_controls` 冻结状态复核；TMS 学校身份仍要求自身可信 app id。学校列表/详情 DTO 增加可信 `school_code` 展示字段，并继续以 `school_id` 作为稳定对象 ID 和授权目标。
- 前端修复：OMS 学校列表优先展示可信学校代码，详情抽屉同时展示“学校代码”和“学校 ID”；路由和 API 仍使用稳定 `school_id`，不新增学校账号开通入口。
- TDD/回归验证：
  - RED：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_school_list_uses_signed_school_projection_without_platform_app_claim --tb=short` 初始失败，`school_actions` 为空。
  - GREEN：同一后端测试通过；该用例覆盖自定义 `school_list_reader` 学校范围授权、默认 `platform_operator` 学校范围授权，以及未授权隐藏学校详情 403。
  - GREEN：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_school_list_uses_signed_school_projection_without_platform_app_claim extensions/enterprise/tests/test_application.py::test_oms_governance_read_api_filters_by_local_school_grants_and_descriptors --tb=short` → 2 passed。
  - RED/GREEN：`npm test -- formal-management-gates.test.tsx -t "OMS 学校列表优先展示可信学校代码且详情保留学校 ID"` 初始失败找不到 `jygjzx`，修复后通过。
  - GREEN：`npm test -- formal-management-gates.test.tsx -t "OMS (正式入口按原型导航切换到学校范围页|学校列表优先展示可信学校代码且详情保留学校 ID|正式入口无 Skill 权限时不读取 Skill DTO 且学校列表仍可用)"` → 3 passed。
  - GREEN：`npm test -- formal-management-gates.test.tsx` → 46 passed。
  - GREEN：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_management_authorization.py --tb=short` → 32 passed。
  - GREEN：`npm run typecheck:oms` → `tsc --noEmit` 通过。
  - GREEN：`openspec validate deliver-oms-test-cn-management-v1 --strict` → valid。
  - GREEN：`openspec validate --all --strict` → 31 passed, 0 failed。
  - GREEN：`git diff --check -- <本次相关文件>` → 无输出。

## 2026-09-30 本地 OMS 学校列表数据联调

- Root cause：本地 `deeptutor_local` 里 `oms.school_bindings`、`eduplus2.webhook_school_state`、`eduplus2.webhook_school_controls` 均为 0，当前 OMS 登录主体只有 platform-scope 授权，没有 `ops.tenants.read` school-scope assignment，因此学校列表返回空。
- test-cn 数据源核对：只读连接 test-cn PostgreSQL，`enterprise.tenants=8`、`oms.school_bindings=7`；test-cn 当前没有 `management.principals/assignments`，也没有新版 Webhook 投影/controls 行。
- 本地导入：已先备份本地库到 `.secrets/test-cn-db-snapshots/local-before-oms-schools-20260930103910.dump`，再把 test-cn 的 8 条学校 tenant 和 7 条已验证学校绑定 upsert 到本地。
- 本地补齐（仅 local unblock）：由于 test-cn 缺少当前代码要求的 Webhook 投影/冻结控制行，按已验证 binding 派生 7 条本地 `eduplus2.webhook_school_state` 与 `eduplus2.webhook_school_controls`；同时给当前本地 OMS 主体授予 7 条 `platform_operator` school-scope assignment（`ops.tenants.read`），未写回 test-cn，未复制学校账号、token、secret、Keycloak 或 OpenFGA 状态。
- 数据校验：
  - `enterprise.tenants=12`（保留原本地 4 条 + test-cn 8 条）
  - `oms.school_bindings=7`
  - `eduplus2.webhook_school_state=7`
  - `eduplus2.webhook_school_controls=7`
  - `management.assignments` 中本地 OMS school-scope active assignment 为 7 条
  - 授权可见学校候选数为 7。

## 2026-09-30 本地 OMS 权限摘要 503 修复

- Root cause：浏览器页面刷新后 `/api/v1/oms/me` 为 200，但 `/api/v1/oms/me/permissions` 为 503；本地复现为应用账号 `dt_enterprise_app` 对 `eduplus2.webhook_school_state` 缺少 `SELECT`，school-scope 权限摘要在 PEP 复核 Webhook 学校投影时触发 `permission denied for table webhook_school_state`。
- 本地临时 unblock：在 `deeptutor_local` 执行 `GRANT SELECT ON TABLE eduplus2.webhook_school_state TO dt_enterprise_app` 与 `GRANT SELECT ON TABLE eduplus2.webhook_school_controls TO dt_enterprise_app`。未改变 schema、未写 test-cn、未改 Keycloak/OpenFGA。
- 验证：
  - 以 `dt_enterprise_app` 设置 `app.tenant_id` / `app.management_app` 后可读取本校 `webhook_school_state=1`、`webhook_school_controls=1`。
  - 用后端同一配置和当前本地 OMS principal 直接调用 `oms_permission_summary()` 与 `list_tenants_for_oms()`：`platform_actions=9`、`school_actions=7`、`tenant_list.count=7`。

## 2026-09-30 本地 OMS 前端静态资源 500 修复

- Root cause：`https://deeptutor.lfun.pub/oms/_next/static/chunks/*.js` 直接返回 500，且直连 `127.0.0.1:4310` 同样 500，排除 nginx 与 4309 本地同源代理；4310 实际运行的是 `apps/oms/.next/standalone/apps/oms/server.js`，而 `output: "standalone"` 未自动携带 `.next/static`，standalone 工作目录下缺少 `.next/static`。
- 本地临时 unblock：把 `extensions/enterprise/frontends/apps/oms/.next/static` 复制到 `extensions/enterprise/frontends/apps/oms/.next/standalone/apps/oms/.next/static`，并重启 4310 OMS standalone server。后端 8001 与 4309 同源代理未重启。
- 验证：
  - `https://deeptutor.lfun.pub/oms/_next/static/chunks/0-exs640rxdyp.js` → 200 `application/javascript`
  - `https://deeptutor.lfun.pub/oms/_next/static/chunks/14gtaug5juexn.js` → 200 `application/javascript`
  - `https://deeptutor.lfun.pub/oms/_next/static/lyArxpKWcpGUEqNZzEZ3l/_buildManifest.js` → 200 `application/javascript`
  - 批量检查当前 `.next/static` 下 18 个文件经 HTTPS `/oms/_next/static/...` 访问全部 200。

## 2026-09-30 本地 OMS school-scope 供给权限预取 403 修复

- Root cause：当前本地 OMS 主体只有学校范围 `platform_operator` assignment；`/api/v1/oms/me/permissions` 正确返回 `school_actions[].actions` 中的 `ops.supply.read/manage`，但前端把 school-scope actions 扁平化后当作全局 API 权限，启动时预取 `GET /api/v1/oms/supply`。该接口是未定向全局供给总览，仍需 platform/global `ops.supply.read`，因此后端返回 403；前端把该 403 渲染成“未获得 DeepTutor Enterprise 本地 ops.* 授权”，实际并非 `/me` 或学校列表授权失败。
- 修复：OMS 前端新增 platform action 视图；全局/平台 API（权限治理、Skill 全局列表、Provider/模型配置、资源状态、全局供给、全局审计、成本）只按 `actions + platform_actions` 预取或显示写按钮；学校目标 API（学校列表、学校用量/任务、学校 quota/entitlement、学校范围 Skill grant）继续按合并后的 school-scope actions 控制。若只有 school-scope 审计读权限，前端改为带 `school_id` 读取审计。
- 后端边界确认：`GET /api/v1/oms/supply` 未放宽给 school-scope；学校范围主体仍不能读取或写入全局供给，避免把定向学校授权提升为 platform 授权。
- TDD/回归验证：
  - RED：`npm test -- tests/formal-management-gates.test.tsx -t "学校范围供给授权"` 初始失败，页面进入 blocked，无法找到“平台智能体运营后台”，证明 school-scope `ops.supply.read` 触发了全局 `/api/v1/oms/supply` 403。
  - GREEN：同一前端测试通过；覆盖只有 `school_actions` 且无 `platform_actions` 时仍能进入学校列表、展示 `jygjzx`，并断言没有请求 `/api/v1/oms/supply`、没有显示“撤销供给批次”。
  - GREEN：`PYTHONPATH=. .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_permissions_summary_allows_school_scoped_operator_without_platform_grant` → 1 passed；该用例确认学校范围 operator 可读 `/me`、权限摘要和学校列表，但全局 `/supply`、Provider 写入和供给写入均 403。
  - GREEN：`npm test -- tests/formal-management-gates.test.tsx` → 47 passed。
  - GREEN：`npm run typecheck:oms` → `tsc --noEmit` 通过。
  - GREEN：`npm run build:oms` → Next.js 16.2.3 production build 通过。
- 本地服务更新：已重建 OMS 前端、同步 `.next/static` 到 standalone 目录并重启 4310 standalone server；后端 8001 和 4309 同源代理保持运行。
- local-ssl 验证：`$HOME/Projects/maintenance/scripts/local-ssl.sh status` 显示 dnsmasq/nginx 均运行且 `deeptutor.lfun.pub -> 127.0.0.1`；`https://deeptutor.lfun.pub/oms/_next/static/...` 当前抽样 12 个静态文件均 200；无效 chunk `https://deeptutor.lfun.pub/oms/_next/static/not-a-real-chunk.js` 返回 404；未登录访问 `/api/v1/oms/auth/status` 返回 401。

## 2026-09-30 模型与服务 / 供应商连接正式草稿写入补齐

- 纠正前一轮“逐连接凭据配置 API 尚未纳入 OMS v1”的保守状态：`供应商连接` 页面现在通过正式 `POST /api/v1/oms/provider-settings/dry-run` 与 `POST /api/v1/oms/provider-settings/draft` 承接 Provider 设置 JSON；逐连接“配置凭据/轮换凭据”不再是禁用原型按钮，而是打开同一正式导入对话框。
- `模型与服务` 页面新增 `保存模型草稿 JSON` 受控入口，提交完整模型草稿数组到 `POST /api/v1/oms/models/draft`，请求包含 `expected_version` 与 `reason`，继续由后端校验版本冲突、Secret `env:` 引用和 `ops.providers.manage`。
- Provider 设置对话框支持先 dry-run 再保存草稿，dry-run 请求带 `source_kind=oms-formal-ui`；保存草稿请求包含 `expected_version` 与 `reason`。前端不展示明文 Secret，模板仅提供 `env:*` 引用，列表/详情仍只显示脱敏凭据状态。
- 原型交互骨架保持不变：页面标题、Tab、搜索入口、连接表列和原有行级详情入口继续保留，只补齐正式写入按钮和对话框，不回退到本地演示数据或 fake save。
- TDD/回归验证：
  - RED：`npm test -- tests/formal-management-gates.test.tsx -t "正式 JSON 保存模型草稿|Provider 设置 dry-run"` 初始失败，找不到 `保存模型草稿 JSON` 按钮和 `导入 Provider 设置 JSON` 对话框。
  - GREEN：同一目标测试通过，覆盖模型草稿保存 body、Provider dry-run/draft body、版本号、reason、`source_kind` 和 Secret 不泄露。
  - GREEN：`npm test -- tests/formal-management-gates.test.tsx` → 49 passed。
  - GREEN：`npm run typecheck:oms` → `tsc --noEmit` 通过。
  - GREEN：`npm run build:oms` → Next.js 16.2.3 production build 通过。
  - GREEN：`npm run lint` → ESLint 通过。
  - GREEN：`git diff --check -- extensions/enterprise/frontends/apps/oms/src/OmsFormalApp.tsx extensions/enterprise/frontends/tests/formal-management-gates.test.tsx openspec/changes/deliver-oms-test-cn-management-v1/implementation-evidence.md` → 无输出；另用 `python3` 扫描上述三文件确认无行尾空白且保留结尾换行。
  - GREEN：`openspec validate deliver-oms-test-cn-management-v1 --strict` → valid。
  - GREEN：`openspec validate --all --strict` → 31 passed, 0 failed。
  - GREEN：`npm run lint` → ESLint 通过。
  - GREEN：`git diff --check -- extensions/enterprise/frontends/apps/oms/src/OmsFormalApp.tsx extensions/enterprise/frontends/tests/formal-management-gates.test.tsx openspec/changes/deliver-oms-test-cn-management-v1/implementation-evidence.md` → 无输出。
  - GREEN：`openspec validate deliver-oms-test-cn-management-v1 --strict` → valid。
  - GREEN：`openspec validate --all --strict` → 31 passed, 0 failed。
  - GREEN：`npm test`（enterprise frontends）→ 27 files / 303 tests passed。

## 2026-09-30 本地 OMS 学校代码/名称显示修复

- Root cause：test-cn 与本地派生的 `eduplus2.webhook_school_state.school_code` 均为空；后端 `tenant_projection()` 只返回该字段且没有 `school_name` 字段，前端 `schoolDisplayName()` 只能回退到稳定 `school_id`，所以学校列表显示 UUID 而不是学校代码/名称。
- 数据事实：test-cn 当前只有 `eduplus2.external_client_registrations.external_tenant_name` 可作为学校名称来源，且只有 `external_tenant_id=92` 有真实名称“晋元高级中学”；其它 test-cn registration 的学校名称为空。当前修复不会伪造缺失名称。
- 后端修复：`tenant_projection()` 增加 `school_name` DTO 字段；`school_code` 优先使用 Webhook 投影 code，空值时回退到 `enterprise.tenants.external_tid`，再回退到 `oms.school_bindings.eduplus_tenant_id`。学校名称从当前学校自己的 active `eduplus2.external_client_registrations.external_tenant_name` 读取。
- 前端修复：`OmsSchoolProjection` 增加 `school_name`；学校列表主标题优先显示学校名称，副标题显示 `代码 <school_code> · ID <school_id>`；详情抽屉增加“学校名称”，并继续显示“学校代码”和稳定“学校 ID”。路由与授权目标仍使用 `school_id`。
- 本地数据补齐（仅 local display unblock）：只读复制 test-cn `eduplus2.external_client_registrations` 投影到本地，8 条源数据插入 7 条，1 条因本地已有同一 active tenant/app 映射跳过；随后仅在本地按同一 EduPlus2 tenant id/code 将空 `external_tenant_name` 回填为已有真实名称。未写回 test-cn，未复制 token、secret、Keycloak 或 OpenFGA 状态。
- 本地数据校验：7 条已绑定学校的 display code 分别为 `237`、`265`、`266`、`267`、`92`、`970000682502`、`990000596628`；其中 `92` 的 display name 为“晋元高级中学”，其它名称为空源数据。
- TDD/回归验证：
  - RED：`PYTHONPATH=. .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_school_list_falls_back_to_eduplus_code_and_registration_name` 初始失败于 `school_code == ''`，且没有 `school_name`。
  - GREEN：同一后端测试通过；并与 `test_oms_school_list_uses_signed_school_projection_without_platform_app_claim`、`test_oms_governance_read_api_filters_by_local_school_grants_and_descriptors` 一起运行 → 3 passed。
  - RED：`npm test -- tests/formal-management-gates.test.tsx -t "学校列表优先展示"` 初始失败，找不到“晋元高级中学”。
  - GREEN：同一前端测试通过；完整 `npm test -- tests/formal-management-gates.test.tsx` → 49 passed。
  - GREEN：`npm run typecheck:oms` → `tsc --noEmit` 通过。
  - GREEN：`npm run build:oms` → Next.js 16.2.3 production build 通过。
- 本地服务更新：已重启 8001 后端与 4310 OMS standalone，并同步新 `.next/static` 到 standalone 目录。
- local-ssl 验证：`deeptutor.lfun.pub -> 127.0.0.1`，dnsmasq/nginx 均运行；当前 `.next/static` 抽样 12 个 `https://deeptutor.lfun.pub/oms/_next/static/...` 文件均返回 200。
  - GREEN：`PYTHONPATH=. .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_model_draft_is_versioned_audited_and_never_active_without_publish extensions/enterprise/tests/test_application.py::test_oms_provider_settings_are_versioned_redacted_confirmed_and_permissioned extensions/enterprise/tests/test_application.py::test_oms_school_scoped_operator_cannot_read_platform_provider_settings --tb=short` → 3 passed（覆盖管理员正例、版本冲突/明文 Secret 拒绝、school-scope 403）。

## 2026-09-30 本地 OMS 学校列表名称/代码分列修复

- UI 调整：OMS 主学校列表不再把学校名称、学校代码和稳定学校 ID 混在同一个“学校”列；列表现在分成“学校名称”和“学校代码”两列，并且列表单元格不显示 `school_id`。稳定 `school_id` 仍仅用于路由/API 授权目标和详情抽屉中的“学校 ID”。
- 同步调整：服务详情里的“授权学校”列表也复用同一名称/代码分列展示，避免学校列表类表格继续回退显示 ID。
- 缺失字段处理：若正式 DTO 暂未返回学校名称或学校代码，列表对应列显示“未返回”，不再用 `school_id` 冒充业务名称或代码。
- TDD/回归验证：
  - RED：`npm test -- tests/formal-management-gates.test.tsx -t "学校列表分列"` 初始失败，找不到“学校名称”表头，证明旧实现仍为单列展示。
  - GREEN：同一目标测试通过；覆盖“学校名称”“学校代码”分列、代码值 `71001` 独立显示，以及列表不出现 `ID school-1`。
  - GREEN：`npm test -- tests/formal-management-gates.test.tsx` → 49 passed。
  - GREEN：`npm run typecheck:oms` → `tsc --noEmit` 通过。
  - GREEN：`npm run build:oms` → Next.js 16.2.3 production build 通过。
- 本地服务更新：已重新构建 OMS 前端、同步 `.next/static` 到 standalone 目录并重启 4310 standalone server；后端 8001 与 4309 同源代理保持运行。
- local-ssl 验证：`$HOME/Projects/maintenance/scripts/local-ssl.sh status` 显示 dnsmasq/nginx 均运行且 `deeptutor.lfun.pub -> 127.0.0.1`；`https://deeptutor.lfun.pub/oms` 返回 307（进入正式入口/登录链路），当前构建抽样静态文件 `https://deeptutor.lfun.pub/oms/_next/static/chunks/0r9eewll1nbi7.js` 返回 200，无效 chunk `https://deeptutor.lfun.pub/oms/_next/static/missing-chunk.js` 返回 404。

## 2026-09-30 test-cn rc.70 提交与标签触发

- 发布规则核对：仓库级规则要求 test-cn 部署标签使用 `deploy/test-cn/vX.Y.Z-rc.N`，不得使用通用 `v*-test`；已从远端 tag 历史确认最新 test-cn 标签为 `deploy/test-cn/v1.4.0-rc.69`，本次递增为 `deploy/test-cn/v1.4.0-rc.70`。
- 本次提交范围：收敛 OMS v1 OpenSpec 主线、冻结/归档已完成或暂停的旧 proposal、保留当前 OMS/TMS 独立前端入口与本地 real-domain 调试规则、提交 OMS 学校列表/代码名称展示、权限失败关闭、静态资源、本地正式 DTO 接入与相关后端/前端测试。
- 提交前验证：
  - GREEN：`npm test`（`extensions/enterprise/frontends`）→ 27 files / 303 tests passed。
  - GREEN：`PYTHONPATH=. .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests` → 809 passed, 3 skipped, 2 warnings（既有 pytest mark warning）。
  - GREEN：`npm run typecheck:oms` → `tsc --noEmit` 通过。
  - GREEN：`npm run build:oms` → Next.js 16.2.3 production build 通过。
  - GREEN：`npm run lint` → ESLint 通过。
  - GREEN：`git diff --check` → 无输出。
  - GREEN：`openspec validate deliver-oms-test-cn-management-v1 --strict` → valid。
  - GREEN：`openspec validate --all --strict` → 31 passed, 0 failed。
- 本次推送目标：`master` 推送到 `origin/master`；随后创建并推送 `deploy/test-cn/v1.4.0-rc.70` 触发 test-cn Woodpecker 部署流水线。
