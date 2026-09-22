# enterprise-conversation-test-page Delta

## ADDED Requirements

### Requirement: 普通对话测试页必须通过真实 API/WS 完成长对话

系统 SHALL 提供 local/test 专用的普通对话测试页，用于让非协议开发者完成真实 DeepTutor 对话流程。页面 SHALL 隐藏 JWT、raw WebSocket frame、任意 JSON 编辑器、Secret 和 request id 技术输入，但 MUST 使用真实 EduPlus2 fronting/OIDC 认证、真实 `/api/v1/ws`、真实 session、真实 token refresh 和真实 turn history。页面 SHALL 支持长时间连续对话、恢复当前会话和新建会话。页面与 EduPlus2 fronting demo 页面 MUST NOT 被 Next.js cookie auth gate 先行重定向到 DeepTutor 本地 `/login`；未持有本地 cookie 的普通用户仍必须能看到 EduPlus2 登录入口并启动 `/api/v1/auth/eduplus2/demo/start`。

#### Scenario: 未登录用户进入 EduPlus2 对话测试页
- **WHEN** 用户没有 DeepTutor 本地 cookie 且打开普通对话测试页
- **THEN** Next.js 前端不得把该页面重定向到 `/login`
- **AND** 页面显示 EduPlus2 登录入口，该入口发起 `/api/v1/auth/eduplus2/demo/start` 并在 EduPlus2 登录成功后回到普通对话测试页

#### Scenario: 用户完成普通长对话
- **WHEN** 用户打开普通对话测试页并完成 local/test 登录
- **THEN** 页面创建或恢复一个 DeepTutor session，用户可以连续发送多轮消息并看到上下文连续的 assistant 回复
- **AND** token refresh 在后台完成，页面不把 token 存入 URL、localStorage、sessionStorage 或可见文本

#### Scenario: 用户新建会话
- **WHEN** 用户点击新建对话
- **THEN** 页面开始新的 session，并清除当前 transcript 中的上下文绑定，但不删除服务端历史或泄露 token

### Requirement: 测试页必须流式展示并渲染助手回复

普通对话测试页 SHALL 在 WebSocket `content` 事件到达时即时更新当前 assistant 气泡，而不是等 `done` 事件后一次性展示。assistant 回复 SHALL 支持 Markdown、LaTeX/KaTeX 与 fenced code block 渲染；用户 turn SHALL 保持原文展示，以便普通用户能区分自己输入和系统输出。页面 SHALL 以类似 DeepSeek 网页的可折叠面板展示服务端显式发出的思考/处理过程事件，但 MUST 只展示用户可见轨迹，不展示 raw WS frame、工具参数、Secret、signed URL、ObjectStore key 或未脱敏内部调试字段。思考过程面板 MUST NOT 在最终答案开始流式输出后持续展开并挤走或遮挡正文；页面应默认收起或限制面板高度，使普通用户能看到正文继续流式增长。若模型或 provider 将 `<think>` / `<thinking>` block 混入 assistant `content`，页面 MUST 从最终答案正文中剥离这些 block，并将脱标签后的内容归入“思考过程”面板或安全摘要区域，避免思考标签与思考文本夹在最终答案正文中。

#### Scenario: 助手回复正在流式输出
- **WHEN** WebSocket 持续返回 `content` chunk 且 turn 尚未 `done`
- **THEN** 页面立即把已收到内容追加到当前 assistant 气泡
- **AND** 页面显示普通用户可理解的输出中状态，不暴露 raw frame 或 chunk 技术细节

#### Scenario: 页面展示思考过程
- **WHEN** WebSocket 返回 `thinking`、`progress`、`tool_call` 或 `sources` 事件
- **THEN** 页面在当前 assistant turn 中展示“思考过程”面板，并按到达顺序流式追加“思考中”“正在查找知识库内容”“已找到可参考内容”等用户可理解步骤
- **AND** 思考过程面板不得展示 raw JSON、工具调用参数、token、Secret、signed URL、ObjectStore key、MCP endpoint secret 或完整未脱敏调试 payload

#### Scenario: 正文开始输出后思考面板不再挤走正文
- **WHEN** assistant turn 已收到思考过程事件，随后 WebSocket 开始返回 `content` chunk
- **THEN** 页面继续即时展示正文 chunk
- **AND** 思考过程面板默认收起或限高滚动，不应持续展开到把正文流式输出推离当前可视区域

#### Scenario: 助手正文混入 think block
- **WHEN** assistant `content` 包含 `<think>` 或 `<thinking>` block，且 block 后还有最终答案
- **THEN** 页面不得在最终答案正文中显示 `<think>`、`</think>` 或其思考文本
- **AND** 页面将脱标签后的思考文本展示在“思考过程”面板或安全摘要区域，最终答案仍按 Markdown/LaTeX 渲染

#### Scenario: 助手回复包含公式和代码
- **WHEN** assistant 回复包含 Markdown 强调、LaTeX 公式或 fenced code block
- **THEN** 页面渲染为富文本、KaTeX 公式和可读代码块
- **AND** 不把 `$...$`、代码围栏或 Markdown 控制符当作最终答案裸露给普通用户

#### Scenario: 用户输入保持原文
- **WHEN** 用户 prompt 本身包含 Markdown 或 LaTeX 字符
- **THEN** 页面在用户气泡中按原文展示，不把用户输入渲染成 assistant 富文本答案

