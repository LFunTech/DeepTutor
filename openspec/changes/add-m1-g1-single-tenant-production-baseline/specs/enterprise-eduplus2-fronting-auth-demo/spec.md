# enterprise-eduplus2-fronting-auth-demo Delta

## ADDED Requirements

### Requirement: Demo 必须体现 ObjectStore 资源预上传与 WebSocket 资源引用边界

Demo SHALL 在 local/test 前置应用页面与 dry-run smoke 中展示 DeepTutor 资源输入的生产边界：资源文件先通过 HTTP 申请 pre-signed upload URL 并直传 S3-compatible ObjectStore；WebSocket `/api/v1/ws` 只提交 `prompt + resource_ids`，不得承载 raw binary、外部 URL、大 base64、signed upload URL 或调用方自选 ObjectStore key。该 demo 表达资源链路契约，不得把 demo-only 页面声明为生产资源治理 UI 或完整多模态能力。

#### Scenario: Demo 页面展示资源引用链路
- **WHEN** 用户打开 `/enterprise/eduplus2/fronting-demo`
- **THEN** 页面展示 pre-signed upload → `prompt + resource_ids` 的资源输入流程，说明上传授权和完成确认走 HTTP/API，WebSocket 对话只发送 DeepTutor 已发行的资源引用

#### Scenario: Demo WebSocket 构造 start_turn
- **WHEN** demo 页面发起 `/api/v1/ws` 对话
- **THEN** `start_turn` payload 使用 `resource_ids` 字段表达已完成上传的资源引用，且 `attachments` 为空；页面不得把 URL、base64、signed upload URL 或 S3 key 放入 WebSocket payload

#### Scenario: Demo smoke 输出资源链路证据
- **WHEN** 运行 EduPlus2 fronting demo dry-run smoke
- **THEN** 输出包含 `resource_upload_reference` 步骤，标记上传通道为 HTTP pre-signed upload、turn 通道为 HTTP/WS `start_turn.resource_ids`，并声明 WebSocket 上传 payload 不被允许
