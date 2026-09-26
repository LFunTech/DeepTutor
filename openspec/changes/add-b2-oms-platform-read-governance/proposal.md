# OMS 平台身份、动作权限与跨租户治理 API

> **实施已获批准（2026-09-26）**：已替换旧“只读 OMS”目标。用户选定 EduPlus2 平台身份与权限并单独批准本 change；但 OMS client/audience、主体/动作/目标范围/撤权契约仍待发送端提供，在双方受控契约和合成负例完成前不装配跨租户写路由。

## Why
当前 PG 身份只有 `tenant_admin/user`，核心同名 OMS 占位 router 仍以 `tenant_admin` 鉴权，企业外壳未挂载该 router。现有 EduPlus2 换票还要求租户 `tid/eui/sub/azp` 且过滤管理权限，不能复用为 OMS 平台主体。必须先交付独立可信平台身份、动作授权和受控跨租户读写边界。

## What Changes
- 由 EduPlus2 受信 OIDC issuer 的**专用 OMS client/audience**与权限权威提供平台主体及具体 `ops.*` 动作权限/撤权版本；DeepTutor 受控映射、逐动作验证，默认及自定义平台角色均不从 `tenant_admin` 继承。平台路径可与租户用户共用 Keycloak realm issuer，但不得复用 DeepTutor 现有租户换票与身份 scope。
- 企业 `/api/v1/oms/*` 提供总览、租户、client/app、资源/配置、供给、授权/额度、用量、核对、成本、审计、任务的分级治理 API；OMS 不写 EduPlus2 租户开停、TMS 成员/client 或私有正文。供给/额度/用量事务仍由 OMS 业务逻辑 change 定义唯一总账。
- 先鉴权再绑定显式目标租户及动作范围；写入需 expected_version/幂等键、原因和审计；读/导出采用最小字段、分页、脱敏和后端 display descriptor，TMS 仅本租户安全 DTO。
- 隔离核心 `tenant_admin` 保护的同名 OMS 占位接口，禁止 router 顺序覆盖、CLI/SDK/后台直写或客户端 header 冒充平台身份。
- **BREAKING**：旧仅只读 OMS 与独立费用/欠费/模型资格权限目标废止。

## Capabilities
### New Capabilities
- `enterprise-platform-oms-read-governance`: 平台身份、动作权限、读写治理 API 与运营状态展示契约（保留历史 capability ID，语义已扩展）。
### Modified Capabilities
无；如需改现有正式身份 spec，实施前补 delta。

## Impact
DeepTutor 企业扩展 PG 平台主体绑定/权限快照/审计迁移、企业 API/Store、状态 catalog、前端权限 bootstrap；core 仅经严格审阅的通用 seam。依赖 B2 多租户可信绑定、EduPlus2 平台签发/权限发送端契约与 lifecycle webhook；外部角色/relation/scope/claim/client 如需扩展，必须由 EduPlus2/相应权限系统版本化迁移，不由本地 DB 自造管理员。
