# B1/B2 可信学校接入与多学校隔离

> **2026-09-27 已获用户单独批准按现版实施；实施中，不开放正式管理写入或真实学校流量。** 只修改智能体基座所在的 DeepTutor 仓库；EduPlus2、Keycloak、OpenFGA 由各自团队维护。隔离合成数据可用于实现验证，真实学校数据、发布、提交、归档均另行授权。

## Why

已归档的第三方换票能力和固定学校 PG 底座，不能证明最终 B1 学校登录绑定、全入口撤权以及 B2 双学校数据面隔离已完成。目前多个管理提案分别依赖这些能力，却缺少一个对可信学校接入、资源隔离和 G2 放量门禁负责的实施 change；若直接接通 OMS/TMS，学校码、旧管理员标签或现有 Webhook demo 容易被误当作授权证据。

## What Changes

- B1 复用已交付的 EduPlus2 OIDC/JWKS、client resolve、本人 Profile 和普通能力换票；按已核实的既存外部学校／账号接口将首所学校的权威外部 ID 绑定到稳定内部 `tenant_id`，并验证登录、HTTP/WS/SDK、后台和第三方应用用户 JWT→`dt_token` 闭环。缺在线核验合同时，相应管理会话与敏感写入失败关闭，不自建发送端接口。
- B2 将相同绑定扩展至多所学校；建立版本化绑定、撤权栅栏、受限 PG 事务范围与资源 owner/grant、对象/S3、LightRAG workspace/图检索、缓存和任务的双学校隔离。`school_code` 仅用于定位，必须与已验证会话的学校 ID/code 绑定复核。
- 对租户生命周期仅消费独立的 `add-b2-eduplus2-tenant-lifecycle-webhook` 结果，不复刻签名 inbox 或用 mock 事件推断学校状态；外部状态、本地隔离和应用权限分别判定。OMS 只管理平台人员与逐校 `ops.*` 范围，不创建学校账号、不授予 `tenant.*`，首位 TMS 管理员由 `add-enterprise-management-authorization` 的学校侧流程负责。
- 建立 B1 单学校受控验证→B2 双学校全入口正负例→G2 放量的证据门禁；第三方应用、TMS、OMS 各自独立的认证与权限验收不能由一次普通用户换票或 Webhook demo 替代。
- **BREAKING（相对旧规划）**：不把 `eit=adm`、旧 `tenant_admin`、学校码、客户端 `tenant_id`、Webhook secret 或普通 `dt_token` 当作 OMS/TMS 管理身份；未验收的外部学校/账号接口不以 fixture、手工改库或降级缓存代替。

## Capabilities

### New Capabilities

- `enterprise-trusted-school-binding`：B1 外部身份与稳定内部学校、账号绑定及全入口撤权栅栏。
- `enterprise-multischool-isolation`：B2 全数据面双学校隔离和 G2 受控放量。

### Modified Capabilities

无。已归档的普通第三方换票与 PG scoped persistence 契约继续有效，本 change 增加最终 B1/B2 验收，而非倒改其历史范围。

## Impact

主要涉及 `extensions/enterprise/` 的 EduPlus2 适配、学校绑定版本化 PG 迁移、企业认证上下文、资源/任务适配器和受控发布验证；core 只允许上游中立的 scope、owner、生命周期 seam。依赖 M1/G1 可用底座及 EduPlus2 **已交付且适用**的外部接口；与 `add-enterprise-management-authorization`、生命周期 Webhook、TMS 业务、OMS 权益和全服务配置/用量总账分别保持权威边界。已有 `oms/0011_school_binding.sql` 不可原位修改，需新增版本迁移。无发送端代码或真实学校数据变更。
