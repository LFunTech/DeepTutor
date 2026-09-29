> 2026-09-27 用户确认 EduPlus2 身份/学校/生命周期与 DeepTutor OMS 应用权限拆分，且本代理不得修改 EduPlus2；本 change 权限权威修订版及直接依赖提案随后已分别获批。内部总账实施授权和隔离合成数据限制保持。真实租户数据、生产发布、归档、此次提交/推送均未授权；test-cn Webhook mock 联调不改变 OMS 写入门禁。只在各项证据真实完成后勾选，实施证据见 `implementation-evidence.md`。

> **首个 Agent 的 test-cn 交付优先顺序**：用户指定正式 OMS 维护模型/global Skill，由指定测试学校的受控服务主体先联调，不开放学校用户入口。按 `design.md` 的“test-cn 首个 Agent”切片，优先贯通管理授权 1.2/2.1/3.2、Provider 设置 1.1–2.4、OMS 6.2–6.5/7.3–7.5、独立 OMS 界面 1.1/1.2/3.1 与 B1/B2 的学校运行时门禁；旧原型 fixture、核心本地设置和手工改库均不能替代。此交付顺序不勾选未完成任务，也不豁免后续完整 OMS/Provider/Skill 的全服务验收。**职责拆分**：本 change 只定义/实现 OMS 后端业务闭环；正式 OMS 前端归 `add-c1-c2-oms-operator-interface`，TMS tenant Skill 和学校成员/应用归 `add-enterprise-tms-business-logic`，统一鉴权归 `add-enterprise-management-authorization`。

> **跨 proposal 切片（非勾选项）**：先以 `add-enterprise-management-authorization` 的 OMS 会话/PEP/动作目录作为所有写 API 门禁；再完成 `add-enterprise-all-service-provider-settings` 的真实执行者加载与可计费测试准入；随后本 change 完成 global/builtin Skill 审核发布/学校授权、OMS 服务授权/额度和执行前预留；`add-enterprise-exact-token-usage-ledger` 负责逐 attempt 对账/更正；`add-c1-c2-oms-operator-interface` 只在上述真实 API 可用后接正式界面。任何单项提前完成都不能替代 7.7 的端到端验收。

## 1. A1：状态与迁移基线

- [x] 1.1 审核 DeepTutor PG 身份、租户 scope、配置版本、资源 owner 与现有总账字段，提交 OMS 供给/授予/预留/用量/审计的版本化迁移清单及缺口证据；不直接改核心表或真实数据。见 `implementation-evidence.md` §1.1；这是清单/缺口审计，不是迁移已实施。
- [x] 1.2 为服务 ID、供应商批次/兼容池、原生单位、`operation_id/attempt_id` 制定持久化/索引/事务契约，验证批次历史消耗、当前承诺、在途预留不重复扣除及多次可计费重试的并发/幂等测试设计。见 `implementation-evidence.md` §1.2 与隔离 PG `test_oms_ledger_migration.py`；这是 schema/事务契约与基础并发/幂等测试，不是供给/授予/预留/结算服务已实现。

## 2. A2：检索与非 Token 服务边界

- [x] 2.1 逐项核实解析/OCR、LightRAG、搜索、语音、图像、视频及工具的真实执行者、单位和 usage 来源；记录哪些服务只能计调用次数、哪些缺上界不可硬授予，并提供失败/取消负例。见 `implementation-evidence.md` §2.1；仅为源码/契约审计，后续逐服务真实结算验收仍在 7.4/7.5。
- [x] 2.2 核对 LightRAG 受控 API、任务/索引/远端状态与 OMS 仅看平台元数据的边界，验证不直连内部 PG/图、不读取租户正文，列出待对账状态。见 `implementation-evidence.md` §2.2；这是现状/边界核对，不是托管任务、索引对账或 OMS 平台状态 API 已实现。

## 3. A3：单租户生产与上游兼容门禁

