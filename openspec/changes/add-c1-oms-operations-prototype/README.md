# add-c1-oms-operations-prototype

Agent 平台 OMS 的总体契约与高保真原型规划。规范性边界见 `proposal.md`、`design.md` 和 `specs/`；源码对照见 `settings-attribute-inventory.md`、`resource-scope-inventory.md` 与 `readiness-audit.md`。

2026-09-26 决策重订：旧“OMS 只读 Provider + Token 计费/欠费”原型和六个依赖提案不能按原内容继续实施。DeepTutor 是本地部署产品；云端 OMS/TMS 前端分别构建、部署，通过共享包复用服务业务组件（OCR 列表为必验样例），TMS 原型由 [`add-b2-tms-management-prototype`](../add-b2-tms-management-prototype/proposal.md) 单独规划。现有 DeepTutor Web `/oms/prototype` 仍是旧演示，**不是本版 IA、共享组件或独立部署的验收证据**；云端正式 OMS 仍未启用。本 change 不授权生产发布、核心修改或归档。
