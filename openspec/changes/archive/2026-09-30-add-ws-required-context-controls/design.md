# 设计说明：WebSocket 强制上下文与普通对话测试页

## 1. 协议模型

`start_turn` 保持现有字段：

- `knowledge_bases: string[]`
- `skills: string[]`
- `tools: string[] | null`
- `resource_ids: string[]`

新增字段：

```json
{
  "mcp_tools": ["lightrag.query"],
  "context_policy": "required"
}
```

`context_policy` 初始枚举：

- `auto` / 缺省：系统只按会话默认、课程默认、部署允许范围、模型判断和 capability 自动挂载运行；不保证指定能力被使用。
- `best_effort`：调用方希望使用指定上下文；服务端应尽量解析和挂载，失败项必须记录到 snapshot/audit，但可以继续执行。
- `required`：调用方要求指定上下文必须可用；服务端必须在模型调用前完成校验和挂载，任一必需项失败则拒绝本 turn。

向后兼容：旧客户端不传 `context_policy` 和 `mcp_tools` 时行为保持现状；`knowledge_bases`、`skills`、`tools` 的已有 payload 结构不改名。

## 2. Required 模式的服务端校验

在创建 turn、持久化用户消息或调用模型前，服务端执行上下文解析：

1. **Knowledge bases**：确认 KB 存在、ready、属于当前 owner/tenant 或显式授权范围，且当前 capability/provider 可以使用。
2. **Skills**：确认 skill id/slug 存在、可读取、当前用户/部署授权，且不会通过本地文件 fallback 绕过企业配置。
3. **MCP tools**：确认 tool name 在服务端登记或用户自有 provider 中可见，复用现有 MCP authorization 规则；不得接受 WS 传入 server URL、secret 或 provider config。
4. **Built-in tools**：若调用方指定 `tools` 且 required，则确认工具存在、已启用、当前 capability 允许挂载。
5. **Resources**：继续使用已有 `resource_ids` 机制；多模态资源按 ObjectStore binding、MIME/size/checksum、owner/session/purpose 和 provider modality 支持校验。

失败策略：

- `required`：返回 stable error 并拒绝本 turn，例如 `required_context_unavailable`、`knowledge_base_unavailable`、`skill_unavailable`、`mcp_tool_unavailable`、`context_authorization_failed`。
- `best_effort`：记录失败项，继续执行可用上下文；响应 metadata 告知调用方哪些项未挂载。
- `auto`：不把未指定能力视为错误；但不得在 UI 或文档中承诺会调用某项能力。

## 3. MCP 边界

MCP 的客户端表达是 **tool name allow/request list**，不是 server 配置。

允许：

```json
"mcp_tools": ["lightrag.query", "resource.search"]
```

禁止：

```json
{
  "mcp_server_url": "https://...",
  "headers": {"Authorization": "..."},
  "command": "node server.js"
}
```

服务端负责把 tool name 解析到已登记 provider，并以当前身份、部署 grant、caller whitelist 和用户自有 provider ownership 计算可见工具集。required 模式下，若解析或授权失败，不进入模型调用。

## 4. 执行路径与可观测性

上下文解析结果应进入统一 turn 环境：

- resolved KB ids / names；
- resolved skill ids；
- resolved MCP tool names；
- required/best_effort/auto policy；
- unavailable context 的脱敏 reason；
- actually used/called context 的脱敏摘要、调用次数和状态；
- resource ids 的脱敏摘要；
- request/session/operation id。

request snapshot/audit/evidence 只记录短 hash、逻辑名、状态、错误 code、调用次数和事件关联，不记录 token、secret、signed URL、MCP endpoint secret、用户完整正文或资源原文。

普通测试页默认不展示这些内部字段。页面应把服务端摘要翻译成用户能理解的“本轮用了什么”：知识库、学习方法、外部工具、上传文件、语音输入和对话模型能力。必要时可以提供“排查详情”折叠区，但默认收起，且只展示脱敏 code、短 id 和状态，不展示 JSON/raw frame。

## 5. 普通对话测试页

新增 local/test 页面，目标用户是普通业务测试者，不是协议开发者。页面不展示 JWT、WS raw frame、request id 编辑框、任意 JSON 编辑器或 Secret。

页面能力：

- 登录态：普通测试页和 EduPlus2 fronting demo 页属于自认证 bootstrap 页面，Next.js cookie auth gate 不应先把它们送到 DeepTutor 本地 `/login`；页面通过 EduPlus2 demo/OIDC start → callback → result/refresh 获得内存态 DeepTutor token，一键进入测试。
- 长对话：默认创建或恢复一个 session；支持新建会话、继续当前会话、清空本页本地状态。
- 流式回答：WebSocket `content` chunk 到达后立即追加到当前 assistant 气泡，pending 状态显示“正在输出”；已到达内容必须持续可见，不等 `done` 事件后才一次性展示；思考过程面板在纯 thinking 阶段可展开，但正文开始输出后默认收起并对长内容限高滚动，避免面板持续增长把正文流式输出挤出可视区域；若 provider 把 `<think>` / `<thinking>` block 混入 `content`，页面在渲染层把这些 block 从最终答案正文剥离，并合并到“思考过程”面板，避免思考文本夹在正文中。
- 富文本展示：assistant 回复按 Markdown 渲染，支持常见段落/列表/强调、 fenced code block 和 LaTeX/KaTeX；用户自己输入的 turn 保持原文展示，避免把用户 prompt 误当模型答案富文本处理。
- 上下文：展示可选知识库、skills、MCP tools；默认提交 `context_policy: "required"`，并提供“自动模式”开关用于对比。
- 多模态：文件选择后执行 upload intent → pre-signed PUT → complete → 自动加入 `resource_ids`；WS 不承载 raw bytes/URL/base64。
- 语音输入：优先使用浏览器 MediaRecorder/getUserMedia 录音并以当前 Bearer 登录态调用 `/api/voice/stt` 转写；若录音/STT 不可用再尝试 Web Speech API；不可用、未授权或转写失败时显示可理解降级说明，不阻断文字输入。
- 错误提示：required context 失败时使用用户语言说明“所选知识库/工具不可用或未授权”，并保留脱敏技术 code 供排查。
- 本轮使用面板：每轮回答后展示“本轮用了什么”，使用普通标签和状态，例如“七年级数学知识库：已用于回答”“分步讲解方法：已启用”“上传图片 1 张：已发送给模型”“外部检索工具：本轮未使用”。不默认显示 `mcp_tools`、`resource_ids`、request id、event id、JSON 或 raw WS frame。
- 恢复：session id、最近 selected context 和未完成上传状态按安全边界保存；token 不进入 localStorage/sessionStorage。

## 6. 上游可合并性

核心改动仅限通用协议字段、验证 hook、provider/tool mounting seam 与 snapshot metadata；企业页面、EduPlus2 local/test 登录、普通测试页和产品化说明放在 enterprise extension 或 enterprise web route 下。不得把 EduPlus2、LightRAG server host、租户规则或测试账号硬编码进 core runtime。
