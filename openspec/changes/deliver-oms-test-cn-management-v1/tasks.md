> **当前主线（2026-09-30）**：本 proposal 是 OMS 的唯一执行主线。旧 OMS 横向 proposal 已完成内容作为证据来源，未完成内容除非列入本文件，否则不再作为当前任务推进。

## 0. Proposal 收敛与旧主线冻结

- [x] 0.1 单独 archive 已完成 proposal：`add-b2-eduplus2-tenant-lifecycle-webhook`、`relocate-database-business-rules-to-application`、`add-ws-required-context-controls`、`add-third-party-capacity-development-guides`。
- [x] 0.2 标记旧未完成 OMS 相关 proposal 为 superseded/paused，并说明本 change 为新的执行主线。
- [x] 0.3 跑 `openspec validate deliver-oms-test-cn-management-v1 --strict` 和 `openspec validate --all --strict`，确保收敛后的 OpenSpec 图有效。

## 1. OMS v1 已完成能力基线

- [x] 1.1 正式 `/oms` 服务端入口、会话提示 Cookie、授权码登录 start/callback/status/refresh/logout 已实现；未登录自动进入登录流程，不展示调试页。
- [x] 1.2 首位平台管理员初始化、OMS 独立会话、CSRF/Origin 写保护、本地 `ops.*` 默认零权和失败关闭已实现。
- [x] 1.3 DeepTutor Enterprise 程序级 PEP 已覆盖 platform/school scope、assignment、撤权、主体停用、审批 apply 和学校绑定版本。
- [x] 1.4 学校列表/学校详情已接正式安全 DTO，展示学校绑定、生命周期、服务授权、额度和用量摘要，不读取学校账号。
- [x] 1.5 模型与服务、Provider 设置读取/draft/test/publish/rollback 已接正式 API 与权限按钮，Secret 不回显。
- [x] 1.6 Agent 与能力、工具与集成、知识基础能力、运行资源已作为安全资源状态投影接入列表/详情，未返回 DTO 时不回退原型 fixture。
- [x] 1.7 global Skill 列表、review、publish、学校授权已接正式 API；后端支持 draft upload、grant/revoke 和包校验。
- [x] 1.8 服务供给、学校服务授权、quota grant 创建/调整/撤销/过期已接后端 API；UI 已接授权、额度和供给批次撤销。
- [x] 1.9 用量 attempt、待核对 jobs、audit、OMS-only cost 安全投影已接入；后端支持 provider receipt、settle、release、usage export。
- [x] 1.10 平台人员、角色、学校范围授权、assignment 撤权、主体停用、审批 review/apply 和授权审计回读已接 UI/API。
- [x] 1.11 本地 `_next/static` catch-all 误入 OMS 鉴权导致 500 的问题已修复；无效 chunk 返回 404，有效 chunk 返回 200。

## 2. v1 剩余功能缺口

- [ ] 2.1 补齐供给批次“注册/采购补充”正式 UI，避免只有后端 API 和撤销按钮；payload 不得伪造采购证据或回显 Secret/成本。
- [ ] 2.2 补齐用量核对 UI：provider receipt 对账、人工 settle、确认未发出 release、usage export 的按钮级入口、版本/原因/审计回读。
- [ ] 2.3 补齐 usage/jobs/cost/audit 的必要筛选、分页、详情和错误态；不前端估算成本或费用。
- [ ] 2.4 补齐 Provider/模型/Skill/供给/额度/授权写操作的失败态、版本冲突态和按钮级真实账号验收。
- [ ] 2.5 明确 Agent/工具/知识基础能力在 v1 中仅为安全状态投影；若需要写管理能力，另建 v2 proposal。

## 3. 本地真实域名验收

- [x] 3.1 仓库规则已写入：本地 OMS/TMS/frontend/auth/cookie/OAuth/WebSocket/static-asset 调试必须使用 `local-ssl`。
- [x] 3.2 本地 `local-ssl` 链路已恢复：`https://deeptutor.lfun.pub/oms` 不再 502，能进入 OMS 登录跳转；auth start 能跳转 EduPlus2 Auth。
- [ ] 3.3 使用 `.secrets/.login-credentials` 中 admin 账号完成本地浏览器登录验收，确认首屏、核心菜单、权限按钮和失败关闭。
- [x] 3.4 本地执行针对 OMS v1 的前端测试、后端测试、typecheck、build、lint、`git diff --check`。

## 4. test-cn 部署与验收

- [x] 4.1 在本地验证完成后，按仓库 tag 规则提交、推送并创建正确 `deploy/test-cn/vX.Y.Z-rc.N` tag。
- [ ] 4.2 监控 Woodpecker 流水线，确认 OMS 前端构建、后端构建、部署和 smoke 无失败。
- [ ] 4.3 部署完成后，只使用 `.secrets/.login-credentials` 中 admin 账号做 test-cn OMS v1 浏览器验收。
- [ ] 4.4 test-cn 验收覆盖：正式入口、学校列表、模型与服务、供应商连接、Skills、知识基础能力、供给/额度、用量/任务、审计/治理、平台人员授权；确认无学校账号开通入口。
- [ ] 4.5 test-cn 验收负例覆盖：无本地授权 fail closed、无效静态 chunk 404、Secret/成本/私有正文不泄露、旧原型/旧学校开通深链不可达。

## 5. 收尾

- [ ] 5.1 将 OMS v1 验收结果写入 `implementation-evidence.md`。
- [ ] 5.2 复核旧 proposal 是否可在 OMS v1 完成后归档、继续暂停或拆分为 v2/TMS/G/H 新 proposal；不得把未完成旧任务伪装成完成。
- [ ] 5.3 用户确认后再归档本 proposal；归档前必须折叠 spec 并通过 `openspec validate --all --strict`。
