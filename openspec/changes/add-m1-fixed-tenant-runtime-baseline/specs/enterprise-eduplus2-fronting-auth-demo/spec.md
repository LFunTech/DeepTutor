# enterprise-eduplus2-fronting-auth-demo Delta

## ADDED Requirements

### Requirement: Demo 必须体现 ObjectStore 资源预上传与 WebSocket 资源引用边界

Demo SHALL 在 local/test 前置应用页面与 dry-run smoke 中展示 DeepTutor 资源输入的生产边界：资源文件先通过 HTTP 申请 pre-signed upload URL 并直传 S3-compatible ObjectStore；WebSocket `/api/v1/ws` 只提交 `prompt + resource_ids`，不得承载 raw binary、外部 URL、大 base64、signed upload URL 或调用方自选 ObjectStore key。页面 SHALL 在“真实 `/api/v1/ws` 对话测试”区域内提供可执行的 local/test 资源预上传 happy path：文件选择、SHA-256 计算、upload intent 申请、pre-signed PUT、upload complete、`resource_id` 自动填充到 WebSocket 输入区；不得用独立 pre-signed upload 说明板块代替对话测试中的完整流程。该 demo 表达资源链路契约，不得把 demo-only 页面声明为生产资源治理 UI、目标 ObjectStore 验收或完整多模态能力。

#### Scenario: Demo 页面展示资源引用链路
- **WHEN** 用户打开 `/enterprise/eduplus2/fronting-demo`
- **THEN** 页面在“真实 `/api/v1/ws` 对话测试”区域展示资源上传入口、上传状态和已完成上传的 `resource_ids`
- **AND** 页面不再提供独立的 pre-signed upload 资源说明板块

#### Scenario: Demo 页面执行资源预上传
- **WHEN** demo 页面已获得 `dt_token`，用户选择图片、音频、视频或文档文件并点击上传
- **THEN** 页面使用 `dt_token` 调用 `/api/v1/resources/upload-intents`，请求体只包含 MIME、大小、SHA-256、purpose、filename 等 metadata，不包含 raw bytes、base64、外部 URL 或 ObjectStore key
- **AND** 页面使用返回的 pre-signed upload URL 和 policy headers 执行 HTTP `PUT`，随后调用 `/api/v1/resources/upload-intents/{resource_id}/complete`
- **AND** 完成后页面把 DeepTutor 返回的 `resource_id` 自动加入 WebSocket 对话的资源引用输入区，并展示脱敏状态摘要

#### Scenario: Demo WebSocket 构造 start_turn
- **WHEN** demo 页面发起 `/api/v1/ws` 对话
- **THEN** `start_turn` payload 使用 `resource_ids` 字段表达已完成上传的资源引用，且 `attachments` 为空；页面不得把 URL、base64、signed upload URL 或 S3 key 放入 WebSocket payload

#### Scenario: Demo smoke 输出资源链路证据
- **WHEN** 运行 EduPlus2 fronting demo dry-run smoke
- **THEN** 输出包含 `resource_upload_reference` 步骤，标记上传通道为 HTTP pre-signed upload、turn 通道为 HTTP/WS `start_turn.resource_ids`，并声明 WebSocket 上传 payload 不被允许