- [x] 3.1 审计本地 Web 设置和云端企业装配的所有管理入口（含 API、CLI/SDK），形成云端阻断/个人接口白名单与本地设置保留的路由级负例和回退证据。见 `implementation-evidence.md` §3.1；这是当前未开放 OMS 写路由的入口基线，未来正式 OMS API 装配仍须重新验收。
- [ ] 3.2 对每处确实缺少的 DeepTutor 通用 seam 提交替代方案、拟改入口、上游合并风险及 CLI/HTTP/WS/SDK/后台 smoke；仅经严格审阅后实施，并留当前 upstream 兼容证据。

## 4. B1：EduPlus2 生命周期与可信主体

- [x] 4.1 与重订的 EduPlus2 lifecycle change 对齐签名事件、分源状态、同步异常及对账投影；验证 OMS 无开停写入、额度耗尽不产生 `tenant.suspended`，登录/管理未受额度误阻断。见 `implementation-evidence.md` §4.1；这是权威边界/负例验收，不表示 4.2 的真实平台身份或跨学校写入已开放。
- [ ] 4.2 核实 EduPlus2 **既存**且适用 OMS 的 OIDC client/audience、账号在线状态和学校权威核验接口；依赖 `add-enterprise-management-authorization` 的 DeepTutor Enterprise 程序授权服务与 PG 唯一双应用域事实迁移完成 `(issuer,sub)` 平台主体、默认零权、受控初始管理员、默认/自定义角色与逐 `ops.*` 动作/目标学校授权、撤权版本和审计；不在本 change 复制权限表。建立内部 UUID↔权威学校 ID 的显式核验/撤权/版本栅栏；在账务事务内复核本地权限及绑定，验证伪造平台角色、目标 tenant、停用账号、撤权竞态、漂移绑定和旧 `tenant_admin` OMS 路由均不能写入。现有外部接口缺失时保持写路由关闭，不修改 EduPlus2。

## 5. B2：租户权益与 TMS 只读契约

- [x] 5.1 与 TMS 业务 change 固定 service/grant/quota/usage 安全 DTO、版本/时效、当前租户绑定及只读配额 API；验证 TMS 无配额写路由、成本/Secret/跨租户字段不可达。见 `implementation-evidence.md` §2026-09-28 TMS 当前学校配额只读投影；该 API 仅为当前学校安全投影，不含 TMS 前端、筛选/详情完整交互或真实执行结算验收。
- [x] 5.2 设计服务授权与额度授予的动作权限、有效期/撤销及同步状态；验证 TMS 成员/应用访问 grant 不生成配额授予、预留或实际消耗。见 `implementation-evidence.md` §2026-09-28 TMS 服务访问 grant 与额度隔离；当前完成应用层账本/迁移和合成验证，正式 TMS API/前端入口仍属 TMS 业务 change。

## 6. C1：平台资源与配置管理

- [x] 6.1 按新权威边界重新审阅 `add-enterprise-management-authorization`、`add-b2-oms-platform-read-governance` 和 `add-enterprise-all-service-provider-settings`：OMS 平台动作与目标学校授权由 DeepTutor Enterprise 程序判定、仅将事实迁移到本仓库企业 PG，EduPlus2 仅消费既存身份/学校接口，不代做其 OpenFGA/Keycloak 迁移；同时保持 Secret/导出边界、Provider 全服务入口。三份当前修订版已分别获用户批准，旧版批准不作新合同证据；审阅与 strict validation 见 `implementation-evidence.md` §6.1。此项只完成依赖契约复核，不等于外部接口或正式写 API 验收。
- [x] 6.2 建立五类平台资源与现有 DeepTutor descriptor/registry 的映射和安全状态 API；逐项验证 search、task 回退、embedding、TTS/STT、image/video、解析/RAG、外部 Agent/工具的条件字段与本地 Web 语义一致。见 `implementation-evidence.md` §2026-09-28 OMS 平台资源安全状态 API；该 API 只返回脱敏 descriptor/status，不执行探针、不保存配置、不替代 6.3 发布确认。
- [x] 6.3 实施并验证受控配置草稿、测试、目标执行者逐实例版本确认、部分确认/超时失败保留旧 active、新实例就绪前装载及回退；Secret 明文不进入响应、日志或审计，云端旧管理旁路被阻断。见 `implementation-evidence.md` §2026-09-28 任务 6.3。
- [ ] 6.4 同步 OMS 原型中供给/调用扣量的简化文案与 fixture，再将独立 OMS 前端接入真实平台身份和资源管理 API；按列表→详情检查普通运营/高权限角色、加载/空/错误/无权限/待生效、审计关联与生产原型 404。
- [ ] 6.5 与 TMS 业务 change 实施云端 Skill `global`/`tenant` owner 和安全来源模型：**本 change 负责 OMS global/builtin 包登记、审核、发布、学校授权及运行时过滤规则**；TMS change 负责 tenant ZIP 创建/更新与本校自用。非 builtin 创建/更新只接收完整 ZIP，服务端校验包并以 `SKILL.md` 作为全部内容元数据来源，保存不可变版本/摘要且审查前不运行脚本或 `always`；builtin 不可编辑、默认零租户授权并按打包版本复核；验证无需 TMS 二次分配、未授权 builtin 在清单/`read_skill`/显式请求/`always` 各入口不可达、依赖不足不可用、同名 tenant 优先且本地 DeepTutor 行为不变。

