# 云端 TMS 业务逻辑基础契约

> **2026-09-29 执行版**：当前修订版已获批准，并已完成 TMS 存储归属与分层权限测试矩阵。TMS 的 `tenant.*` 本产品权限由 DeepTutor Enterprise 程序按本地 PG 事实判定，与 OMS `ops.*` 共用内核但域隔离；PG 数据库权限/RLS 不代替程序鉴权，EduPlus2 在权限链路中只提供认证和稳定身份识别。用户指定签名真实 `subscription.created.actor.user_id` 为首位学校管理员身份来源，由本系统一次性登记、本人登录匹配后激活；不走旧双负责人开通。随后 TMS 管理本校权限。详细规则由 [`add-enterprise-management-authorization`](../add-enterprise-management-authorization/proposal.md) 唯一规定；mock/外部角色均不自动授权。

## Why

现有 [`add-b2-tms-management-prototype`](../add-b2-tms-management-prototype/proposal.md) 已确定单一可信租户、六组导航、共享组件与配额只读，但尚未形成可实施的租户身份、应用接入、成员/资源授权、知识内容管理和用量查询业务契约。旧企业文档仍混有单体前端、TMS 可调整配额或 OMS 只读的过时描述；正式开发不能直接按页面原型或旧路由推断后端权限。

## What Changes

- 将 TMS 对外称为**学校智能体管理后台**，保留 TMS 技术缩写、`/tms` 入口和现有 `tenant_id`、`tenant.*`、Skill `owner=tenant` 契约；在 EduPlus2 教育业务中一个 tenant 即一所学校，`school_code` 即学校的 tenant code，界面和业务文档使用“学校”。正式路由为 `/tms/{schoolCode}` 及其列表/详情子路径，URL code 只定位学校并与可信账号绑定核对，不能单凭 URL 授权或任意切换学校。
- EduPlus2 继续维护外部账号、学校和登录凭证；DeepTutor 在经验证的 `(issuer,sub,school)` 绑定上管理仅限本产品的 `tenant.*` 角色与动作，首次登录零权。首位学校管理员由已验签真实 `subscription.created.actor.user_id` 一次性登记，本人登录与学校身份精确匹配后由 Enterprise 程序激活，后续本校授权由 TMS 管理；一般 lifecycle 事件和 mock 不授予管理员权限。缺既存在线账号或学校核验能力时正式管理写入口保持关闭。
- 定义 TMS 仅在可信当前租户内管理本租户应用/client、明确获授权的成员与资源使用权、共享 KB/文档和允许的 Agent/工具使用；EduPlus2 继续是租户生命周期、用户、组织及外部应用身份的权威，个人内容继续受 owner/显式 grant 保护。
- 定义云端 Skill 的 `global`/`tenant` owner：DeepTutor builtin 是只读 global 来源，云端默认未授权；OMS 授权后 TMS 才能查看，并在 `requires` 满足时使用。TMS 仅通过完整 ZIP 包创建/更新 tenant Skill；受控 Hub 导入须取得并校验包，Skill 名称、说明、标签和依赖等内容元数据从包内 `SKILL.md` 读取，不接受单文件、纯文本或表单覆盖。可信 tenant owner、来源、审核状态及包摘要由平台生成，发布后仅本租户自用。与已授权 global（含 builtin）同名须先提醒并由租户管理员确认，运行时 tenant 优先且不静默回退；Skill 不走成员/应用服务访问 grant 或独立配额。
- 定义应用/client 注册、状态复核、注销及审计：由 EduPlus2 权威解析 client/app/tenant，外部 tenant 必须与当前租户绑定一致，同 provider 的 active client 与同租户同 app 的 active 注册均唯一；TMS 不得代管其他租户或重建 EduPlus2 主数据。
- 区分 OMS 租户级服务授权、TMS 本租户成员/应用的**服务访问权限**与 OMS 租户配额。TMS 可在授权范围内管理访问 grant，但不能增加平台授权、发放额度、预留/划拨额度、设置成员/应用配额上限或修改实际消耗。服务实际可调用还取决于 EduPlus2 状态、资源/应用权限、OMS 授权、配置 readiness、租户额度与平台供给。
- 将“本租户配额清单”固定为与服务列表并列的**只读一级列表**：赠送/充值同一清单按获取方式筛选，详情展示 OMS 授予事实及真实消耗；配额新增、充值、赠送、调整、撤销只在 OMS。未知用量和额度耗尽要准确呈现，不能在 TMS 创建配额写 API 或模拟编辑。
- 定义本租户知识/内容、业务任务、用量和审计的查询/管理范围；TMS 不持有供应商凭据、采购成本、跨租户聚合或平台配置动作。共享 OCR 等业务组件不等于共享 OMS 专有数据与权限。
- **BREAKING（相对旧企业文档）**：TMS 不是 DeepTutor 本地 Web 管理页微调；它独立构建部署。旧“TMS 可以管理/调整配额”的表述不再适用，应用/成员授权仅是访问权限，不是额度管理。

## Capabilities

### New Capabilities

- `enterprise-tms-business-logic`：可信当前租户内的身份/应用归口、资源与服务访问授权、KB/内容管理、只读配额/用量与租户审计契约。

### Modified Capabilities

无。TMS 原型 delta 管交互与演示；本 change 管正式业务规则。既有 EduPlus2、资源存储、授权和会话正式 spec 如实施时受影响，须由后续实施 change 明确补 delta。

## Impact

- 未来实现涉及 `extensions/enterprise/` 的 `/api/v1/tms/*`、共用企业 PG 应用授权迁移、学校主体绑定、学校资源/grant/client/审计、既存 EduPlus2 身份/学校状态复核、KB/文件与用量只读投影，以及 TMS 独立前端；不修改 OMS 的配额写入权威。学校生命周期 Webhook 与学校管理员的本产品授权是不同职责。
- 依赖 B1 可信身份、B2 多租户/资源隔离和 [`add-enterprise-management-authorization`](../add-enterprise-management-authorization/proposal.md) 的本产品权限/双人开通；配额视图依赖 OMS 授予与 DeepTutor 真实用量总账。TMS 不能用 fixture、客户端 tenant 参数或前端隐藏按钮替代真实授权；OMS `ops.*` 角色/学校范围不授予 TMS 能力，也不进入 TMS DTO。既存外部身份/账号/学校接口若缺失，只能由所属团队独立提供，本代理不修改发送端；缺必要核验时正式管理写入口继续关闭。
- 本 change 现在是**正式实施清单**：已获批准后只在 DeepTutor 仓库内推进 `/api/v1/tms/*`、企业 PG 事实、独立 TMS 前端与当前学校安全 DTO；不实施 EduPlus2、OpenFGA、Keycloak 或外部系统变更。任务完成度以 `tasks.md` 与执行证据为准，未勾选任务不得用原型 fixture、手工改库或前端隐藏按钮替代。
