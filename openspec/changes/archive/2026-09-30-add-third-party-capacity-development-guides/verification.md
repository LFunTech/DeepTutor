# 验证记录（2026-09-27）

- 新增 Capacity 目录页及九类独立页面；每页有企业适用状态、交付物、输入输出、安全、失败、示例、自测。第三方读者只读审查指出的阅读扩展入口、可视化 ZIP/消息结构、二维数据格式及当前能做什么等问题已修正。
- `PYTHONPATH=extensions/enterprise/src .venv/bin/python -m unittest discover -s docs-site/scripts -p 'test_docs_contracts.py' -v`：23 个测试通过，包含页面结构、可用性边界及示例格式校验。
- `PYTHONPATH=extensions/enterprise/src .venv/bin/python docs-site/scripts/check_ws_examples.py`：17 个命令示例通过。
- `npm --prefix docs-site run typecheck`、`npm --prefix docs-site run build`：通过；构建产物包含 `/capacities/` 及九个详情路由。
- 本地开发站 `http://localhost:3000/docs/` 已启动；使用浏览器等价的 `Accept: text/html` 请求，目录、MCP 与快速开始路径均返回 200。
- `openspec validate add-third-party-capacity-development-guides --strict` 与 `git diff --check`：通过。
- 额外运行现有 `check_enterprise_routes.py` 时发现当前工作区另有两条 TMS school-bootstrap 路由未列入目录排除清单，因此该全局检查未通过；本次文档变更未修改路由或排除清单，需由对应企业路由变更单独处理，不将其记为本次通过。
- 未提交、推送、归档或部署；工作区中其他改动保持原样。

## 用户复审后的完整规范修订

- 已按 `source-contract-matrix.md` 对照九类当前代码契约：各页由“最小示例”转为字段/方法、校验、限额、输出与失败语义为主体，示例仅用于验证。知识库没有虚构包 manifest，CLI 没有虚构任意插件加载器。
- 纠正两处关键语义：MCP `isError`/`structuredContent` 不会自动转成当前 Tool 失败/结构化结果；CLI 应用非零退出码不自动令 `ToolResult.success=false`。企业第三方实际开放范围仍单独提示。
- `PYTHONPATH=extensions/enterprise/src .venv/bin/python -m unittest discover -s docs-site/scripts -p 'test_docs_contracts.py' -v`：24 个测试通过，新增从当前代码常量/字段核对九类页面的测试；Python/JSON/TOML 示例解析通过，Tool、阅读扩展和 Turn 示例已用合成上下文实际执行。
- `PYTHONPATH=extensions/enterprise/src .venv/bin/python docs-site/scripts/check_ws_examples.py`：17 个命令示例通过。
- `npm --prefix docs-site run typecheck`：通过。首次 `build` 发现知识库页面内竖线导致 MDX 表格误解析，已定位并改为文字枚举；随后 `npm --prefix docs-site run build` 通过，构建产物中核对到扩展页面的新规范正文。
- `openspec validate add-third-party-capacity-development-guides --strict`、`git diff --check`：通过。现有本地文档服务的目录及抽查页面路径均返回 HTTP 200；未修改 API、流水线或外部仓库。
- 第三方读者视角复核：逐页能区分“可交付的格式/类/服务”“已实现的运行约束”和“企业第三方入口当前能否调用”；不把建议、规划或自部署能力冒充企业正式接口。本次仍未提交、推送或部署。
