# OMS v1 收敛设计

## 目标

以最短路径交付 test-cn 可用 OMS：让 `.secrets/.login-credentials` 中的 admin 账号能够通过正式 `/oms` 入口完成登录、看到授权范围内的 OMS 功能，并对 v1 范围内的读写动作完成真实 API 验收。

## 收敛原则

1. **一个主线**：OMS v1 的新增任务、验收和证据只写入本 change。
2. **旧 proposal 只作证据来源**：旧任务已完成项可引用，但不再继续在旧 proposal 下拆分推进。
3. **v1 只做必要闭环**：优先让 OMS 可用、可验证、可部署；把全量角色矩阵、全 provider adapter、HA、多学校全量验收放到后续 proposal。
4. **真实链路优先**：本地必须经过 `local-ssl` 的 `https://deeptutor.lfun.pub/oms`；test-cn 必须经过部署域名和真实 admin 账号。
5. **失败关闭**：任何缺少本地 `ops.*`、学校范围、版本、CSRF/Origin 或外部身份状态的路径继续失败关闭。

## v1 范围

### 已纳入

- OMS 正式入口与授权码登录。
- 首位平台管理员初始化和本地 `ops.*` 授权。
- 学校列表/详情和学校范围授权过滤。
- 模型与服务、Provider 草稿/测试/发布/回滚。
- Agent/工具/知识基础能力/运行资源的安全状态投影。
- Skills 列表、review、publish、grant。
- 服务供给、学校服务授权、额度 grant/adjust/revoke/expire。
- 用量 attempt、待核对任务、成本状态、审计投影。
- 平台人员、角色、学校范围授权、assignment 撤权、主体停用、审批 review/apply。
- local-ssl 本地真实域名调试和 test-cn admin-only 验收。

### 暂不纳入

- TMS 完整后台和学校成员/应用管理。
- 全供应商真实 adapter 的逐服务 usage/账单样本。
- 外部学校目录搜索合同。
- 全平台角色矩阵和双学校真实账号完整负例。
- HA/多执行者、容量与故障恢复。
- 租户费用、账单、欠费停机或支付流程。

## 验收口径

- 本地：`https://deeptutor.lfun.pub/oms` 可打开，未登录自动跳转，登录后 admin 可用；无效 `_next/static` chunk 返回 404，有效 chunk 返回 200。
- 后端：所有 v1 写 API 使用 DeepTutor Enterprise PEP、版本/幂等/审计，不能由 header、tenant_admin、EduPlus2 role 或 DB 权限绕过。
- 前端：不显示调试页、不使用 fixture、不回退原型、不显示学校账号开通。
- test-cn：部署后只用 `.secrets/.login-credentials` 中 admin 账号完成 v1 入口、核心菜单、读写按钮和失败关闭验收。
