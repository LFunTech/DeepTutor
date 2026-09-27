# 智能体基座 Agent 开发者文档站

本目录是面向第三方 Agent 开发者的独立 Docusaurus 站点，仅记录 **15 个第三方 HTTP 接口及 11 个 WebSocket 命令**。其他企业路由不进入发布内容。站点不提供凭证，也不代表已经发布到公网。

## 本地预览

要求 Node.js 22.12 或更新版本（Mermaid 相关依赖的最低版本）。

```bash
cd docs-site
npm ci
npm run start
```

默认站点路径为 `http://localhost:3000/docs/`。如果要在不同本地路径预览或发布，设置 `DOCS_SITE_URL` 与 `DOCS_BASE_URL`。

## 构建与发布配置

```bash
DOCS_SITE_URL='https://<your-docs-host>' DOCS_BASE_URL=/docs/ npm run build
```

`DOCS_SITE_URL` 必须在正式发布前替换为部署方的真实文档域名；未设置时仅使用本地预览地址。构建产物位于 `docs-site/build/`。

受保护的 `deploy/test-cn/*` Woodpecker 发布分支使用本目录作为独立 Docker 构建上下文，构建时从环境 registry 注入测试域名，固定 `DOCS_BASE_URL=/docs/`；文档镜像以 digest 部署到独立静态服务，并经现有测试域名的 `/docs/` Ingress 路由开放。预发和生产分支不发布文档站。本地构建或修改流水线不代表已上线；实际发布需先将本目录纳入受保护提交，并由授权人员按现有发布门禁打 tag、审批和验证。

页脚只显示版权及已配置的备案信息，不显示导航快捷入口。部署方在构建时按实际备案情况设置 `DOCS_ICP_NUMBER`、`DOCS_PUBLIC_SECURITY_NUMBER`；未提供时不展示虚构备案号。

## 内容维护

企业路由的真实挂载源是 `extensions/enterprise/src/deeptutor_enterprise/api/application.py`，身份白名单在同文件的 `AuthenticationMiddleware` 中，WebSocket wire model 在 `deeptutor/api/contracts/turn_protocol.py`，命令处理器在 `deeptutor/api/routers/unified_ws.py`。更新接口时同步更新本站目录和示例；不得仅从规划文档推断接口已经开放。

在 **DeepTutor 仓库根目录**运行契约检查（只装配应用，不启动外部服务）：

```bash
PYTHONPATH=extensions/enterprise/src .venv/bin/python docs-site/scripts/check_enterprise_routes.py
PYTHONPATH=extensions/enterprise/src .venv/bin/python docs-site/scripts/check_ws_examples.py
PYTHONPATH=extensions/enterprise/src .venv/bin/python -m unittest discover -s docs-site/scripts -p 'test_docs_contracts.py' -v
npm --prefix docs-site run typecheck
npm --prefix docs-site run build
```

`src/data/enterprise-routes.json` 是**第三方公开页面**的数据源；每项必须有独立详细页面。`check_enterprise_routes.py` 同时校验公开目录与真实挂载路由及非公开排除清单，防止新增路由被误发布或遗漏分类。WS JSON 示例前的 `<!-- ws-command -->` 标记由 `check_ws_examples.py` 按 `ClientCommand` 校验。脚本无法替代人工核对 Origin、资源归属、错误语义和部署策略。站点不包含真实域名、测试身份、Secret 或公网部署配置；这些由部署方提供。
