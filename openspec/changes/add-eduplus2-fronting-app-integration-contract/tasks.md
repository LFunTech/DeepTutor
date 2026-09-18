# 实施任务

范围以 [proposal](proposal.md)、[design](design.md) 和 `enterprise-eduplus2-fronting-app-integration` delta spec 为准。P1 是**前置应用接入契约与联调 smoke 包**，不是 TMS/OMS、Handoff 或实时撤权实现。

## 0. 契约基线与输入核对

- [x] 0.1 读取并记录已归档 `enterprise-eduplus2-federated-access` 的 API/WS/audit contract，不复制旧“周期校验由当前 repo 实现”的口径。
- [x] 0.2 核对现有代码中的实际 endpoint、headers、payload、响应字段、错误码和 WS frame schema。
- [x] 0.3 核对 `.secrets/token-test.secrets` 与 `.secrets/deeptutor-local-eduplus2.env` 所需 key 名称；不得记录 token、client secret 或用户隐私。
- [x] 0.4 明确 local/test/prod 配置矩阵和 Secret ref 命名，标注哪些来自前置应用、哪些由 DeepTutor 读取。

## 1. 前置应用接入契约文档

- [x] 1.1 新增 `docs/enterprise/eduplus2-fronting-app-integration-contract.md`，包含架构边界、端到端时序、职责分界和非目标。
- [x] 1.2 写明 `POST /api/v1/auth/eduplus2/exchange` 的请求、响应、错误码、幂等/重放/限流和禁止字段。
- [x] 1.3 写明 HTTP/SDK 后续调用如何携带 `dt_token`，以及不得用 body/query/header 传 tenant/user/client 作为授权证据。
- [x] 1.4 写明 WS `auth_refresh`、`auth_ack`、`auth_revoked`、可选 `auth_expiring` 和 `resume_from` 的 payload 与状态机。
- [x] 1.5 写明前置应用负责打开、refresh、周期合法性校验和 EduPlus2 user JWT 更新；当前 repo 不实现周期校验调度。
- [x] 1.6 写明审计查询/导出接口、权限要求、筛选参数、导出格式、脱敏字段和排障流程。

## 2. 错误矩阵与安全要求

- [x] 2.1 增加 401/403/409/429/503、WS refresh 失败、owner guard denied、resolve/profile/permission unavailable 的处理矩阵。
- [x] 2.2 增加 token/JWT/client secret/M2M token 不落日志、不进审计正文、不进前端可读存储的要求。
- [x] 2.3 增加 request id / trace id 传播建议，确保前置应用、DeepTutor 审计和 EduPlus2 调用可关联。
- [x] 2.4 增加前置应用用户提示与重试策略：重新登录、指数退避、配置冲突阻断、服务不可用降级。

## 3. Smoke harness 与脱敏证据

- [x] 3.1 新增或封装 smoke 入口，读取 `.secrets` 中 local/test 配置但不打印 secret。
- [x] 3.2 smoke 覆盖 discovery/JWKS、M2M token、resolve、user JWT exchange、`dt_token` 解码和 `azp/tid/eui` 摘要校验。
- [x] 3.3 smoke 覆盖 WS refresh 或明确复用现有 pytest 的命令；输出 `auth_ack`/失败摘要，不打印 token。
- [x] 3.4 smoke 覆盖审计 query/export 或明确复用现有 pytest 的命令；验证普通用户 403、tenant_admin 成功、导出内容脱敏。
- [x] 3.5 增加 expired JWT、missing token、tenant mismatch、rate limit 或 service unavailable 的至少两个负例 smoke/测试。
- [x] 3.6 输出 `execution-evidence.md` 模板，记录命令、退出码、脱敏结果、未验证项和下一步。

## 4. 文档同步与交付

- [x] 4.1 更新 `docs/enterprise/readme.md` 文档地图，加入 P1 接入契约文档。
- [x] 4.2 更新 `docs/enterprise/11-api-and-entrypoints.md` 中当前实现状态，指向 P1 契约而不是重复内联全部细节。
- [x] 4.3 如新增脚本，更新 README 或 runbook 中的调用示例。
- [x] 4.4 确认所有新增文档链接有效，不引用已不存在的 active OpenSpec changes。

## 5. 验证与收口

- [x] 5.1 运行 `openspec validate add-eduplus2-fronting-app-integration-contract --strict`。
- [x] 5.2 运行 P1 smoke dry-run / real test；无法执行真实 test 时记录缺失的非 secret 前提。
- [x] 5.3 运行 targeted secret leakage scan，确认新增文档、脚本、evidence 不含 `.secrets` 中 token/secret 值。
- [x] 5.4 运行适用 lint/format 检查；若只改文档和脚本，说明未运行全量前后端测试的原因。
- [x] 5.5 更新 proposal/evidence 的 rollout 结论：P1 完成仅代表前置应用联调契约完备，不代表 TMS/OMS、M1/G1 或生产上线完成。
