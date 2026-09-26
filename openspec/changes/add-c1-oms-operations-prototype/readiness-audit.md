# OMS 新目标对 DeepTutor 现状的支撑审计

审计基线：2026-09-26 当前工作树；为静态代码/契约盘点，不是集成、权限、采购、配额或真实浏览器验收。此前 2026-09-25“只读治理 + Token 计费/欠费”的审计结论已被用户新决策取代；其后“OMS/TMS 与 DeepTutor 本地 Web 共用生产构建”的假设也已被独立云端前端决策取代。规范性边界见同目录 `proposal.md`、`design.md` 与 delta spec。

## 可复用事实与缺口

| 新目标 | 当前可复用事实 | 尚缺能力 / 不能误认 |
| --- | --- | --- |
| OMS 云端平台入口 | DeepTutor 本地 Web 中 `web/app/oms/page.tsx` 是未启用规划页；`web/app/oms/prototype/page.tsx` 有开发态演示路由 | 它们不属于独立云端 OMS 应用；现有原型仍是旧只读/计费 IA，卡片堆叠、组件与 fixture 混合；没有真实平台身份、资源管理 API 或新 IA 的可复用界面 |
| OMS/TMS 独立前端与共享组件 | 目前仅有单个 `web/package.json` 构建，`web/app/tms` 是占位页；没有云端 OMS/TMS 两套独立构建或共享管理组件包 | 需要同仓共享基础/服务业务组件，OCR 列表的共用列、搜索、分页、状态和详情交互在 OMS/TMS 实际复用；两个应用各自装配安全 DTO/API/权限，不让 TMS 接收 OMS 成本、Secret、跨租户数据 |
| 平台身份/隔离 | 企业外壳 `extensions/enterprise/src/deeptutor_enterprise/api/application.py` 已只挂核心 `settings.public_router`，未挂完整设置管理 router | 核心 `deeptutor/api/routers/governance.py` 的同名 OMS 路由使用 `tenant_admin` 依赖，不能当平台权限；缺平台管理动作授权、跨租户白名单、目标绑定及默认/自定义角色负例 |
| 云端 DeepTutor 原管理入口关闭 | 企业 API 装配已有不挂载完整设置 router 的先例 | 云端 Web `/settings`、直接核心部署、CLI/SDK 或其他管理路由均需逐项入口审计；仅隐藏菜单或只关闭一个 API 前缀不足以禁止直连；本地 DeepTutor Web 设置仍须保留，非管理公共 UI 与个人偏好需白名单 |
| 全服务 Provider 配置 | SettingsStore、`ConnectionsEditor`、`ServiceConfigEditor`、`TaskModelsEditor` 和后端 descriptor 覆盖八种模型目录服务；解析、视频学习、外部 Agent 有独立设置语义 | 企业运行态目前没有 OMS 全服务配置/Secret/发布闭环；现有企业 PG 模型适配主要覆盖 LLM，不能声称其他执行者已使用 active 版本；字段详情见 `settings-attribute-inventory.md` |
| Agent、工具、知识、运行资源 | `CapabilityRegistry`、`ToolRegistry`、skills/MCP/CLI apps/subagents/partners/personas 路由和 KB/解析、memory、workspace、sandbox、cron 服务均存在 | 它们有平台/租户/个人不同作用域；缺逐类 OMS 资源 descriptor、授权、版本/生效、供应商依赖和用量证据；不能把所有对象当 provider profile 或可计量额度 |
| 供应商服务供给 | 现有 Provider 连接及执行服务可作为资源方案的来源对象 | 没有外部采购批次、可信服务原生单位、供应商有效期、已承诺未使用额度、可授予量或采购/补充对账；金额型供应商余额不能未经契约换算为 Token/次数 |
| 租户服务授权/额度 | PG `runtime_settings/policies` 有 desired/active 状态骨架；TMS/OMS 名称 router 有部分设置/Secret 方法 | 尚无统一“获取方式=充值/赠送”的授予记录、赠送优先、服务调用准入、并发预留、过期/撤销、跨服务隔离或防超额承诺。现有 `mark_active` 直接复制 desired，不能证明执行者已生效 |
| 真实用量与消耗 | 运行时 `UsageTracker` 能读部分 provider usage；`usage_frame.py` 可复用规范化片段 | 当前 turn 摘要含字符估算，不能作为租户额度或服务供给真实消耗；没有带可信 tenant/user/service/provider/model/call ID 的逐调用持久总账、缺失 usage 待核对、原生非 Token 单位或 Agent 子调用防重复；核心 `/api/v1/oms/usage` 是 ObjectStore 汇总，不是服务用量 |
| EduPlus2 租户资格 | PG 身份、external eligibility/local enabled/provisioning 分源底座存在 | 开通/暂停/恢复签名、版本化 webhook 与对账仍需实施；新配额耗尽不可映射为 `tenant.suspended` 或禁用登录。旧独立欠费模型资格方案不再是本目标依赖 |
| 审计与运营状态 | PG 治理审计、EduPlus2 专用审计已有片段 | 缺跨租户授权/额度/采购/配置发布审计、脱敏导出、后端 display descriptor 和工作台异常聚合；任务取消/重试需遵守原执行归口，不能由页面凭空增加 |

## 裁决与实施阻断

1. **当前旧原型不满足新需求。**不得只改视觉样式、卡片顺序或标题后标记完成；需迁入独立云端 OMS 工程并重新实现对象列表→详情、资源覆盖、供给—额度—消耗三本关联事实、演示状态及与 TMS 真正复用的服务组件/数据适配边界。
2. **旧六个实施 proposal 存在目标冲突。**`add-b2-eduplus2-tenant-lifecycle-webhook` 的欠费模型资格、`add-b2-oms-platform-read-governance` 的只读范围、`add-enterprise-all-service-provider-settings` 的独立 DeepTutor 管理页、`add-enterprise-exact-token-usage-ledger` 的仅 Token 计费定位、`add-oms-token-billing-and-arrears` 全部财务逻辑、`add-c1-c2-oms-operator-interface` 的只读/计费页面均须重订。**在重订和分别批准前不得 apply 这些旧 tasks。**
3. **上游可合并性为硬门禁。**新增 OMS/供给/额度/身份逻辑先放企业扩展；若真实 CLI、HTTP/WS、SDK、后台执行需新的通用 seam，先逐处审阅替代方案、上游风险和 smoke 测试，不靠 monkey patch 或核心企业规则。
4. **迁移判断**：本次规划不改 DB、OpenFGA 或 Keycloak。未来实施预计需要版本化 PG 资源/授予/消耗/审计迁移；能力模型/外部身份若实际变化，再按仓库机制做 OpenFGA/Keycloak 迁移和正负例，不手工改库作为最终实现。
5. **验证边界**：先前对旧规划/旧原型运行的 TypeScript、构建、测试和 OpenSpec 校验只证明当时文件可编译、旧示例可交互，不证明新业务语义或真实服务消耗。新原型与实施 proposal 必须重新验证。
