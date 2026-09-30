> **冻结/替代状态（2026-09-30）**：本 proposal 不再作为当前 OMS 执行主线；已完成项仅作为 `deliver-oms-test-cn-management-v1` 的证据来源，未完成项除非在新 proposal 中列明，否则暂停推进。不得把本 proposal 的未完成任务当作已交付或直接 archive。

> **实施中；任务 2.1、2.2 已完成，证据见 implementation-evidence.md。** 旧版“EduPlus2 同时掌管 OMS 动作权限”已被用户确认的职责拆分取代；当前修订版已获批准。只在 DeepTutor 仓库实施本产品 OMS 权限，不修改 EduPlus2。现有身份/账号状态/学校接口、权限迁移和负例未就绪前不装配跨学校写路由。

> **职责边界（非勾选项）**：本 change 是 OMS 治理 API 与读写边界，不拥有权限事实迁移（归 `add-enterprise-management-authorization`）、Provider 生效链（归 `add-enterprise-all-service-provider-settings`）、额度/用量总账（归 OMS 业务和 usage change）或正式前端（归 `add-c1-c2-oms-operator-interface`）。它只消费这些权威，并验证 `/api/v1/oms/*` 不经旧 admin、租户 token、header 或数据库权限绕过。

## B2.0 权限模型与迁移
- [ ] 1.1 只读核实 EduPlus2 **已交付** OIDC issuer/client/audience、稳定 `sub`、在线账号有效性和学校核验接口及所需现有凭据；记录缺失项，缺失时保持对应写路由关闭。不要求本代理在发送端新增 client、`ops.*` relation 或 provider 迁移。
  - [x] 1.1.1 已在本地与 test-cn 浏览器链路核实 `eduplus-platform-admin` 授权码登录和 OMS token-only 身份状态：认证可达但无 DeepTutor 本地 `ops.*` 时失败关闭；在线账号状态/学校目录合同仍归父任务。
- [ ] 1.2 依赖 `add-enterprise-management-authorization` 的 DeepTutor Enterprise 唯一授权服务及企业 PG 权限事实迁移：平台主体 `(issuer,sub)`、默认零权、角色/动作、`platform`/`school` 范围、撤权、学校绑定、签名真实 `subscription.created.actor.user_id` 一次性首位管理员登记与本人激活及追加审计；本 change 不建平行权限表；合成数据验证 RLS、幂等、重复 apply/verify、drift、最后管理员保护与 `tenant_admin` 不继承。已应用 `0011` 不修改，契约差异另增迁移。
  - [x] 1.2.1 已消费管理授权 change 的本地权限事实与统一 PEP：`ops.*` platform/school 范围、零权失败关闭、受控首位 OMS 管理员初始化、assignment 撤权/主体停用/审批 apply 和 school-scope 不能冒充 platform 均有合成验证。
- [ ] 1.3 测试先行：无 token、租户 token、错 issuer/audience/签名、外部账号停用/接口故障、伪造 scope/目标学校、拿学校授权冒充全局权限、本地撤权及在途竞态均拒绝；默认管理员和自定义动作正例，operator/auditor 高权限写 403。
  - [x] 1.3.1 已用后端/前端测试覆盖 OMS 缺本地授权失败关闭、租户 token/普通学校 token 不进入 OMS、school-scope grant 调用 platform Provider/供给写 API 返回 403、自定义角色正例和高权限按钮按 `ops.*` key 显隐。
## B2.1 真实分级治理 API
- [x] 2.1 实现 Enterprise 程序层 `require_platform_permission(action)`、按动作选定 `platform`/`school` 范围、涉及学校时经权威核验的绑定与受审计事务；在同一 PG 写事务复核本地权限/绑定版本，外部账号在线状态不可用时 fail closed。企业 app 不挂核心旧 OMS `require_admin` 旁路，CLI/SDK/后台无直写；已撤回发送端 OMS 授权客户端不得装配。
- [x] 2.2 实现总览、资源/配置、供给、权益/额度、用量、核对、成本、审计与任务的最小化治理 API 和后端 display catalog；具体写事务调用 OMS 业务唯一总账，不复制实现。
- [ ] 2.3 独立 OMS 前端入口/按钮/路由守卫与 DeepTutor 后端 `ops.*` 同 key，含仅高权限可见的平台人员/角色/学校操作范围；不得含学校账号或首位管理员开通；缺 descriptor 安全降级。TMS 不读取 OMS 权限，仍仅当前租户安全投影，无后端数据时显示未启用。
  - [x] 2.3.1 已完成正式 OMS 前端入口/按钮/路由守卫与后端 `ops.*` 同 key 接线：平台人员/角色/学校操作范围只在 `ops.permissions.manage` 下展示；无学校账号/首位学校管理员开通入口；TMS 不读取 OMS 权限。
## B2.2 验收
- [ ] 3.1 双租户 PG + HTTP/API 正负例、Secret/成本/私有内容泄露及导出负例、TMS/OMS 边界与 upstream seam 检查。
  - [x] 3.1.1 已覆盖本地双学校/学校范围合成负例、Secret/成本/私有正文不泄露、TMS/OMS DTO 边界、Provider/供给 platform-vs-school 权限边界与旧学校开通深链 404；真实双学校外部登录负例仍未完成。
- [ ] 3.2 运行 CLI、HTTP/WS、SDK、后台、session owner、审计关联测试与 OpenSpec strict validation；保留 DeepTutor PG 权限迁移 plan/apply/verify、真实既存 OIDC/账号/学校接口联调、撤权/回退和入口证据，不要求外部 OpenFGA/Keycloak 迁移。
  - [x] 3.2.1 已完成当前本地回归：企业后端全量测试、企业前端全量测试、OMS/TMS typecheck/build、frontends lint、OpenSpec strict validation、`git diff --check` 与只读 upstream merge-tree smoke 均通过；真实既存 OIDC/账号/学校接口综合联调仍归父任务。
