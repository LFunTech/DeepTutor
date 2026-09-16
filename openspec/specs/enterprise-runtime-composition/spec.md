# enterprise-runtime-composition Specification

## Purpose
> 范围演进：本文记录首切片已验收的历史范围；下文 local 兼容要求已被用户后续确认的[全仓 PG-only 目标](../../../migrate-all-sqlite-state-to-postgresql/specs/postgres-only-runtime/spec.md)取代，后续 change 尚待实施，未来规范收敛须按其 design 处理替代而非同时保留矛盾要求。

规定 DeepTutor 企业身份与会话子切片的组合入口、配置和能力边界，使真实 HTTP、WebSocket 与 SDK 复用同一业务实现，在依赖未交付或配置错误时明确拒绝，而不静默启用本地持久化或被误认为完整生产版本。

## Requirements

### Requirement: 企业装配先于本地副作用

企业入口 MUST 在接收请求及初始化业务服务前完成可信身份、应用持久化、配置和凭证依赖装配；缺失必需依赖或版本不兼容 MUST 拒绝启动。core 与企业实现 SHALL 保持明确依赖边界，不通过运行时全局替换或路由注册顺序覆盖行为。

#### Scenario: 配置缺失或 schema 不兼容
- **WHEN** 企业包缺少必需 provider、固定 tenant、Secret 引用，或应用/core/schema 版本不兼容
- **THEN** 服务不接流量并返回脱敏的配置失败信息，不使用 local admin、SQLite、PocketBase 或文件 fallback

#### Scenario: 导入及启动完整进程
- **WHEN** 从企业入口完成模块加载、启动、认证、文本聊天与停止
- **THEN** 不创建或改写本地账号、签名密钥、settings、memory/notebook、附件或会话权威文件，不自动执行旧文件迁移

### Requirement: 切片入口与依赖显式声明

系统 SHALL 明确声明已支持的认证、文本会话及交互入口；未交付资源、管理页面、插件或能力 MUST 不进入执行路径。显式请求未支持参数或能力 MUST 在业务写入/模型调用前返回可解释的不可用错误，不静默忽略或伪造成功。

#### Scenario: 文本请求携带未交付资源
- **WHEN** 用户请求附件、KB、动态 skill/persona、memory/notebook、学习或未授权工具
- **THEN** 请求明确失败，不读取 local 服务，不创建 turn 后再静默降级为无资源文本回答

#### Scenario: 访问旧管理或其他执行入口
- **WHEN** 用户直调未纳入的原管理 API、Plugin API 或其他 WebSocket 路由
- **THEN** 企业路由清单不提供该能力且不存在回落到原生未适配服务的旁路

### Requirement: 真实聊天使用受控最终配置入口

本切片 SHALL 使用版本化只读部署配置和 Secret 引用供应真实聊天模型及明确授权范围，复用最终通用配置/授权边界。系统 MUST NOT 新建可编辑文件配置权威、硬编码测试账号/模型结果或提供保存后丢失的管理接口；管理员也受模型和工具范围限制。

#### Scenario: 普通用户完成真实文本 turn
- **WHEN** 已认证用户使用其获准模型及文本交互能力
- **THEN** 原聊天执行链调用实际模型并持久化真实事件、消息和用量，不返回固定演示内容；响应和日志无模型密钥

#### Scenario: 用户覆盖模型或尝试保存配置
- **WHEN** 用户提交未授权模型、任意 Secret/endpoint 或未交付的配置写操作
- **THEN** 服务拒绝操作，不扩大部署允许范围、不写本地配置，已有获授权请求不受影响

### Requirement: 入口与独立本地模式兼容

已交付会话 SHALL 保留现有通用 HTTP、`/api/v1/ws` 的协议与事件语义；SDK/企业 CLI SHALL 使用同一授权和持久化边界，不默认实例化未适配的内容服务。独立 local 模式 MUST 保持既有行为，不被企业依赖强制切换。

#### Scenario: 使用 SDK 读取企业会话
- **WHEN** 受信任身份通过企业装配的 SDK 或 CLI 发起/读取会话
- **THEN** 与 HTTP/WS 得到相同权限和 PG 数据，不接受任意 tenant 覆盖、不初始化本地 notebook

#### Scenario: 未安装企业包运行本地模式
- **WHEN** 用户使用现有 local CLI/SDK 配置
- **THEN** 仍可按原本地模式工作，无需企业 PG 或强制修改管理路径

### Requirement: 子切片验收不表示生产发布

本切片 SHALL 仅形成 A1 内部集成证据，M1 完整功能、剩余 A1、A2/A3 与 G1 MUST 继续作为生产前置。组件健康不得冒充完整企业发布就绪，不新增半替换生产版本。

#### Scenario: 本切片全部测试通过
- **WHEN** 身份和 PG 会话均通过验收，但配置/个人内容/S3/RAG/流水线等尚未交付
- **THEN** 只记录本切片完成，A1/G1 保持未通过，不开放普通生产业务流量或勾选总纲的未完成范围
