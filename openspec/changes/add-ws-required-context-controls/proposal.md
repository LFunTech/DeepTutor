# WebSocket 强制上下文与普通对话测试页方案

## Why

DeepTutor 的 `/api/v1/ws` 已经承担真实对话入口，现有 `start_turn` payload 也已有 `knowledge_bases`、`skills`、`tools`、`resource_ids` 等字段。但这些字段的执行语义尚未足够明确：调用方如果不显式指定上下文，系统只能按默认会话、课程、工具挂载和模型自主决策运行，不能保证一定会使用某个知识库、skill 或 MCP 工具；如果调用方显式指定，又必须避免“字段被接收但实际静默忽略”的不可调试状态。

同时，当前 local/test demo 偏技术化，无法让普通业务用户完整测试“登录/进入对话 → 上传图片/音频/视频/文档 → 选择知识库/skills/MCP → 长时间连续对话 → 上下文恢复”的真实体验。M1/G1 已把资源上传边界收敛为 DeepTutor 发行 pre-signed upload URL、WebSocket 只提交 `resource_ids`；下一步需要把知识库、skills 与 MCP 的强制选择也纳入同一 turn contract，避免第三方应用只能靠 prompt 暗示或前端说明猜测后端是否使用了对应能力。

本 proposal 规划 **WebSocket 强制上下文控制** 与一个 **普通用户可用的对话测试页**：在不改变默认自动模式的前提下，为 `start_turn` 增加明确的 required/best-effort 策略和 MCP 一等字段，并让测试页用真实协议验证长对话、知识库、skills、MCP、语音输入和多模态资源引用。

## What Changes

- 新增 OpenSpec 能力 `websocket-turn-required-context`：定义 `/api/v1/ws` `start_turn` 如何显式要求 knowledge bases、skills、MCP tools 与内置 tools 进入本 turn。
- 新增 OpenSpec 能力 `enterprise-conversation-test-page`：定义 local/test 普通对话测试页，隐藏 JWT/WS 技术细节，但用真实 API/WS、真实 session、真实 ObjectStore resource flow 和真实上下文选择完成联调。
- 扩展 `TurnRequest` / WebSocket contract：保留已有 `knowledge_bases`、`skills`、`tools` 字段，新增 `mcp_tools` 与 `context_policy`。
- 明确两种语义：
  - **自动模式**：未指定上下文或 `context_policy` 缺省时，系统只按默认策略暴露可用能力；模型可能调用，也可能不调用；页面/文档不得承诺一定使用。
  - **强制模式**：`context_policy: "required"` 时，指定的 KB、skills、MCP tools、必需内置 tools 必须在模型调用前完成存在性、授权、可用性和挂载校验；任一失败则拒绝本 turn，不得静默降级。
- MCP 只通过受控 tool name 指定，例如 `lightrag.query` 或部署登记的逻辑名；客户端不得通过 WebSocket 提交 MCP server URL、密钥、headers、命令行或任意 provider 配置。
- `start_turn` request snapshot、audit/event metadata 必须记录 requested/resolved/unavailable/used context 的脱敏摘要，方便后端排查“为什么没有调用到某个能力”；普通测试页默认只展示用户能理解的能力使用结果。
- 普通对话测试页支持：一键获取/刷新测试登录态、长对话 session 复用与新建、知识库选择、skills 选择、MCP tools 选择、语音输入、多模态文件上传、`resource_ids` 自动提交、上下文错误可读提示、session 恢复，以及“本轮用了什么”的普通用户友好面板。

## Scope

### In scope

- WebSocket `start_turn` 协议字段与服务端校验语义：`mcp_tools`、`context_policy`，以及已有 `knowledge_bases`、`skills`、`tools` 在 required 模式下的 fail-closed 行为。
- 调用方显式指定上下文时的权限、授权、存在性、ready 状态、provider 支持能力、可审计 metadata 和错误码。
- 默认自动模式的文档化：不指定上下文时不保证调用 KB/skills/MCP，也不得在测试页或接入契约中暗示必然使用。
- 普通对话测试页 local/test 能力：真实 `/api/v1/ws`、真实 session、真实 upload intent/pre-signed PUT/complete、真实 `resource_ids`、知识库/skills/MCP 选择、语音输入、长上下文与恢复。
- Upstream-neutral core seam：核心只增加通用 request contract、validation/mounting hook 与 snapshot 字段；企业页面和 EduPlus2/local-test 入口位于 `extensions/enterprise/` 或 enterprise route/page 下。
- 负例和可观测性：未授权 KB、缺失 skill、MCP tool 不可用、provider 不支持媒体类型、resource 未完成、token refresh 身份不匹配、context required 不满足等场景。
- 普通用户能力使用展示：每轮回答后展示用户可理解的“本轮用了什么”，例如知识库、学习方法/技能、外部工具、上传文件、语音输入、模型/对话能力；默认不展示 raw payload、MCP tool name、request id、event id 或 JSON。

