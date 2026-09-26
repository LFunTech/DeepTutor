## Purpose
DeepTutor 企业环境复用核心设置语义，由独立 OMS 安全管理全部 provider 依赖服务的云端配置；本地设置保持可用。

## ADDED Requirements
### Requirement: Provider 设置必须覆盖全部既有服务
系统 SHALL 以现有 descriptor/真实执行者为单一语义源，为 connections、LLM、task、embedding、search、TTS、STT、imagegen、videogen 及现有 provider 依赖解析/RAG、外部 Agent、视频学习服务提供可配置、可测试、可发布并被实际执行者读取的路径。缺适配的服务 MUST 标为 `unsupported` 并说明原因；非 provider 的个人偏好不得被当作平台凭据。
#### Scenario: 非 LLM 服务发布
- **WHEN** 平台管理员发布 embedding 或 STT 配置
- **THEN** 对应真实执行者确认 active 后，新请求使用该版本
- **AND** LLM 配置及其他未提交草稿不被一起应用

### Requirement: 配置必须版本化并在失败时保持旧 active
系统 SHALL 使用不可变版本分离 draft/desired 与 active，固定目标执行者并逐实例记录真实装载确认，提供版本冲突与后端状态 descriptor；部分确认/超时 MUST 保持旧 active、未确认实例不接新流量，新实例装载 active 前不可 ready；保存成功 MUST NOT 被描述为生效。
#### Scenario: 远端执行者未确认
- **WHEN** LightRAG 或后台 worker 尚未确认新版本
- **THEN** 页面显示待生效，旧 active 继续有效或服务 fail closed，不虚报完成

### Requirement: 云端平台配置只经 OMS 授权写入且凭据最小化
系统 SHALL 仅保存 Secret ref，云端平台设置写入只经独立 OMS API 的 EduPlus2 平台主体及 `ops.providers.manage`/`ops.credentials.manage` 具体动作授权；企业 app 不挂核心完整 settings/governance 管理 router，CLI/SDK/后台不能形成第二写入口。本地 DeepTutor Web 设置 SHALL 保持可用。OMS/TMS/用户 API、日志、审计与导出均不返回 Secret 明文。
#### Scenario: operator 尝试修改 key
- **WHEN** 无写能力的 operator 或携带伪造 `ops.*` header 的 tenant_admin 调用旧 settings 或 OMS provider 写 API
- **THEN** 系统拒绝并记录脱敏审计

#### Scenario: 可计费配置测试
- **WHEN** 获授权人员发起会触发供应商请求的配置测试
- **THEN** 测试经过同一服务授权、供给、额度预留与 attempt 核对，不能免配额发出

### Requirement: 租户配置不得扩大平台提供的服务集合
系统 SHALL 分离平台目录、租户允许范围和个人选择，后两者只能收窄；跨租户不能读取对方配置或凭据。
#### Scenario: 租户选择未分配 provider
- **WHEN** tenant_admin 或普通用户请求未分配模型
- **THEN** 运行时拒绝，不能靠请求字段覆盖目录

### Requirement: 单服务额度不足不得阻断其他管理功能
系统 SHALL 保持获授权的配置查询、管理历史与其他服务操作可用；额度不足只拒对应服务的新供应商请求，包括可计费配置测试。`active` 配置状态 MUST NOT 被解释为租户已获授权或有可用额度。

#### Scenario: 单服务额度耗尽
- **WHEN** 某租户的图像服务额度耗尽但仍可访问管理与其他服务
- **THEN** 图像服务的新可计费测试被明确拒绝，登录、管理历史与其他服务不受影响
