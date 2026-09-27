# 设计：EduPlus2 身份与 DeepTutor OMS 应用权限边界

## 权威与登录

EduPlus2 继续权威维护外部账号、学校和租户生命周期；DeepTutor 只消费**已存在且适用 OMS**的 OIDC issuer/JWKS、client/audience、账号在线状态及学校核验接口，不修改 EduPlus2 仓库或外部 Keycloak/OpenFGA。OMS 登录验证签名、`iss/aud/azp/exp/iat/sub`，敏感写入前再核实外部账号当前有效；缺可用 client、凭据或在线接口时写入口 fail closed。平台与租户可共用 issuer，但不可复用要求 `tid/eui` 的普通租户换票；JWT realm/client role、`eit`、用户名、`X-Scopes`、Webhook secret 和 `tenant_admin` 均不是 OMS 授权证据。平台与租户 session 不互继承。

DeepTutor Enterprise 程序是**仅限智能体基座 OMS/TMS**的应用授权决策权威，PG 只保存权限事实、版本与审计，RLS/约束仅作隔离兜底；本 change 只消费 [`add-enterprise-management-authorization`](../add-enterprise-management-authorization/design.md) 的 OMS 域服务，不另建权限表或第二套角色迁移。平台主体按 `(issuer,sub)` 唯一绑定，默认零权限；受限且可审计的初始管理员登记流程只接受已验证外部主体，禁止注册即获权、租户管理员升级或自授。版本化角色模板、可定义角色、逐 `ops.*` 动作与范围授权、有效期、撤权版本和审计均在本仓库迁移；角色名称不自动授予全部能力。范围显式区分 `platform` 与 `school`：全局 Provider/Secret 配置及未绑定学校的供应采购只接受对应动作的 `platform` 授权，不能用任一学校授权代替；学校权益、额度、学校定向供给和跨校明细须有对应 `school` 授权，若写动作同时影响全局和学校则两者都查。角色/授权管理另需 `ops.permissions.manage`；全局角色模板变更需 `platform` 范围，学校授权变更需该学校范围，均附原因、幂等键、预期版本，并禁止无恢复路径地撤销最后管理员。

内部 UUID 与外部学校 ID 只通过 EduPlus2 已交付学校权威接口建立一对一、已核验、可撤权的版本化绑定；学校码、`external_tid` 文本或请求参数不构成授权。外部 ID 类型/状态语义以真实接口为准；现有数字 ID 的 `0011_school_binding.sql` 不自动回填，若契约不同通过后续 DeepTutor 迁移适配。没有学校核验接口时关闭针对该学校的写入口。每次管理写入先在线确认外部账号仍有效，再在同一 PG 业务事务内锁定、复核主体状态、动作/所需范围授权版本和业务对象版本；涉及学校时还须复核权威学校绑定版本；撤权与在途写入按同一锁序串行，禁止缓存的旧允许结果放行。读/导出同样逐动作和 `platform`/`school` 范围过滤。跨学校数据使用受限受审计事务，不把 BYPASSRLS 连接交普通请求；未认证 401、无权 403、目标不存在按防枚举策略 404。

## 治理 API 与界面

API 草案：`GET /api/v1/oms/summary|tenants|tenants/{id}|resources|providers/status|supply|entitlements|quotas|usage|reconciliation|cost|audit|jobs`，以及与 OMS 唯一总账和配置 change 对应的受控写动作；另在 OMS 治理范围内提供角色、动作与学校授权的受控管理 API/页面，不建立第二套供给或用量权威。租户详情仅展示 EduPlus2 lifecycle/本地隔离、同步异常和逐服务授权/额度状态，不再有独立欠费模型资格。列表分页和范围有上限；普通运营 DTO 仅含必要脱敏元数据，成本需 `ops.cost.read` 独立授权，Secret 明文、私有正文、完整 JWT/token/长期下载 URL 一律不返。TMS 仅从安全投影读取当前学校配额/用量，不能调用 OMS 专有 DTO。ObjectStore summary 不冒充实际供应商用量。

能力矩阵：`ops.oms.access` 控入口；`ops.tenants.read`、`ops.clients.read`、`ops.providers.read/manage`、`ops.credentials.manage`、`ops.supply.read/manage`、`ops.entitlements.read/manage`、`ops.quotas.read/manage`、`ops.usage.read`、`ops.reconciliation.manage`、`ops.cost.read`、`ops.audit.read/export`、`ops.jobs.read` 与 `ops.permissions.manage` 分权。平台 admin/operator/auditor 的默认**应用权限**由 DeepTutor 版本化模板给出，自定义角色须显式授权；最终由 Enterprise 程序按当前权限事实和 `platform`/`school` 范围检查。OMS 无 EduPlus2 租户开停、TMS client 注册或一般成员管理写能力；TMS／学校侧的首位管理员双人开通是唯一例外。配置、供给、授予、核对、授权变更及导出均需 reason、expected_version/幂等键及 actor/目标/前后版本/request ID/结果审计；Secret/成本权限不从普通读权限继承。状态由后端返回稳定 `code`、`label`/`tone`、`description`、`observed_at` 与来源，详情含影响、下一步、时效及 descriptor 版本。

主体/角色/动作/范围/撤权/审计只由 `add-enterprise-management-authorization` 在本仓库企业 PG 统一迁移；本 change 仅增加 OMS 治理业务所需表，不迁移 EduPlus2/OpenFGA/Keycloak。菜单、路由、按钮和 API 使用同一权限 key。核心旧 OMS router 不挂企业 app，不能靠注册顺序覆盖；CLI/SDK/后台不设直写旁路。验收包含错 issuer/audience/签名、外部账号停用/接口故障、本地撤权与在途竞态、tenant_admin/伪造 header、跨学校/Secret/成本/导出负例，及默认管理员/自定义角色正例；最后以既存外部接口受控联调。已撤回的发送端 OMS 授权客户端不能作为生产授权后端。
