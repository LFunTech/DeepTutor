# OMS 可信外部身份、本地应用权限与跨学校治理 API

> **双应用域权限依赖修订（2026-09-27，当前修订版已单独获批）**：用户确认不得修改 EduPlus2，既存外部接口仅作身份、账号状态和学校核验；DeepTutor 企业扩展自行维护仅限本产品 OMS 的动作、目标学校授权与撤权。批准不等于完成迁移、真实身份/学校契约或负例验收；此前不装配跨学校写路由。

## Why
当前 PG 身份只有 `tenant_admin/user`，核心同名 OMS 占位 router 仍以 `tenant_admin` 鉴权，企业外壳未挂载该 router。现有 EduPlus2 换票还要求租户 `tid/eui/sub/azp` 且过滤管理权限，不能复用为 OMS 平台主体。发送端 OMS 权限草稿已撤回；要在不修改外部系统的前提下完成跨学校治理，必须把可信外部身份与本产品 OMS 应用权限分开。

## What Changes
- 使用 EduPlus2 **既存且适用 OMS 的**受信 OIDC issuer/client/audience、在线账号状态和学校核验接口确认外部身份/学校；不要求本代理新增发送端 client、relation、角色或迁移，接口不具备时对应写入口 fail closed。
- DeepTutor Enterprise 程序以 `(issuer,sub)` 绑定平台主体，按本地 PG 事实逐请求判定默认/自定义 OMS 应用角色、`ops.*` 动作、显式 `platform`/`school` 范围和撤权版本；PG 只保存事实与审计，数据库权限/RLS 不代替程序授权；默认零权，首次管理员经受控运维登记，不从 `tenant_admin`、JWT role、用户名、header、Webhook secret 或普通换票继承。
- 企业 `/api/v1/oms/*` 除按 `add-enterprise-management-authorization` 提供平台人员/角色/学校操作范围与审计适配外，提供总览、租户、client/app、资源/配置、供给、授权/额度、用量、核对、成本、审计、任务的分级治理 API；OMS 不写 EduPlus2 租户开停、任何 TMS 学校账号/client 或私有正文；首位管理员开通仅由 TMS／学校侧受控完成。供给/额度/用量事务仍由 OMS 业务逻辑 change 定义唯一总账。
- 先鉴权并判定 `platform`/`school` 范围；涉及学校时再绑定权威目标学校；写入需 expected_version/幂等键、原因和审计；读/导出采用最小字段、分页、脱敏和后端 display descriptor，TMS 仅本租户安全 DTO。
- 隔离核心 `tenant_admin` 保护的同名 OMS 占位接口，禁止 router 顺序覆盖、CLI/SDK/后台直写或客户端 header 冒充平台身份。
- **BREAKING**：旧仅只读 OMS 与独立费用/欠费/模型资格权限目标废止。

## Capabilities
### New Capabilities
- `enterprise-platform-oms-read-governance`: 平台身份、动作权限、读写治理 API 与运营状态展示契约（保留历史 capability ID，语义已扩展）。
### Modified Capabilities
无；如需改现有正式身份 spec，实施前补 delta。

## Impact
依赖 `add-enterprise-management-authorization` 的 DeepTutor 企业 PG 双应用域主体/角色/动作/范围/撤权/审计唯一迁移，本 change 不建平行权限表、企业 API/Store、状态 catalog、前端权限 bootstrap；core 仅经严格审阅的通用 seam。依赖 B2 多租户可信绑定、EduPlus2 **已交付**的 OIDC/账号状态/学校核验接口与 lifecycle webhook；若这些接口不满足要求，只能由其所属团队独立提供，DeepTutor 不修改 EduPlus2 代码或外部 Keycloak/OpenFGA 状态。本地权限是本产品应用权限，不声称成为 EduPlus2 通用平台权限主数据。
