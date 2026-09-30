# 实施证据：OMS 平台只读治理与分级 API

## 2026-09-28 最小治理 API 与后端状态目录

完成任务：2.2。

实现内容：

- 新增 `deeptutor_enterprise.oms.governance`，集中提供后端拥有的状态 descriptor/catalog，覆盖生命周期、绑定、配置就绪、用量 attempt、审计结果与运行时资源状态；未知 code 返回“状态说明缺失，请联系支持”，前端不得硬编码 raw code。
- 在企业 FastAPI 装配新增 OMS 治理读 API：
  - `GET /api/v1/oms/status/catalog`
  - `GET /api/v1/oms/summary`
  - `GET /api/v1/oms/tenants`
  - `GET /api/v1/oms/tenants/{school_id}`
  - `GET /api/v1/oms/supply`
  - `GET /api/v1/oms/schools/{school_id}/usage`
  - `GET /api/v1/oms/schools/{school_id}/jobs`
  - `GET /api/v1/oms/audit?school_id=...`
  - `GET /api/v1/oms/cost`
- 所有新增 OMS API 均先经 `_authorize_oms_request` 和 DeepTutor Enterprise 本地 `ops.*` PEP；跨学校列表只返回当前平台主体已获 `ops.tenants.read` school-scope 授权且经绑定/业务状态复核的学校，不接受 header/query/body 的租户覆盖。
- 响应只包含脱敏运营元数据，不返回 Secret、供应商 endpoint、evidence 原文、`provider_request_id`、私有正文、成本明细或长期 URL。成本源未核实时返回 `not_configured`，不从配额/用量推导经营成本。
- 具体供给、权益、额度和用量仍读取 OMS 业务唯一总账表，不复制第二套写入权威；TMS 仍只读取当前学校安全投影。

验证：

- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_governance_read_api_filters_by_local_school_grants_and_descriptors --tb=short` → 1 passed。
- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/oms/governance.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py` → passed。

未覆盖/阻断：

- 真实 `eduplus-platform-admin` 授权码登录、在线账号状态与学校核验接口仍需目标环境证据，任务 1.1、3.2 不因此完成。
- 独立 OMS 前端按钮/路由守卫尚未接入这些正式治理 API，任务 2.3 不因此完成。
- 高风险导出、真实成本源、真实双学校外部 OIDC 联调仍未开放。

## 2026-09-28 任务 2.1：OMS 专用程序层 PEP 入口

完成任务：2.1。

实现内容：

- 在 `deeptutor_enterprise.oms.governance` 新增 `require_platform_permission(connection, identity, action, target_school_id=None, write=False)`，作为 OMS 专用 PEP 包装：
  - 只接受 `ManagementIdentity(application="oms")` 与 `ops.*` 动作；
  - 再委托统一 `require_management_permission()` 按 DeepTutor PG 本地权限事实、显式 `platform`/`school` 范围、学校绑定版本、撤权版本、业务状态与事务锁复核；
  - `write=True` 时把目标学校锁序传入统一授权服务，避免学校授权撤销与业务写入反序。
- 企业 FastAPI `_authorize_oms_request()` 改为调用该 OMS PEP 入口；每个正式 `/api/v1/oms/*` 请求仍先验证 OMS Bearer、在线账号状态，再查 `ops.oms.access` 与具体动作。租户 `dt_token`、普通学校 token、伪造 header/query 的 tenant override 和未配置外部 OMS 身份适配器均失败关闭。
- 继续不挂载核心旧 OMS `require_admin` router；既有 CLI/SDK 公开面无 Provider/OMS 管理写命令。

验证：

- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/oms/governance.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py` → passed。
- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_governance_read_api_filters_by_local_school_grants_and_descriptors extensions/enterprise/tests/test_application.py::test_oms_me_uses_verified_platform_identity_and_local_action --tb=short` → 2 passed。

未覆盖/阻断：真实 `eduplus-platform-admin` OIDC 授权码登录、账号状态端点、双学校外部学校核验和正式前端权限守卫仍未完成；任务 1.1、2.3、3.1、3.2 不因此完成。

## 2026-09-30 正式 OMS 前端与权限负例同步

本节同步后续管理授权、OMS 业务和 C1/C2 界面 proposal 已完成的本地成果；真实外部账号状态、双学校真实登录和 test-cn 综合验收仍不关闭父任务。

- 身份与默认零权：
  - 已在本地与 test-cn 浏览器链路验证 `eduplus-platform-admin` 授权码登录可达；无 DeepTutor 本地 `ops.*` 时 `/api/v1/oms/me` 返回 403，正式页面失败关闭，不回退原型。
  - 正式 OMS 零本地管理员场景可受控自动初始化首位平台管理员；该初始化仍只依赖已验签 OMS 会话与 DeepTutor 本地事务，不读取 EduPlus2 角色/权限。
- 权限与入口：
  - 正式 OMS 前端按 `/api/v1/oms/me/permissions` 的 `ops.*` 动作控制读取面与按钮：Provider/模型、Skill、学校范围、服务授权/额度、供给批次、权限治理均与后端 API key 对齐。
  - 平台人员、角色、学校操作范围、审批、assignment 撤权和主体停用只在 `ops.permissions.manage` 下显示；OMS 不展示学校账号或首位学校管理员开通入口，旧 `/oms/tms-bootstrap*` 深链 404。
  - TMS 独立读取 `/api/v1/tms/*` 当前学校 DTO，不读取 OMS 权限或平台 Provider/Secret 字段。
- 负例与泄露边界：
  - 后端/前端覆盖 school-scope operator 不能调用 platform Provider/供给写 API，未委托学校 403，自定义角色正例，高风险按钮按 `ops.*` 隐藏/显示。
  - Provider、供给、成本、Skill、知识基础能力详情均使用安全 DTO；不回显 Secret、采购 evidence 原文、供应商成本、学校私有正文或未授权 builtin 内容。
- 验证：
  - `npm test --prefix extensions/enterprise/frontends` → **27 files / 297 tests passed**。
  - `.venv/bin/python -m pytest extensions/enterprise/tests -q` → **803 passed, 3 skipped, 2 warnings**。
  - `npm run typecheck:oms --prefix extensions/enterprise/frontends && npm run typecheck:tms --prefix extensions/enterprise/frontends && npm run build:oms --prefix extensions/enterprise/frontends && npm run build:tms --prefix extensions/enterprise/frontends` → **通过**；`npm run lint --prefix extensions/enterprise/frontends` → **通过**。
  - `openspec validate add-b2-oms-platform-read-governance --strict` → 见本轮验证记录；`git diff --check` → **通过**。
  - 只读 upstream mergeability smoke 未发现 merge-tree 冲突标记，未执行 merge/rebase/reset。

任务影响：新增勾选 **1.1.1、1.2.1、1.3.1、2.3.1、3.1.1、3.2.1**。父任务 **1.1、1.2、1.3、2.3、3.1、3.2** 仍不关闭；在线账号状态接口、真实双学校外部学校核验、真实账号撤权/回退和 test-cn 端到端综合验收仍待完成。