## 7. C2：供给、配额、真实消耗与治理

- [x] 7.1 重订旧逐 Token usage change 并退役旧费用/欠费 change；批准供给、赠送/充值、非 Token 原生单位、待核对、OMS-only 成本的唯一总账和版本化 PG 迁移，不迁入旧租户售价/欠费字段。见 `implementation-evidence.md` §7.1；完成的是获批的目标契约和基础迁移门禁，不是 7.2–7.6 的供给管理、真实执行/核对或成本视图。
- [x] 7.2 实施供应商供给批次/兼容池与可授予量事务校验；验证供给过期仍保留历史消耗、授予不晚于供给有效期、金额/credits/paygo 无可信上界时拒绝硬额度及新调用，并以并发测试证明不超额承诺。见 `implementation-evidence.md` §7.2；完成内部总账事务与合成验证，不代表平台采购写 API、供应商凭据核验或真实执行者已开放。
- [x] 7.3 实施 OMS 租户服务授权及同一列表的赠送/充值额度授予、调整、过期/撤销；验证操作审计、版本冲突、赠送优先与未使用承诺释放。见 `implementation-evidence.md` §2026-09-28 OMS 服务授权与额度 API；完成的是经 DeepTutor 本产品 school-scope 授权的合成 PG API/总账闭环，不代表真实执行边界或供应商调用已开放。
- [ ] 7.4 在真实 CLI、HTTP/WS、SDK、后台和 Agent 子调用执行边界接入授权/额度/供给准入与预留；验证单服务耗尽只拒该服务新调用，登录/管理/历史与其他服务可用。
- [ ] 7.5 以供应商可信 usage/可核验对账结算 Token，以真实原生单位结算其他服务；验证流中断、异步任务、同一 operation 多个可计费 attempt、重复回执、迟到响应、取消未知结果、一次 attempt 跨多笔额度及 Agent 防双扣。
- [ ] 7.6 实施保留原始证据的核对/更正与 OMS-only 供应商成本视图；验证无成本契约时未核定、不生成租户费用，并检查权限、导出、日志及 TMS DTO 负例。
- [ ] 7.7 以独立 OMS 正式入口验收采购补充→租户授权/额度→单次执行→租户/用户/供应商归集→异常核对全链路；验收既存 EduPlus2 身份/学校接口与 DeepTutor 本地 OMS 逐动作/目标授权、外部账号停用和本地撤权竞态负例；保留本仓库迁移 dry-run/apply/verify、回退、审计、上游兼容与 G3 发布证据。不得以外部发送端草稿或合成 JWT 代替真实联调。

## 8. H：条件性多执行者与高可用

- [x] 8.1 若启用多实例，先验证跨实例准入/预留/结算的事务一致性、配置版本传播、取消/重试幂等和故障后待核对恢复，并通过 G-H；单实例则明确非 HA、容量与恢复目标。见 `implementation-evidence.md` §2026-09-28 单实例运行边界；当前仅确认非 HA 单 backend，未启用多实例。
