# 云端 OMS 全服务 Provider 设置与执行者确认

> **实施已获批准（2026-09-26）**：本版替换旧“云端 DeepTutor 设置写、OMS 只读”方案，用户已单独批准按现版实施；不得以 artifact 齐备或 strict validation 视为运行实现。平台权限与 OMS attempt 准入未就绪前不开放云端写路由。

## Why
核心 `/settings` 具有多个服务的配置与测试能力，但企业外壳只暴露 public settings，企业 PG 模型适配主要读取 LLM。仅在 OMS 增加 LLM 表单会遗漏其他执行者、复制目录并使 upstream merge 脆弱。

## What Changes
- DeepTutor 保持一套 provider/service catalog/descriptor 语义；企业环境以 PG 不可变配置版本、目标执行者确认和 Secret ref 存储受控发布，不复制第二套服务实现。
- 覆盖连接、LLM、任务模型、embedding、search、TTS、STT、imagegen、videogen，以及文档解析、视频学习和有 provider 依赖的外部 Agent/工具；逐项区分平台、租户、个人范围。
- 云端唯一平台配置写入口为独立 OMS 的获授权 `/api/v1/oms/*`；本地 DeepTutor Web 设置继续可用。企业云端不挂核心完整 settings/governance 管理 router，CLI/SDK/后台不得另行直写。
- 保留草稿、单服务测试、有效模型/档位/能力、连接复用、轮换和失败回退。每个目标执行者实际装载版本后确认；部分确认/超时保持旧 active，新实例装载 active 前不 ready，LightRAG 通过受控服务契约确认，不能把保存或 desired 当生效。
- Secret 明文不入 PG、API 响应、日志、审计或导出；可计费配置测试须通过 OMS 同一服务准入/attempt 契约，不设免配额后门。
- **BREAKING**：旧云端 DeepTutor 平台设置写入口和独立欠费模型资格配置逻辑废止；额度不足只阻对应服务新调用。

## Capabilities
### New Capabilities
- `enterprise-all-service-provider-settings`: 企业 DeepTutor 全服务 provider 维护与实际生效契约。
### Modified Capabilities
无；核心正式 runtime-settings spec 若行为变化，实施前另补 delta。

## Impact
优先影响 `extensions/enterprise/` 的 PG 迁移、Secret/runtime adapter、OMS 管理 API 和独立前端；核心只在实证缺口且经 upstream-neutral seam 审阅后改动，本地 Web 设置回归。依赖 EduPlus2 可信平台身份/动作权限与 OMS 服务供给/attempt 准入；依赖未就绪前不开放云端写路由。外部 SecretStore/LightRAG 仅经受控服务接口，不直连内部 DB/图。
