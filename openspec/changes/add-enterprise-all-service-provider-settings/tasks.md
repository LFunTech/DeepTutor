> **实施中**：配置目标不变，OMS 动作权限归 DeepTutor；EduPlus2 只提供既存身份/在线状态。任务 1.1 descriptor/执行者矩阵、1.3 PG 配置事实迁移与旧 JSON dry-run、2.1/2.2 OMS Provider 设置读写 API 已完成；其余仍未完成，本地应用权限及 OMS attempt 准入未就绪前不得开放写路由。

> **职责边界（非勾选项）**：本 change 只负责“配置是什么、如何草稿/测试/发布、执行者是否装载 active 版本、Secret 如何脱敏”。实际学校能否调用某服务由 OMS 服务授权/额度、逐 attempt 用量与 B1/B2 学校运行时共同决定；正式页面由 OMS 界面 change 装配。配置测试若产生供应商调用，必须走与真实调用相同的学校授权、供给/额度预留和 attempt 记录。

## P0 清单与存储迁移
- [x] 1.1 建立完整设置字段/条件规则→descriptor→真实执行者矩阵，核对 connections/LLM/task/embedding/search/TTS/STT/image/video/解析/RAG/外部 Agent/工具；标作用域、计费测试与未支持原因。
- [ ] 1.2 核实 EduPlus2 既存 OIDC 身份/在线账号状态，确认 DeepTutor OMS `ops.*` 动作矩阵及本仓库默认/自定义应用角色迁移；审计云端旧 settings/governance、CLI/SDK/后台旁路与本地设置正例，列最窄 core seam 的 upstream 风险。
- [x] 1.3 企业扩展 PG 版本化迁移（配置版本、目标确认、Secret ref、审计）和受控旧 JSON 映射 dry-run；合成数据验证 plan/apply/verify、重复运行、drift/失败回退；OMS 应用权限由本仓库 Enterprise 程序按 PG 事实判定，迁移只负责事实存储，不新增发送端 OpenFGA/Keycloak 迁移。
## P1 完整维护闭环
- [x] 2.1 测试先行：平台 admin/自定义角色正例、operator/auditor/tenant_admin/伪造 header 写入与 Secret 读取负例；草稿、版本冲突、单服务发布、失败回退。见 `implementation-evidence.md` §2026-09-28 任务 2.1/2.2。
- [x] 2.2 在独立 OMS `/api/v1/oms/*` 实现获授权的配置读写/安全状态，并固定正式前端所需 DTO/状态契约；企业云端旧写 API 404、本地 Web 设置继续可用，TMS 仅当前租户安全 DTO。当前完成后端正式 API、装配 allowlist 与安全响应；正式前端完整接入仍归界面提案。见 `implementation-evidence.md` §2026-09-28 任务 2.1/2.2。
- [ ] 2.3 接入每个服务真实执行者的配置加载、Secret ref、可用性测试、逐目标实例确认、部分确认/超时保留旧 active、新实例 ready 门禁和回退。
- [ ] 2.4 逐服务验证连接复用、task 回退、embedding 完整 endpoint、search 无模型列表、语音、图像/视频、解析/RAG、外部 Agent/视频学习；可计费测试显式选已核验学校并校验操作人 `school` 范围和测试服务主体 grant，再走该学校 OMS 服务准入/预留/attempt 核对；无学校时不发可计费请求，缺适配不得标记完成。
## P2 验证
- [ ] 3.1 双租户权限/Secret 泄露/旧 active 保留/部分确认与外部服务失败/重试负例、TMS 投影负例及真实执行者读取证据。
- [ ] 3.2 CLI、HTTP/WS、SDK、后台及本地 Web smoke、会话 owner/审计关联、当前 upstream 兼容审阅、OpenSpec strict validation；记录未支持服务清单。
