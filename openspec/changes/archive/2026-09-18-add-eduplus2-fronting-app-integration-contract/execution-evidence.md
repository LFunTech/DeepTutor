# add-eduplus2-fronting-app-integration-contract 执行证据

> 本文件只记录命令、退出码、脱敏摘要、未验证项和下一步。禁止写入 EduPlus2 user JWT、DeepTutor `dt_token`、client secret、M2M token、webhook secret、签名、完整 profile 或用户隐私原文。

## 契约基线

- 已读取正式 spec：`openspec/specs/enterprise-eduplus2-federated-access/spec.md`。
- 已核对实现入口：`extensions/enterprise/src/deeptutor_enterprise/api/application.py`、`extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py`、`extensions/enterprise/src/deeptutor_enterprise/bootstrap.py`。
- 已核对 secret 文件 key 名称：
  - `.secrets/token-test.secrets`: `TOKEN`、`ClientID`、`ClientSecret`。
  - `.secrets/deeptutor-local-eduplus2.env`: `DT_EDUPLUS2_*` OIDC/open API endpoint、client、allowlist、profile/permission、revocation webhook ref 等 key。
- 基线结论：打开 DeepTutor、refresh 时外部用户合法性校验和周期合法性校验由前置应用负责；当前 repo 只处理 exchange、短 `dt_token`、WS refresh seam、owner/resource guard、可选 profile/permission/webhook 增强与审计。

## 命令记录

| 时间 | 命令 | 退出码 | 脱敏结果摘要 | 未验证项 / 下一步 |
| --- | --- | --- | --- | --- |
| 2026-09-18 | `./.venv/bin/python -m pytest tests/scripts/test_eduplus2_fronting_app_smoke.py -q` | 0 | 3 passed；覆盖 dry-run 脱敏、missing token fail-closed、expired token fail-closed。 | 无。 |
| 2026-09-18 | `openspec validate add-eduplus2-fronting-app-integration-contract --strict` | 0 | `Change 'add-eduplus2-fronting-app-integration-contract' is valid`。 | 无。 |
| 2026-09-18 | `./.venv/bin/python scripts/enterprise/eduplus2_fronting_app_smoke.py --dry-run --token-file .secrets/token-test.secrets --env-file .secrets/deeptutor-local-eduplus2.env` | 2 | 配置 key 完整且无 secret 输出；`user_jwt.status=expired`、`azp_matches_client=true`、tenant/user/sub 仅输出 SHA-256 摘要；未访问网络。 | 需要前置应用/测试人员刷新未过期 EduPlus2 user JWT。 |
| 2026-09-18 | `./.venv/bin/python scripts/enterprise/eduplus2_fronting_app_smoke.py --real --token-file .secrets/token-test.secrets --env-file .secrets/deeptutor-local-eduplus2.env` | 2 | discovery/JWKS ok（JWKS key count=2）；M2M token received（只输出 hash）；resolve ok（client active、tenant 仅 hash）；`user_jwt.status=expired`；exchange delegated，因为未提供 DeepTutor URL。 | 需要刷新未过期 EduPlus2 user JWT；如需真实 exchange/`dt_token` 解码，还需提供可达 DeepTutor 企业入口 `--deeptutor-url`。 |
| 2026-09-18 | `set -a; . .secrets/deeptutor-local-eduplus2.env; set +a; export DT_EDUPLUS2_REAL_SMOKE=1; PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_real_smoke.py -q` | 0 | 1 passed；现有真实 smoke 验证 discovery/JWKS、M2M token、resolve 正负例。 | 该 pytest 不覆盖 user JWT exchange。 |
| 2026-09-18 | `PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py::test_ws_auth_refresh_accepts_only_same_eduplus2_identity extensions/enterprise/tests/test_eduplus2_federated_access.py::test_audit_query_and_export_api_requires_tenant_admin -q` | 0 | 2 passed；覆盖 WS `auth_ack`、身份不扩大、refresh audit；覆盖普通用户审计 403、tenant_admin query/export 和导出脱敏。 | 无。 |
| 2026-09-18 | `./.venv/bin/python -m ruff check scripts/enterprise/eduplus2_fronting_app_smoke.py tests/scripts/test_eduplus2_fronting_app_smoke.py` | 0 | All checks passed。 | 初次运行仅测试 import 排序，已用 ruff fix 修正后重跑通过。 |
| 2026-09-18 | `git diff --check -- <P1 touched files>` | 0 | 无 trailing whitespace / patch 格式问题。 | 无。 |
| 2026-09-18 | local markdown link checker for modified enterprise docs/evidence | 0 | 检查 4 个 markdown 文件的本地相对链接，均存在。 | 未做外部 URL 可达性检查。 |
| 2026-09-18 | targeted secret leakage scan against modified docs/scripts/tests/evidence/tasks | 0 | 排除 `*_REF` ref 名后，对 7 个文件扫描 6 个 `.secrets` token/secret 值；no matches。 | 无。 |

## Smoke 输出约束

P1 smoke 允许输出：

- `overall_status`、每个 step 的 `status` / `reason`。
- request id。
- JWT 过期时间窗口、`azp_matches_client` 布尔值。
- tenant/user/subject 的短 SHA-256 摘要。
- endpoint 是否可达、JWKS key 数量、M2M token 是否收到、resolve 是否 verified。
- `dt_token_valid_now`、`dt_token_has_eduplus2_claim`、`dt_token_azp_matches_client` 布尔值（仅在提供 DeepTutor URL 且真实 exchange 成功时）。

P1 smoke 禁止输出：

- `.secrets` 中任何 token/secret 值。
- EduPlus2 user JWT、DeepTutor `dt_token`、M2M token、webhook signature。
- 外部用户原始 `eui/sub`、完整 profile 或私密正文。

## 未完成的真实环境前提

- 当前 `.secrets/token-test.secrets:TOKEN` 已过期，P1 smoke 按 fail-closed 返回退出码 2；需要前置应用或测试人员提供未过期 EduPlus2 user JWT 后，才能声明真实 user-JWT exchange 成功。
- 本轮没有提供可达 DeepTutor 企业入口 `--deeptutor-url`，因此脚本未执行真实 `POST /api/v1/auth/eduplus2/exchange` 与 `dt_token` 解码；脚本已实现该路径，等待可达 URL 与未过期 JWT。
- WS refresh 和审计 query/export 的联调通过现有 pytest 复用验证，未连接外部前置应用 UI。

## Rollout 结论

P1 当前完成了前置应用接入契约、配置矩阵、错误矩阵、审计排障流程、smoke 入口和脱敏证据模板。验证结果表明 discovery/JWKS、M2M token、resolve、WS refresh 单元/集成路径、审计 query/export 权限与脱敏、脚本负例和文档链接均已覆盖。

P1 完成只代表前置应用联调契约与 smoke 包可用，不代表 TMS/OMS、Handoff/OIDC callback、在线 client 治理、实时撤权 SLA、M1/G1 或生产上线完成。真实前置应用联调前必须刷新未过期 EduPlus2 user JWT，并在提供 DeepTutor 企业入口 URL 后重跑 `--real --deeptutor-url ...`。
