# 实施任务

范围以 [proposal](proposal.md)、[design](design.md)、`websocket-turn-required-context` 与 `enterprise-conversation-test-page` delta specs 为准。本 change 当前仅创建 proposal，获批后实施；未真实验证前不得勾选任务。

## 1. 协议与 schema

- [x] 1.1 在 `TurnRequest` / JSON schema / TS generated contract 中新增 `mcp_tools: string[]` 与 `context_policy: "auto" | "best_effort" | "required"`，旧客户端不传新字段时保持兼容。
- [x] 1.2 明确 `knowledge_bases`、`skills`、`tools`、`mcp_tools` 在 auto/best_effort/required 三种策略下的语义，并更新接入文档与示例 payload。
- [x] 1.3 定义稳定错误码和 WS/turn failure 表达：`required_context_unavailable`、`knowledge_base_unavailable`、`skill_unavailable`、`mcp_tool_unavailable`、`context_authorization_failed` 等。

## 2. 后端校验与挂载

- [x] 2.1 在 turn 创建/模型调用前实现 required context resolver，校验 KB 存在/ready/授权、skills 存在/授权、内置 tools 可挂载、MCP tools 已登记且授权。
- [x] 2.2 将 `mcp_tools` 映射到现有 provider authorization/loading 链路，复用 MCP tool name 授权；禁止 WS 传入 server URL、secret、headers、命令行或任意 provider config。
- [x] 2.3 确保 resolved KB/skills/MCP/tools 与资源附件进入真实 `UnifiedContext`、tool registry/provider view/capability 执行路径，required 项不得被 capability routing 或默认策略吞掉。
- [x] 2.4 在 request snapshot/audit/event metadata 中记录 requested/resolved/unavailable/used context 的脱敏摘要，不记录 token、Secret、signed URL、MCP secret 或用户私密正文。
- [x] 2.5 汇总本轮实际使用能力，供普通测试页展示为非技术化文案；服务端仍保留脱敏排查字段，但默认 UI 不展示 raw JSON/WS frame。

## 3. 普通对话测试页

- [x] 3.1 新增 local/test 普通对话测试页，隐藏 JWT/WS raw 技术参数，提供一键登录/refresh、会话新建/恢复、长对话 transcript 与用户可读错误。
- [x] 3.2 页面提供知识库、skills、MCP tools 选择；默认 `context_policy: "required"`，并允许切到自动模式用于对比“不保证调用”。
- [x] 3.3 页面内置多模态资源上传：文件选择 → upload intent → pre-signed PUT → complete → 自动提交 `resource_ids`；不提供独立的 pre-signed upload 技术面板替代真实对话流程。
- [x] 3.4 页面支持语音输入；浏览器不支持 Web Speech API 时提供降级提示且不影响文本输入和对话。
- [x] 3.5 页面按 turn 展示普通用户友好的“本轮用了什么”面板，覆盖知识库、学习方法/skills、外部工具/MCP、上传文件、语音输入和模型/对话能力；技术详情默认收起且脱敏。
- [x] 3.6 页面流式渲染 assistant 回复，支持 Markdown、LaTeX/KaTeX 与 fenced code block；用户 turn 保持原文展示。
- [x] 3.7 页面展示类似 DeepSeek 的“思考过程”面板，流式汇总 `thinking`/`progress`/`tool_call`/`sources` 用户可见轨迹，并避免 raw JSON/工具参数/Secret 泄露。

## 4. 权限、安全与负例

- [ ] 4.1 覆盖未授权 KB、私有 KB、缺失 KB、未 ready KB、缺失 skill、未授权 skill、MCP tool 不存在、MCP tool 未授权、provider 不支持媒体类型等 fail-closed 场景。
- [x] 4.2 覆盖自动模式和 best-effort 模式，确认不可用上下文不会被描述为已强制使用。
- [x] 4.3 覆盖 token refresh 身份不匹配、跨 owner/session `resource_ids`、未完成资源上传、raw URL/base64/binary WS payload 等已有资源边界负例。

## 5. 测试与验证

- [x] 5.1 增加 Python contract/validation/provider tests，证明 required context 在模型调用前失败或成功挂载。
- [x] 5.2 增加前端 unit tests，覆盖普通测试页 payload 构造、session 复用、KB/skill/MCP 选择、资源上传、语音降级、普通用户能力使用面板和错误展示。
- [x] 5.3 增加浏览器 smoke 或 Playwright 验证，完成真实登录/WS 长对话/资源上传/required context 选择链路。
- [x] 5.4 运行 `ruff`/Python targeted tests、前端 typecheck/lint/unit tests、`openspec validate add-ws-required-context-controls --strict` 和 `openspec validate --all --strict`。
- [x] 5.5 更新 execution evidence，记录命令、退出码、脱敏 request/session/context 摘要、未验证项和后续风险。
