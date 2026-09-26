> **实施已获批准（2026-09-26）**：本清单与 `add-enterprise-oms-business-logic` 的 OMS 独占配置写入契约对齐，旧任务不再执行；用户已单独批准按现版实施，以下仍未完成。可信 EduPlus2 平台权限及 OMS attempt 准入未就绪前不得开放写路由。

## P0 清单与存储迁移
- [ ] 1.1 建立完整设置字段/条件规则→descriptor→真实执行者矩阵，核对 connections/LLM/task/embedding/search/TTS/STT/image/video/解析/RAG/外部 Agent/工具；标作用域、计费测试与未支持原因。
- [ ] 1.2 确认 EduPlus2 平台身份、`ops.*` 动作矩阵及默认/自定义角色迁移；审计云端旧 settings/governance、CLI/SDK/后台旁路与本地设置正例，列最窄 core seam 的 upstream 风险。
- [ ] 1.3 企业扩展 PG 版本化迁移（配置版本、目标确认、Secret ref、审计）和受控旧 JSON 映射 dry-run；合成数据验证 plan/apply/verify、重复运行、drift/失败回退，按实际外部权限来源判定其迁移。
## P1 完整维护闭环
- [ ] 2.1 测试先行：平台 admin/自定义角色正例、operator/auditor/tenant_admin/伪造 header 写入与 Secret 读取负例；草稿、版本冲突、单服务发布、失败回退。
- [ ] 2.2 在独立 OMS `/api/v1/oms/*` 和正式前端实现获授权的配置读写/安全状态；企业云端旧写 API 404、本地 Web 设置继续可用，TMS 仅当前租户安全 DTO。
- [ ] 2.3 接入每个服务真实执行者的配置加载、Secret ref、可用性测试、逐目标实例确认、部分确认/超时保留旧 active、新实例 ready 门禁和回退。
- [ ] 2.4 逐服务验证连接复用、task 回退、embedding 完整 endpoint、search 无模型列表、语音、图像/视频、解析/RAG、外部 Agent/视频学习；可计费测试走 OMS 服务准入/预留/attempt 核对，缺适配不得标记完成。
## P2 验证
- [ ] 3.1 双租户权限/Secret 泄露/旧 active 保留/部分确认与外部服务失败/重试负例、TMS 投影负例及真实执行者读取证据。
- [ ] 3.2 CLI、HTTP/WS、SDK、后台及本地 Web smoke、会话 owner/审计关联、当前 upstream 兼容审阅、OpenSpec strict validation；记录未支持服务清单。