### Out of scope

- 不实现生产级知识库管理 UI、skill marketplace、MCP server 自助配置 UI 或租户治理 UI。
- 不让前端或第三方应用通过 WS 提交 MCP server endpoint、Secret、任意 headers、脚本或 provider 配置。
- 不保证自动模式一定调用某个 KB/skill/MCP；自动模式只能表示系统可按默认策略和模型判断选择使用。
- 不交付完整音频/视频解析或转码系统；测试页只通过既有 ObjectStore resource contract 提交资源，服务端按 provider 支持情况处理或 fail closed。
- 不新增多租户开放、TMS/OMS 或生产 Handoff/OIDC 登录；测试页为 local/test 联调入口。
- 不提交 `.secrets`、JWT、`dt_token`、client secret、模型 key、MCP secret、用户隐私或完整业务正文。

## Capabilities

### New Capabilities

- `websocket-turn-required-context`：WebSocket turn 级 required/best-effort/automatic 上下文选择与校验契约。
- `enterprise-conversation-test-page`：普通用户可用的 local/test 完整对话测试页契约。

### Related Existing Capabilities

- `enterprise-eduplus2-fronting-auth-demo`：已有 local/test 登录、WS 对话、auth refresh 与 resource upload demo；本 proposal 不替代它，而是让普通测试页复用其可用登录/refresh 能力。
- `enterprise-eduplus2-fronting-app-integration`：第三方前置应用接入契约需要引用新增的 WS context 字段与 required 语义。
- `externalized-resource-store` 与 `enterprise-m1-g1-single-tenant-baseline`：资源仍走 pre-signed upload + `resource_ids`，不得回退 WS payload 上传。
- `enterprise-runtime-composition`：显式请求未支持或未授权能力必须在业务写入/模型调用前返回可解释错误，不得静默忽略。

## Delivery Plan

1. **协议冻结**：更新 OpenSpec delta，确认 `context_policy` 枚举、`mcp_tools` 命名、错误码、snapshot/audit 字段与向后兼容策略。
2. **后端 contract 与校验**：扩展 `TurnRequest`、JSON schema/TS contract、WebSocket parser；在 turn 创建前校验 required KB/skills/MCP/tools，失败时返回稳定脱敏错误且不调用模型。
3. **MCP 挂载链路**：把 `mcp_tools` 映射到现有 provider authorization/loading 机制，只允许按 tool name 指定，并复用 `authorize_mcp_tools` 等授权边界。
4. **上下文注入与执行路径**：确保 resolved KB、skills、MCP tools 与资源附件进入真实 `UnifiedContext` / tool registry / provider view；required 模式不得被 capability routing 或模型选择吞掉。
5. **普通对话测试页**：新增 local/test 页面，提供登录态恢复、长对话、知识库/skills/MCP 选择、语音输入、多模态上传、上下文错误展示与 session 管理；页面隐藏 token/WS 技术细节。
6. **测试与 smoke**：补齐 Python contract/validation/provider tests、前端 payload/UI tests、Playwright 或等价浏览器 smoke；覆盖 required 成功、required 失败、best-effort/自动模式、资源上传联动、长对话 session 复用和 auth refresh。
7. **文档与证据**：更新接入文档、demo说明和 execution evidence；运行 `openspec validate add-ws-required-context-controls --strict` 与 `openspec validate --all --strict`。

## Success Criteria

- `/api/v1/ws` `start_turn` 接受 `mcp_tools` 与 `context_policy`，并保持旧客户端在不传新字段时兼容。
- `context_policy: "required"` 时，指定 KB/skills/MCP/tools 未授权、缺失或不可用会在模型调用前 fail closed，返回可定位但脱敏的错误；不会创建“看似成功但没有用上下文”的 turn。
- 不传上下文字段或自动模式时，文档、测试页和接入契约明确说明系统不保证调用 KB/skills/MCP。
- MCP 只能按服务端登记的 tool name 指定；客户端不能通过 WS 注入 server URL、secret 或任意 provider 配置。
- 普通对话测试页可以完成真实长对话：登录/refresh、文件上传、`resource_ids`、KB/skill/MCP required 选择、语音输入、上下文恢复，并用用户可读错误展示 required context 问题。
- request snapshot/audit/evidence 能脱敏记录 requested/resolved/unavailable/used context；普通测试页能以非技术语言展示本轮实际使用的能力，排查详情仅在折叠区域展示。
- 相关 Python/TypeScript tests、前端 typecheck/lint、OpenSpec strict validation 通过；未覆盖的真实外部依赖明确记录为未验证项。
