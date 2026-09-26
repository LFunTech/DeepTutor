# add-b2-tms-management-prototype

云端 TMS 高保真原型与 OMS 共享组件契约。规范性边界见 `proposal.md`、`design.md` 与 `specs/`；实施/验证门禁见 `tasks.md`。

本 change 仅规划学校/企业租户管理后台。DeepTutor 本地 Web、云端 OMS、云端 TMS 是不同前端交付物；OMS/TMS 独立部署，但复用同一管理业务组件（OCR 服务列表为必验样例）。本租户配额清单是一级只读列表：TMS 可查看 OMS 配置的赠送/充值额度、余额和消耗明细，不能新增、编辑、撤销或调整任何配额；配额写入仅在 OMS。现有 `web/app/tms` 不是目标 TMS，尚无真实 TMS 原型、API 或生产部署。未经用户审阅和后续实施提案批准，不得把文档校验当作功能完成。
