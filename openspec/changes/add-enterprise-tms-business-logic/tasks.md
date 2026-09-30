> **暂停状态（2026-09-30）**：本 proposal 暂不作为当前 OMS v1 执行主线；已完成项保留为历史证据，未完成项需在后续 TMS/M1/G1/学校集成或发布专项 proposal 中重订后再推进。不得因暂停而视为完成或直接 archive。

> **实施中；任务 1.1、1.2 已完成，证据见 tms-storage-permission-inventory.md 与 tms-permission-test-matrix.md。** 本 change 是正式 TMS 业务逻辑实施清单；当前修订版已获批准。TMS 原型交互仍由 `add-b2-tms-management-prototype` 承担，OMS 配额写入和真实用量由 OMS/DeepTutor 业务 change 承担。当前只负责学校侧成员/应用/资源/tenant Skill/只读投影和独立 TMS 入口；不承担 OMS global Skill 审核发布、Provider Secret 或额度写入。

> **学校侧推进顺序（非勾选项）**：先消费 lifecycle Webhook 的学校—应用有效投影和管理授权 change 的首位 actor 本人激活；再开放当前学校成员/应用/资源/服务访问 grant；随后接 KB/文档、tenant Skill ZIP 和只读额度/用量。TMS 无法通过前端按钮、服务访问 grant、成员角色或 tenant Skill 给学校增加 OMS 服务授权、额度或 Provider Secret。

## 1. A1：租户与资源归属基线

- [x] 1.1 盘点 PG 可信 tenant scope、成员/owner/显式 grant、应用与 KB/文件的现有存储，给出 TMS 所需版本化迁移及回填/权限负例清单；不把旧全局 admin 自动变成租户授权。
- [x] 1.2 建立管理元数据读取、私有正文读取和资源写入的分层权限测试矩阵，覆盖 HTTP/WS/SDK/下载入口与同租户不同 owner。

## 2. A2：知识与内容业务基础

- [ ] 2.1 核实 TMS KB/文档列表与详情所需真实申请、池领取、导入、索引、失败/重试、删除和非托管解绑状态；验证逻辑 ID 重新授权且无任意远端 URL/workspace/密钥。
- [ ] 2.2 验证 LightRAG 引用和派生文件下载再次按 owner/显式 grant 授权，任务取消意图不冒充远端停止或零消耗，不在 TMS 暴露内部 PG/图与实例池操作。

## 3. A3：独立前端与入口基线

- [ ] 3.1 建立 TMS 独立构建/发布/回退契约，检查 DeepTutor 本地 Web 设置仍可用，旧 `/admin`/`/tms` 占位和核心管理 API 不能成为云端权限旁路。
  - [x] 3.1.1 已完成当前独立 TMS 前端本地构建验证：`typecheck:tms` 与 `build:tms` 通过；正式 TMS 使用独立 `apps/tms` 路由和 `/api/v1/tms/*` 安全 DTO，不复用 OMS 专有 API client。
- [ ] 3.2 同步 TMS 原型“使用分配”为服务访问 grant 的文案及跨授予用量示例；验证独立 TMS 应用开发原型可达、生产原型真实 HTTP 404、正式入口在身份/API/权限准备前未启用，并保留窄屏/键盘/错误状态证据。
  - [x] 3.2.1 已在正式 TMS UI 中将成员/应用服务资格实现为“服务访问 grant/revoke”，payload 不含额度数量/余额/上限；`/tms/prototype*` 在非 development 环境服务端 `notFound()`，正式入口在权限/学校码不可信时失败关闭。
- [ ] 3.3 固定 TMS 对外名称“学校智能体管理后台”和 `/tms/{schoolCode}` 的学校路由、列表/抽屉深链/模态框/筛选回退契约；实现独立前端与 Ingress 路由，验证 `/tms` 仅跳转到可信绑定的唯一学校、跨学校 code/资源猜测拒绝、生产原型 404，保留 TMS 与底层 `tenant.*` 技术键。
  - [x] 3.3.1 已固定正式 `/tms/{schoolCode}` 路由与“学校智能体管理后台”显示名称；根 `/tms` 返回 404，前端以 `/api/v1/tms/me/permissions` 的可信 `school_code` 校验 URL code，不一致或缺失时不继续读取当前学校 DTO。

## 4. B1：EduPlus2 身份、租户和应用归口

- [ ] 4.1 对接可信身份绑定的当前 `internal_tenant_id/external_tenant_id` 与 EduPlus2 lifecycle 只读投影；验证任意 URL/body/header tenant 覆盖被拒，未知/延迟状态不伪装 active。
- [ ] 4.2 实施 client/app 注册前 EduPlus2 权威 resolve、租户完全匹配及 active 唯一性，附带 PG 迁移和 403/409/外部失败/并发注册测试；不接收人工名称作为身份凭据。
- [ ] 4.3 实施 client 注销/retire 和历史审计、换 client 流程；验证 token exchange/撤权仍依赖签名 JWT 和真实注册状态，不能凭 TMS 列表自动放行。
- [ ] 4.4 对接 `add-enterprise-management-authorization` 的 Enterprise 应用授权服务、PG 主体/角色/学校范围事实迁移与签名真实 `subscription.created.actor.user_id` 一次性首位引导/本人激活；不要求新增发送端管理员权限 webhook。验证双学校同名账号隔离、学校改码/解绑、身份失效、真实事件与候选本人登录匹配、mock/system/null/重放拒绝、撤权后旧会话失权及身份合同缺失时写入口 fail closed；本仓库 PG dry-run/apply/verify，不修改外部 OpenFGA/Keycloak。
  - [x] 4.4.1 已对接正式 TMS 当前学校权限摘要、安全 bootstrap 状态、成员、审批、审计、Skill、目录和服务访问 DTO；URL/body/header 不能切校，学校码不匹配或缺失时前端失败关闭，后端 `/api/v1/tms/me/permissions` 对缺可信学校码返回 403。

