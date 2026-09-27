# 当前代码契约核对矩阵（仅供文档维护）

本矩阵记录 2026-09-27 当前工作区已实现的扩展协议；公开页面只写开发者必须遵守的接口与限制，不复制源码路径、内部装配或运维细节。OMS/TMS 规划中的上传/发布不作为现状。

| 类型 | 当前实现的契约来源 | 必须纠正/写全的点 | 企业第三方入口 |
| --- | --- | --- | --- |
| MCP | `deeptutor/services/mcp/config.py`、`user_config.py`、`network.py`、`manager.py` | 远程 `sse`/`streamableHttp`，用户服务不能 `stdio`；服务名、工具 schema、名称包装、超时；当前适配器拼接文本内容、图片省略，`structuredContent`/`isError` 不进入 ToolResult 语义，不能谎称自动透传错误 | `extensions/enterprise/src/deeptutor_enterprise/runtime.py` 对非空 `mcp_tools` 标不可用，`required` 失败 |
| Tool | `deeptutor/core/tool_protocol.py`、`runtime/registry/tool_registry.py` | `BaseTool.get_definition/execute`；`ToolParameter` 全字段；`raw_parameters` 优先；`ToolResult` 全字段；`deferred`；无通用自动安装/加载器，同名注册会覆盖 | 仅部署允许的 `tools`，无自定义 Tool 注册 API |
| Skill | `deeptutor/services/skill/service.py`、`deeptutor/services/session/turns/configured.py` | 包根 `SKILL.md`、frontmatter `name/description/tags/always/requires`、命名/支持文件/限额、读取截断、普通与 `always` 区别；导入来源会去掉 `always`；不能把 Skill 当权限 | 受权 ID 可在 `skills` 选择，缺失/不可用依策略失败；无第三方上传接口 |
| 知识库 | `deeptutor/knowledge/naming.py`、`utils/document_validator.py`、`services/rag/file_routing.py`、`api/routers/knowledge.py`、企业 `knowledge_bases.py` | 本地名称校验、文件 200 MiB 上限、支持格式随解析器/提供者而变、状态/索引准备；企业 KB ID 不是本地名称规则，需 ready 且有检索绑定/授权，上传附件 ID 不等于 KB ID | 仅选择已有受权 ID，无第三方创建/导入 API |
| Turn Capability | `deeptutor/core/capability_protocol.py`、`runtime/registry/capability_registry.py`、`runtime/orchestrator.py`、`core/stream.py` | `CapabilityManifest` 全字段、`run(context, stream)`、`deeptutor.extensions` entry point、事件/终态、请求配置实际验证不由 `request_schema` 自动生效 | 只支持 `chat` |
| 对话循环扩展 | `deeptutor/capabilities/protocol.py`、`capabilities/registry.py` | 结构协议必需方法、`owned_tools` 语义、可选 hooks、`KnowledgeCapability` 排他例外、entry point；不等同顶层能力 | 无第三方启用/安装 API |
| 可视化扩展 | `deeptutor/visualizers/protocol.py`、`store.py`、`README.md` | Manifest 全字段/取值/长度、ZIP 限额、第三方只限 iframe、payload/schema 限额、消息类型/版本；不是任意后端代码 | 无第三方安装/选择 API |
| 阅读扩展 | `deeptutor/reading/extensions.py`、`api/routers/reading_extensions.py` | Entry point 与 id 匹配；Manifest/Context/Result 全字段和上限；action 必须声明、选择文本须在当前单元内；30 秒超时与忙/错误 503 | 无第三方动作 API |
| CLI 工具集成 | `deeptutor/services/cli_apps/models.py`、`catalog.py`、`provider.py`、`runner.py` | 当前仅目录条目对应应用，不存在任意 CLI 包自助加载；ID/入口规则、包管理器支持、`args: string[]`、120/600 秒、20k 字符、非零退出码是应用结果并不自动置 ToolResult 失败、权限多条件 | 无第三方目录/执行 API |

以上是文档事实来源，而不是对这些协议的跨版本稳定性承诺。若代码或部署组合变化，应更新矩阵、公开页面和对应回归测试。
