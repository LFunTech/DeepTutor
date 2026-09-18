# 设计说明

## Context

P0 收口后，DeepTutor 当前 repo 已经具备 API-only EduPlus2 联邦访问基础能力，但前置应用仍需要一份独立、可执行的交接契约。P1 的设计目标是把“如何接入”从实现代码和零散讨论中抽出，形成可版本化文档与 smoke 入口。

P1 不是功能扩展 proposal。除非发现 contract drift 或无法联调的真实缺陷，P1 不应改动 DeepTutor core auth/WS 行为。

## 决策 1：契约文档是主要交付物

新增文档建议路径：

```text
docs/enterprise/eduplus2-fronting-app-integration-contract.md
```

文档受众：

- 前置应用前端/后端团队；
- DeepTutor 部署/联调人员；
- EduPlus2 测试环境维护人员；
- 后续 TMS/OMS/M1/G1 proposal 作者。

文档必须包含：

1. 系统边界图：EduPlus2、前置应用、DeepTutor、浏览器/SDK、WS。
2. 端到端时序：打开 DeepTutor、exchange、start turn、WS refresh、断线重连、audit 查询。
3. HTTP contract：headers、body、响应、错误码、禁止字段。
4. WS contract：`auth_refresh` payload、`auth_ack/auth_revoked/auth_expiring`、`resume_from`。
5. 前置应用职责：合法性校验、JWT 获取、refresh 触发、周期策略、撤权窗口。
6. DeepTutor 职责：JWT 验签、resolve/allowlist、短 `dt_token`、owner guard、审计。
7. 配置矩阵：local/test/prod 需要的 env 和 Secret ref。
8. 故障矩阵：401/403/409/429/503 与用户可见处理。
9. 审计和排障：request id、event kind、导出权限、脱敏规则。
10. 安全禁令：不记录 token、不能信任 body tenant/user、不能保存 client secret。

## 决策 2：前置应用职责外置，不再混入当前 repo

P1 文档必须明确：

- 前置应用负责打开 DeepTutor 前校验当前 EduPlus2 用户是否合法；
- 前置应用负责 refresh 时重新获取 EduPlus2 user JWT；
- 前置应用负责周期合法性校验和撤权窗口策略；
- DeepTutor 不实现前置应用周期校验调度；
- DeepTutor 只在自身接收 exchange/refresh/HTTP/WS/SDK 敏感操作时做本地信任边界校验。

若用户后续要求实时撤权 SLA，应另立 proposal，不在 P1 中补实现。

## 决策 3：Smoke harness 只输出脱敏证据

P1 应提供一个清晰入口，候选路径：

```text
scripts/enterprise/eduplus2_fronting_app_smoke.py
```

或复用 pytest wrapper：

```bash
PYTHONPATH=extensions/enterprise/src \
DT_EDUPLUS2_REAL_SMOKE=1 \
./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_real_smoke.py -q
```

若新增脚本，脚本必须：

- 从 `.secrets/token-test.secrets` 与 `.secrets/deeptutor-local-eduplus2.env` 读取配置；
- 校验文件存在但不打印 secret；
- 检查 user JWT 是否未过期、`azp` 是否匹配 configured client id；
- 调用 exchange 并验证 `dt_token` 可解码且包含 EduPlus2 claims；
- 可选执行 WS refresh 和 audit export；
- 输出 JSON 摘要，例如 `exchange_status=ok`、`dt_token_valid_now=true`、`request_id=...`；
- 遇到 missing token / expired token / invalid client / permission denied 时输出脱敏 reason 和建议下一步。

## 决策 4：错误处理矩阵必须成为验收内容

P1 文档和 smoke 必须覆盖下列分类：

| 场景 | DeepTutor 响应 | 前置应用处理 |
| --- | --- | --- |
| 缺 JWT / JWT 无效 / 过期 | 401 | 重新从 EduPlus2 获取登录态或提示重新进入 |
| client 未注册/暂停/撤销 | 403 | 停止调用，提示应用未授权，联系管理员 |
| tenant/app/client mismatch | 409 | 停止调用，视为配置冲突 |
| replay/rate limit | 429 | 指数退避，不循环换票 |
| EduPlus2 resolve/profile/permission 不可用 | 503 或 fail closed | 降级提示，稍后重试 |
| owner/resource guard denied | 403/404 | 不重试为其他 tenant/user，不暴露资源是否存在 |
| WS refresh 失败 | `auth_revoked` 或连接关闭 | 用新 JWT 重新 exchange 后重连并 `resume_from` |

## 决策 5：不改变 upstream mergeability 边界

P1 只新增文档、脚本或测试，不把 EduPlus2 业务规则写入 core。若 contract drift 要求改代码，必须：

1. 优先改企业扩展包；
2. core 只允许通用 seam；
3. 新增测试证明未启用 EduPlus2 时默认路径不受影响；
4. 更新 P1 tasks 和 execution evidence。

## Failure Modes

- 文档写成 TMS/OMS 已实现：必须 fail review。
- smoke 打印 token/client secret/JWT：必须阻断。
- 前置应用示例信任 body/query tenant/user：必须阻断。
- 文档错误地要求 DeepTutor 实现周期合法性任务：必须修正。
- smoke 只验证 discovery，不覆盖 user JWT exchange：不能视为 P1 完成。
- API/WS contract 与实际代码不一致：优先修正文档或记录实现缺陷并补任务。

## Verification Strategy

- `openspec validate add-eduplus2-fronting-app-integration-contract --strict`
- 文档链接检查和 secret 字符串扫描。
- smoke 脚本 dry-run / missing-secret / expired-token 负例。
- 使用 `.secrets/token-test.secrets` 的真实 user JWT 执行 local/test exchange smoke。
- WS contract 至少复用现有 `tests/api/test_unified_ws_protocol.py` 或新增 wrapper 检查 `auth_refresh` payload。
- 审计 export 通过现有 API/测试或 smoke 验证权限和脱敏。