## 5. B2：租户自管理、只读配额和真实用量

- [ ] 5.1 审阅并批准 TMS 的 `tenant.*` 默认/自定义角色、菜单/按钮/API 映射、Enterprise 程序决策与 DeepTutor PG 事实迁移；OMS/TMS 同一授权内核但应用域与 session 隔离，验证普通成员、旧 `tenant_admin`、他人私有内容和跨学校负例；不做外部 OpenFGA/Keycloak 迁移。
- [ ] 5.2 实施当前租户成员、应用、后台主体与资源访问 grant 的授权、撤销和审计；服务访问 grant 绑定 OMS 授权代际且不含数量/余额/上限，验证撤权后及同服务重新授权后旧 grant 均不自动放行。
  - [x] 5.2.1 已实现并接入正式 TMS 当前学校低风险角色授予、assignment 撤权、已批准审批 apply、服务访问 grant/revoke；服务访问 payload 绑定 entitlement version 与 grant version，不写 quota 数量、unit、OMS 成本或 Secret。
- [ ] 5.3 实施本租户 KB/文档及业务任务的真实管理与 owner/grant 检查；验证索引失败、重试、非托管解绑、私有引用下载和取消待确认状态。
- [ ] 5.4 接入 OMS 同一赠送/充值配额列表和 DeepTutor 真实用量的当前租户只读投影；验证筛选、详情、同一 attempt 跨赠送/充值两笔额度但用量只计一次、待核对、耗尽、同步延迟，以及所有配额/用量写请求拒绝。
  - [x] 5.4.1 已接入正式 TMS `/api/v1/tms/quotas` 当前学校只读 DTO，在前端展示 entitlement、quota grant 与 usage/usage_details；TMS 不显示新增、赠送、充值、调整、撤销、核销或成本/Secret 写入口。
- [ ] 5.5 在 TMS 独立前端实现六组对象列表→唯一详情，消费与 OMS 同源的 OCR 服务业务组件；验证列/搜索/分页/状态/导航一致而 TMS API/导出/浏览器载荷无成本、Secret、采购或跨租户字段。
  - [x] 5.5.1 已按原型结构补齐正式 TMS 成员、应用、服务、额度、知识、用量、事件导航与列表→详情抽屉；知识库和应用正式 DTO 尚未启用时显示安全空态，不回退合成成员、应用、知识库或私有正文。
- [ ] 5.6 用真实入口完成当前租户的 client→应用授权→服务调用→用量/配额只读回看和 KB/文档操作验收；保留迁移 dry-run/apply/verify、403/409/异常、审计、回退与 G2 切换证据。
- [ ] 5.7 实施当前 tenant owner Skill 的完整 ZIP 创建/更新与受控 Hub 包导入，以服务端 `SKILL.md` 解析作为全部内容元数据来源并保存不可变包版本；拒绝单文件/纯文本/伪造字段/危险 ZIP，脚本与 `always` 审核前不可执行；审核发布后仅本租户可用。同名已授权 global（含 builtin）提交前由管理员明确确认，tenant 运行时优先，清单/正文/参考文件一致，不可用时不静默回退；验证未授权 builtin 不进 TMS 投影、已授权但 `requires` 不足不可用、后授权/撤销提示、租户隔离、无配额/成员应用二次分配及用户级旧 API 旁路拒绝。

## 6. C1：OMS 平台资源与服务授权协同

- [ ] 6.1 与 OMS 业务 change 固定 service ID、授权版本、配置 readiness 及安全服务 DTO；验证 TMS 不持有平台 Provider/Secret 写动作，OMS 服务撤权及时限制 TMS 应用访问。
- [ ] 6.2 运行 OMS/TMS 两个独立前端对同一 OCR 列表组件的构建、视觉、键盘、交互及版本兼容回归，不允许 TMS import OMS 应用页面。
  - [x] 6.2.1 已完成当前本地前端回归：企业前端全量测试、OMS/TMS typecheck/build 与 lint 均通过；正式 TMS 从自身 app 导入 `TmsFormalApp`，不 import OMS 页面或 OMS 专有 API client。

## 7. C2：配额、用量和治理联动

- [ ] 7.1 与 OMS 总账验证赠送优先、服务供给不足、租户额度不足和待核对状态在 TMS 的只读投影，且额度耗尽仅限制对应服务新调用、不阻断登录/管理/历史。
- [ ] 7.2 核验 TMS 用量、审计、分享/转授权与导出的 tenant/owner/动作权限，覆盖直接用户、委托应用、纯应用、后台及 Agent 子调用；验证成本/采购/Secret/跨租户字段和直接配额写入的后端负例，记录 G3 联合证据。

## 8. H：条件性多实例与兼容发布

- [ ] 8.1 若启用多实例，验证 TMS 会话/租户 scope、grant 撤权、client 状态与 OMS 配额只读版本在跨实例发布/故障切换下保持一致并通过 G-H；单实例明确非 HA 和恢复目标。
