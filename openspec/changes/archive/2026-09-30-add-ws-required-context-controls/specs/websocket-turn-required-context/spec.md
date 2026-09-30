# websocket-turn-required-context Delta

## ADDED Requirements

### Requirement: WebSocket start_turn 必须支持显式上下文策略

系统 SHALL 在 `/api/v1/ws` `start_turn` contract 中支持 `context_policy` 字段，用于声明调用方对知识库、skills、内置 tools 和 MCP tools 的使用要求。`context_policy` 缺省或为 `auto` 时，系统 MAY 按会话默认、课程默认、部署策略、capability 自动挂载和模型自主判断使用可见能力，但 MUST NOT 保证会调用任何未显式 required 的知识库、skill 或 MCP tool。`context_policy` 为 `required` 时，系统 MUST 在模型调用前验证并挂载调用方指定的上下文；任一 required 项不可用、未授权或不支持时 MUST fail closed。

#### Scenario: 调用方不指定上下文
- **WHEN** WebSocket client 发送 `start_turn`，且未传 `knowledge_bases`、`skills`、`mcp_tools` 或 `context_policy`
- **THEN** 系统按默认策略运行，不把任何特定 KB、skill 或 MCP tool 视为必用项
- **AND** 文档、测试页和审计不得声称本 turn 一定调用了某个未指定能力

#### Scenario: 调用方要求强制上下文
- **WHEN** WebSocket client 发送 `start_turn` 并设置 `context_policy: "required"`，同时指定 `knowledge_bases`、`skills` 或 `mcp_tools`
- **THEN** 系统在持久化最终 turn 执行状态或调用模型前校验这些上下文存在、ready、授权且可挂载
- **AND** 校验通过后，本 turn 的执行环境包含这些 resolved context

#### Scenario: Required 上下文不可用
- **WHEN** required KB、skill、MCP tool 或内置 tool 不存在、未 ready、未授权、被 deployment policy 禁用或当前 provider/capability 不支持
- **THEN** 系统拒绝该 `start_turn` 或将 turn 标记为 rejected/failed，并返回稳定脱敏错误
- **AND** 系统不得静默降级为无上下文文本回答，不得继续调用模型

### Requirement: MCP tools 必须按服务端登记的 tool name 指定

系统 SHALL 允许 WebSocket client 通过 `mcp_tools: string[]` 指定本 turn 希望或必须使用的 MCP tools。`mcp_tools` 的元素 MUST 是服务端已登记或当前用户自有 provider 暴露的逻辑 tool name；系统 MUST 复用 MCP 授权规则校验当前身份、deployment grant、caller whitelist 和 ownership。系统 SHALL NOT 接受客户端通过 WebSocket 提交 MCP server URL、Secret、headers、命令行、代码或任意 provider 配置。

#### Scenario: 指定已授权 MCP tool
- **WHEN** client 发送 `mcp_tools: ["lightrag.query"]` 且该 tool 对当前身份可见并授权
- **THEN** 系统将该 MCP tool 纳入本 turn 的 provider/tool view，并在 snapshot/audit 中记录脱敏 resolved tool name

#### Scenario: 指定未授权 MCP tool
- **WHEN** client 发送 `context_policy: "required"` 和未授权或不存在的 `mcp_tools`
- **THEN** 系统返回 `mcp_tool_unavailable` 或 `context_authorization_failed` 等稳定错误，并在模型调用前停止

#### Scenario: Client 尝试注入 MCP server 配置
- **WHEN** client 在 WebSocket payload 中提交 MCP endpoint、headers、Secret、命令行、脚本或 provider config
- **THEN** 系统拒绝或忽略这些字段并返回脱敏错误，不创建外部连接、不记录 Secret、不扩大授权范围

### Requirement: Required context 结果必须可审计且脱敏

系统 SHALL 在 request snapshot、turn metadata、audit 或 execution evidence 中记录本 turn 的 context policy、requested context、resolved context 和 unavailable context 的脱敏摘要。记录 MUST 足以排查“为什么没有调用到某个知识库、skill 或 MCP tool”，但 MUST NOT 泄露 token、Secret、signed URL、MCP credentials、用户私密正文或资源原文。

#### Scenario: Required context 成功解析
- **WHEN** required KB、skills 和 MCP tools 均通过校验并挂载
- **THEN** snapshot/audit 记录 context policy、资源逻辑名或短 hash、resolved 状态和 request/session/operation 关联信息

#### Scenario: Best-effort context 部分失败
- **WHEN** `context_policy: "best_effort"` 且部分 KB、skill 或 MCP tool 不可用
- **THEN** 系统 MAY 继续执行可用上下文，但 MUST 在 metadata 中记录 unavailable 项和脱敏 reason
- **AND** 响应或测试页不得把失败项展示为已使用

### Requirement: Turn 必须提供可面向用户解释的能力使用摘要

系统 SHALL 为每个 WebSocket turn 生成脱敏的能力使用摘要，使客户端能够区分调用方要求的上下文、服务端已准备的上下文，以及本轮回答实际使用或调用的能力。该摘要 SHOULD 覆盖 capability、模型 profile、knowledge bases、skills、内置 tools、MCP tools、resources 和语音/多模态输入状态。摘要 MUST 同时支持普通用户展示和脱敏排查；普通用户展示不得暴露 raw protocol 字段、JSON、WS frame、token、Secret、signed URL、MCP credentials、用户私密正文或资源原文。

#### Scenario: 能力已准备但本轮未调用
- **WHEN** required MCP tool、skill 或知识库已通过授权并进入本 turn 执行环境，但本轮回答没有实际调用它
- **THEN** 摘要区分“已准备/已启用”和“未实际调用”
- **AND** 客户端不得把它展示为“已用于回答”

#### Scenario: 能力实际用于回答
- **WHEN** 本轮执行期间发生 tool call、RAG/KB 查询、skill 读取/加载、MCP tool 调用或资源传递给模型
- **THEN** 摘要记录对应能力的安全显示名称、类型、状态和调用次数或使用状态
- **AND** 排查字段只包含脱敏 code、短 id 或事件关联，不包含敏感内容
