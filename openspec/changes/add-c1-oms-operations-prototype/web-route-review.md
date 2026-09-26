# DeepTutor Web 入口退役调整审阅记录

本原型的主体代码全部位于 `extensions/enterprise/frontends/`，未修改 DeepTutor 核心运行时、设置字段/执行语义、CLI、SDK、HTTP/WS 调用、Session 或持久化。唯一触及原本地 Web 的变更是下表中的**云端占位与旧演示入口**，不改变本地 `/settings` 功能。

| 路径 | 必要性 | 替代方案及取舍 | 上游合并风险 | 验证 |
| --- | --- | --- | --- | --- |
| `web/app/oms/page.tsx`、`web/app/tms/page.tsx` | 旧云端占位包含与获批业务边界冲突的“只读 Provider / Token 计费 / TMS 设置写入”陈述；正式云端管理路径未具真实身份/API，不能继续展示为待启用云端入口 | 仅改文案仍会保留易误认入口；改为 `notFound()` 并在 Proxy 返回真实 404，避免云端管理旁路 | 低：只影响两个占位页，不触及本地设置；若 upstream 删除/重命名占位页，合并时优先保留其不启用原则 | `web/tests/proxy-policy.test.ts`、`tests/runtime/test_tms_oms_frontend_contract.py` |
| `web/app/oms/prototype/page.tsx`、`web/app/tms/prototype/page.tsx` | 老 OMS 费用/欠费演示不得继续作为当前原型；本地 Web 只提供开发态入口跳转 | 直接删除旧入口会使已有评审链接失效；保留开发态跳转，生产由 Proxy 预渲染前 404 | 低：两个专用原型路径，无通用设置/聊天影响 | 开发态独立 200、生产原型路径 HTTP 404；Web 路由测试 |
| `web/lib/proxy-policy.ts`、相关测试 | 精确阻断 `/oms`、`/tms` 及其尾斜杠；不影响 `/api`、`/ws`、`/settings` | 只在页面 `notFound()` 可能产生流式 200，不能满足入口隔离 | 低：精确路径集，既有 auth/backend 路由顺序不变 | 路由纯函数测试与 `git diff --check` |

**审阅结论：**这些是企业云端占位/演示入口退役的窄范围 Web 调整，不是 DeepTutor 管理逻辑迁移，更不证明真实云端管理入口已经关闭全部直连路径。正式企业云端对旧 `/settings` API、CLI/SDK、身份/授权的封闭仍由后续实施 proposal 逐入口审阅；若未来需要核心 seam，须另行审阅而非在本原型中补丁式改动。
