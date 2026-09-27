# add-b2-tms-management-prototype

云端 TMS 高保真原型与 OMS 共享组件契约。规范性边界见 `proposal.md`、`design.md` 与 `specs/`；实施/验证门禁见 `tasks.md`。

本 change 规划并交付**开发态**学校智能体管理后台原型。DeepTutor 本地 Web、云端 OMS、云端 TMS 是不同前端交付物；OMS/TMS 独立构建，但复用同一管理业务组件（OCR 服务列表为必验样例）。本校配额清单是一级只读列表：TMS 可查看 OMS 配置的赠送/充值额度、余额和消耗明细，不能新增、编辑、撤销或调整任何配额；配额写入仅在 OMS。现有 `web/app/tms` 不是目标 TMS；原型不等于真实 TMS API 或生产部署。双端浏览器验收见 [记录](../add-c1-oms-operations-prototype/prototype-browser-audit-2026-09-27.md)，正式能力仍受后续实施提案审批及服务端验证门禁约束。