### Requirement: 测试页必须支持知识库、skills 和 MCP tools 的 required 选择

普通对话测试页 SHALL 展示当前用户/部署可选择的知识库、skills 和 MCP tools，并在用户选择后通过 WebSocket `start_turn` 提交 `knowledge_bases`、`skills`、`mcp_tools` 与 `context_policy`。页面默认 SHALL 使用 `context_policy: "required"`，以便测试者确认所选上下文必须进入本 turn；页面 MAY 提供自动模式开关，但 MUST 明确说明自动模式不保证调用所选能力。

#### Scenario: 用户选择知识库和 MCP tool 后提问
- **WHEN** 用户在测试页选择一个 ready 知识库、一个 skill 和一个 MCP tool，并发送问题
- **THEN** 页面发送的 `start_turn` payload 包含所选 `knowledge_bases`、`skills`、`mcp_tools` 和 `context_policy: "required"`
- **AND** 若后端返回 required context 错误，页面用用户可读方式说明所选知识库或工具不可用/未授权，并显示脱敏错误 code

#### Scenario: 用户切换自动模式
- **WHEN** 用户将上下文策略切换为自动模式后发送问题
- **THEN** 页面不得承诺后端一定调用已显示或已选择的 KB、skill 或 MCP tool
- **AND** 页面应说明可通过 required 模式验证指定能力是否真正可用

### Requirement: 测试页必须内嵌多模态资源上传到对话流程

普通对话测试页 SHALL 在对话输入区域提供文件选择能力，并执行 DeepTutor resource upload flow：upload intent、pre-signed PUT、complete、`resource_ids` 自动加入下一次或当前 `start_turn`。页面 SHALL NOT 提供独立的 pre-signed upload 技术面板来替代真实对话流程；WebSocket payload MUST NOT 包含 raw binary、任意外部 URL、大 base64、signed upload URL 或调用方自选 ObjectStore key。

#### Scenario: 用户上传图片后发起对话
- **WHEN** 用户在对话输入区域选择图片、等待上传完成并点击发送
- **THEN** 页面先完成 upload intent、pre-signed PUT 和 complete，再在 `start_turn.resource_ids` 中提交 DeepTutor 返回的 `resource_id`
- **AND** 页面不把图片 bytes、signed URL、S3 key 或 base64 放入 WebSocket payload

#### Scenario: 资源上传未完成
- **WHEN** 用户选择文件但 upload intent、PUT 或 complete 尚未成功
- **THEN** 页面阻止发送或明确提示资源尚未完成上传，不生成声称包含资源的 `start_turn`

### Requirement: 测试页必须支持语音输入并安全降级

普通对话测试页 SHALL 支持语音输入到 prompt 文本框。若浏览器提供 MediaRecorder/getUserMedia 且服务端语音转写接口可用，页面 SHALL 录制用户语音并用同一登录态调用服务端 STT 转写；若浏览器提供 Web Speech API 或等价本地能力，页面 MAY 将其作为降级转写方式。若不可用、用户未授权麦克风或转写失败，页面 SHALL 显示可理解的降级提示，并继续允许文字输入和多模态上传。

#### Scenario: 浏览器支持语音输入
- **WHEN** 用户点击语音输入并完成一段语音
- **THEN** 页面把转写文本填入或追加到 prompt，并允许用户编辑后发送

#### Scenario: 使用服务端语音转写
- **WHEN** 普通测试页已登录且浏览器支持录音
- **THEN** 页面用当前 Bearer 登录态调用 `/api/voice/stt` 上传录音片段
- **AND** 转写成功后将文本填入 prompt，转写失败时显示普通用户可理解的原因并保留手动输入能力

#### Scenario: 浏览器不支持语音输入
- **WHEN** 页面检测不到可用语音识别能力或麦克风权限被拒绝
- **THEN** 页面展示降级提示，不阻断文本对话、文件上传或上下文选择

### Requirement: 测试页必须用普通语言展示本轮使用能力

普通对话测试页 SHALL 在每轮回答旁展示“本轮用了什么”面板，面向普通用户说明回答使用了哪些能力。面板 SHALL 使用普通标签和状态，不默认展示协议字段名、raw JSON、request id、event id、MCP tool 原始名称、ObjectStore key 或 WebSocket frame。页面 MAY 提供“排查详情”折叠区，但该区域默认收起且只能展示脱敏 code、短 id 和状态。

#### Scenario: 用户查看本轮使用情况
- **WHEN** 一轮 WebSocket 对话完成
- **THEN** 页面用普通语言展示本轮使用的知识库、学习方法/skills、外部工具/MCP、上传文件、语音输入和模型/对话能力
- **AND** 每项能力显示用户可理解的状态，例如“已用于回答”“已启用但本轮未用”“不可用或未授权”“上传文件已发送给模型”

#### Scenario: 外部工具已启用但未调用
- **WHEN** 后端摘要表明某外部工具已准备好，但本轮没有实际调用
- **THEN** 页面显示“已启用但本轮未用”，不得显示为“已调用”

#### Scenario: 用户展开排查详情
- **WHEN** 用户或测试人员展开排查详情
- **THEN** 页面只显示脱敏错误 code、短 id、状态和时间，不显示 token、Secret、signed URL、ObjectStore key、MCP endpoint secret、完整文档正文或用户隐私
