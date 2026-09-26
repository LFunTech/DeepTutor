## Purpose
为普通运营和高权限平台角色提供 EduPlus2 可信平台身份、动作级权限与跨租户治理 API。

## ADDED Requirements
### Requirement: 平台 OMS 权限必须独立于 tenant_admin
系统 SHALL 为每个 OMS API 验证 EduPlus2 受信 OIDC issuer/JWKS、专用 OMS client/audience、签名、有效期及由 EduPlus2 权限权威确认的具体 `ops.*` 动作和撤权状态；不得从 JWT realm/client role 推断业务权限。租户换票、`tenant_admin`、普通用户、伪造 header/claim MUST NOT 获得平台权限。平台/租户 session 不互继承，前端入口 key 与后端 key 一致。
#### Scenario: 租户管理员直调
- **WHEN** tenant_admin 直接请求 `/api/v1/oms/tenants`
- **THEN** 后端返回 403 且不泄露跨租户数据
#### Scenario: 自定义平台只读角色
- **WHEN** 经 EduPlus2 可信授权的自定义角色仅具备 `ops.tenants.read`
- **THEN** 只能读取授权的运营元数据，不能写供给/配额或读取成本/Secret

#### Scenario: 伪造平台 token
- **WHEN** 客户端提交错 issuer/audience、过期或撤权版本的 token，或在租户 token 附加 `X-Scopes`
- **THEN** 平台 API 拒绝且不生成写入或跨租户数据响应

### Requirement: OMS 治理 API 必须按动作与目标范围绑定
系统 SHALL 提供授权范围内总览、租户、client/app、资源/配置、供给、授权/额度、用量、核对、成本、审计、任务的分级读写 API；查询和写入先鉴权后绑定显式目标，响应最小化。OMS MUST NOT 写 EduPlus2 租户开停、TMS client/成员或租户私有正文；供给/额度/用量 MUST 使用 OMS 业务逻辑唯一总账，不能在此 change 建第二套。写入需要 expected_version、幂等键、原因和审计；导出单独授权。
#### Scenario: 任意 tenant override
- **WHEN** 用户在 query/header/body 伪造其他 tenant ID
- **THEN** 不扩大其授权范围

#### Scenario: 普通运营尝试高权限动作
- **WHEN** 仅有 `ops.oms.access` 与 `ops.tenants.read` 的平台 operator 写供给、轮换 Secret 或导出成本
- **THEN** 系统逐动作返回 403，未写入且记录脱敏拒绝审计

### Requirement: 后端必须持有运营状态展示描述
系统 SHALL 为 EduPlus2 lifecycle、本地隔离、逐服务授权/额度、同步、配置生效、任务及原因码返回后端拥有的 descriptor/catalog，列表精简、详情含影响与下一步；额度不足 MUST NOT 展示为租户停用，前端不得硬编码 raw code 语义。
#### Scenario: 缺 descriptor
- **WHEN** 状态缺少展示描述
- **THEN** 前端显示“状态说明缺失，请联系支持”，不展示 raw code 作为业务文案

#### Scenario: 单服务额度耗尽与租户启用并存
- **WHEN** 租户 lifecycle 为启用但某服务额度耗尽
- **THEN** OMS 展示“可登录和管理”与对应服务“新调用受限”，不将租户标为停用

### Requirement: OMS 查询不得泄露经营与私有数据
普通治理查询 MUST NOT 返回供应商成本、Secret、私有正文、完整 prompt、JWT 或长期下载 URL；成本仅在 OMS 专有接口经 `ops.cost.read` 授权返回，TMS 仅当前租户安全权益/用量投影。
#### Scenario: auditor 查任务
- **WHEN** auditor 查询跨租户任务
- **THEN** 只收到状态、时间、影响和脱敏诊断摘要
