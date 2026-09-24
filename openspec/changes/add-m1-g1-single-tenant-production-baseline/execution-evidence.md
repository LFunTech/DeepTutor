# add-m1-g1-single-tenant-production-baseline 执行证据

日期：2026-09-18。范围：仓库内 M1/G1 单租户生产基线的配置契约、smoke/evidence 工具与本地企业回归。**未触发真实 Woodpecker，未操作目标 Kubernetes/生产集群，未连接真实 ObjectStore/LightRAG 样本检索环境；因此不能声明 G1 或生产上线完成。**

2026-09-18 审查修正：先前生成的 `.woodpecker/m1-g1-single-tenant.yml` 与 `deploy/kubernetes/m1-g1-single-tenant.yaml` 被撤回。原因是 K8s/Woodpecker 发布拓扑不能从“单租户/多租户”直接推导；真实流水线必须先确认目标 Woodpecker 版本、agent backend、审批/Secret 边界、registry、集群命名空间、Ingress/TLS、SecretStore、发布锁和回退机制。撤回后 A3.1/A3.2/C1.1 均保持未完成。

禁止记录：`.secrets` 明文、JWT、DeepTutor `dt_token`、client secret、模型 key、完整 profile、用户隐私或原始业务正文。本文件只记录命令、退出码、脱敏摘要、未验证项和后续阻断。

## 已实现制品

| 类别 | 路径 | 脱敏说明 |
| --- | --- | --- |
| Production 配置契约 | `extensions/enterprise/src/deeptutor_enterprise/configuration.py`、`extensions/enterprise/deployment.example.json` | 新增 `object_store`、`settings_provider`、`secret_provider`、`lightrag`、`eduplus2`、`production` 绑定；只允许 `env:*` Secret ref；生产 fallback 必须为 false。 |
| Readiness / Evidence / Smoke 工具 | `extensions/enterprise/src/deeptutor_enterprise/m1_g1.py`、`smoke.py`、`m1_g1_cli.py` | readiness 仅输出 endpoint/tenant/client 短 hash 与错误 code；resource binding evidence 保存 ObjectStore/LightRAG 版本、hash、状态和未验证阻断；release evidence 写 JSON 且对 token/secret/password/API key 字段脱敏；smoke 输出不写目标 host、JWT 或 `dt_token`。 |
| 目标部署契约门禁 | `extensions/enterprise/deployment-contract.example.json`、`extensions/enterprise/src/deeptutor_enterprise/m1_g1.py`、`m1_g1_cli.py` | 新增 contract-first schema 与 CLI，可校验 Woodpecker/K8s 目标契约、单执行限制、受保护 ref、Secret ref、发布锁、回退和 evidence 存储；示例标明不是 A3 完成证据。 |
| 回归测试 | `extensions/enterprise/tests/test_m1_g1_baseline.py`、`extensions/enterprise/tests/test_application.py` | 覆盖生产绑定校验、缺 Secret fail-closed、evidence 脱敏、LightRAG 样本未验证阻断、M1 不暴露 TMS/OMS 路由；不再把未确认的 K8s/Woodpecker YAML 当作完成门禁。 |
| 日期稳定性修复 | `extensions/enterprise/tests/test_eduplus2_federated_access.py` | 把已过期的硬编码 `2026-09-17T12:00:00Z` 改为测试运行时未来时间；接受已实现的具体 issuer/expired 错误，不放宽生产行为。 |

## A1 盘点与生产阻断差距

已核对企业总纲与已归档证据：`postgres-only-runtime`、`sqlite-to-postgres-cutover`、`postgres-business-stores`、`enterprise-local-identity`、`enterprise-session-lifecycle`、`enterprise-scoped-persistence`、`externalized-runtime-configuration`、`externalized-resource-store`、`kubernetes-stateless-runtime`、EduPlus2 API-only/P1 contracts 只能证明分散能力或联调契约，不等于 G1 发布闭环。

当前 production runtime 阻断项：

1. 目标 Woodpecker server/agent、受保护 ref、审批边界、registry 和 K8s namespace 尚未实跑登记。
2. 目标 ObjectStore 未执行写/读/删、hash mismatch、权限不足和删除补偿负例。
3. LightRAG Server + HugeGraphStorage 固定 fork digest、样本教材导入/ready/检索/授权引用/删除/恢复尚未实跑；`smoke` 在样本未就绪时输出 `lightrag_sample_unavailable`，不能声明完整生产上线。
4. K8s 发布期间排空、旧执行者停止、新执行者启动和不重叠证据尚未实测；当前没有可验收 K8s 清单或 Woodpecker 流水线，必须先完成目标环境接入契约。
5. 真实 Ingress/TLS、EduPlus2 未过期 user JWT exchange、WebSocket `start_turn` / `auth_refresh`、ObjectStore、audit/export、rollback 演练尚需目标环境凭证与窗口。
6. B2/TMS、C1/C2/OMS、G-H 高可用均未交付；本 change 已验证 M1 企业应用未暴露 `/tms`/`/oms` 路由，但不开放后续治理能力。

## 命令记录

| 时间 | 命令 | 退出码 | 脱敏结果摘要 | 未验证项 / 下一步 |
| --- | --- | --- | --- | --- |
| 2026-09-18 | `PYTHONPATH=. .venv/bin/pytest -q extensions/enterprise/tests/test_m1_g1_baseline.py` | 0 | 4 passed；覆盖 M1/G1 配置、readiness、evidence、smoke plan。 | 不连接目标环境；K8s/Woodpecker 可执行制品已撤回。 |
| 2026-09-18 | `PYTHONPATH=extensions/enterprise/src:. .venv/bin/pytest -q extensions/enterprise/tests/test_m1_g1_baseline.py` | 0 | 9 passed；新增目标部署契约模型、CLI、示例契约校验、脱敏摘要测试和 smoke 输出脱敏测试。 | 只验证契约登记与 smoke 工具；未登记真实目标环境，A3.1/A3.2 仍未完成。 |
| 2026-09-18 | `PYTHONPATH=extensions/enterprise/src:. .venv/bin/python -m deeptutor_enterprise.m1_g1_cli contract --input extensions/enterprise/deployment-contract.example.json --output "$tmpdir"` | 0 | 生成 `deployment-contract.json` 脱敏摘要；输出 host/ref/hash、Woodpecker agent backend、K8s 单执行限制、回退策略和 evidence store，未输出 registry credential 或真实 host 原文。 | 使用 example-only 契约，不是目标环境验收；不可作为 A3 完成证据。 |
| 2026-09-18 | `PYTHONPATH=extensions/enterprise/src:. .venv/bin/pytest -q extensions/enterprise/tests/test_configuration.py extensions/enterprise/tests/test_m1_g1_baseline.py` | 0 | 17 passed；旧企业配置仍兼容，新 production 绑定、目标部署契约门禁、resource binding evidence、CLI、governance projection、C2 fail-closed gate 与 smoke 脱敏通过。 | 不连接目标环境。 |
| 2026-09-18 | `PYTHONPATH=. .venv/bin/python -m ruff check ...` / `ruff format --check ...` | 0 | `m1_g1.py`、`m1_g1_cli.py`、`smoke.py`、`test_m1_g1_baseline.py`、`test_application.py` lint 和格式检查通过。 | 无。 |
| 2026-09-18 | `PYTHONPATH=extensions/enterprise/src:. .venv/bin/pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_m1_does_not_expose_tms_or_oms_surfaces` | 0 | 1 passed；隔离 PG 企业 ASGI 应用中 `/tms`、`/api/v1/tms/*`、`/oms`、`/api/v1/oms/*` 对匿名和已认证 tenant_admin 均返回 401/404/405，不暴露未纳入 M1 的 TMS/OMS。 | 仅验证当前仓库企业应用路由；不等同目标 K8s smoke。 |
| 2026-09-18 | `PYTHONPATH=extensions/enterprise/src:. .venv/bin/pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_m1_does_not_expose_tms_or_oms_surfaces extensions/enterprise/tests/test_eduplus2_federated_access.py::test_audit_query_and_export_api_requires_tenant_admin` | 0 | 2 passed；tenant_admin 对未交付 OMS/release evidence 路径、伪造 `ops.*` scope、跨 release evidence 路径均不可用；普通 EduPlus2 用户访问 audit/export 为 403，tenant_admin 审计导出脱敏。 | 不交付 OMS；只验证当前企业应用边界和已授权 EduPlus2 audit/export。 |
| 2026-09-18 | `PYTHONPATH=extensions/enterprise/src:. .venv/bin/pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py` | 0 | 5 passed；auth/csrf/revoke、owner guard、session PG-only、SDK local fallback、M1 TMS/OMS 边界均通过。 | 不连接目标环境。 |
| 2026-09-18 | `PYTHONPATH=. .venv/bin/python -m ruff check --fix ...` | 0 | 新增/修改 Python 文件 import 和 lint 通过。 | format check 见最终验证。 |
| 2026-09-18 | `PYTHONPATH=. .venv/bin/pytest -c extensions/enterprise/pytest.ini -q <3 failing EduPlus2 cases>` | 0 | 3 passed；修复当前日期导致的过期测试夹具，并保留具体错误语义。 | 无。 |
| 2026-09-18 | `PYTHONPATH=. .venv/bin/pytest -c extensions/enterprise/pytest.ini extensions/enterprise/tests -q --ignore=extensions/enterprise/tests/test_real_model.py` | 0 | 189 passed、1 skipped；覆盖企业身份、会话、CLI/SDK/WS、EduPlus2 exchange/refresh/audit、owner guard、preflight/schema drift 等本地隔离 PG 回归。 | `test_real_model.py` 未运行，避免重复计费；目标 K8s/Woodpecker 未运行。 |
| 2026-09-18 | `openspec validate add-m1-g1-single-tenant-production-baseline --strict` | 0 | `Change 'add-m1-g1-single-tenant-production-baseline' is valid`。 | 无。 |
| 2026-09-18 | `openspec validate --all --strict` | 0 | 14 items passed、0 failed。 | 无。 |
| 2026-09-18 | targeted secret leakage scan against modified/new files | 0 | 扫描高熵 `.secrets` 候选值、JWT 形态 token、长 `dt_token`、私钥块；排除环境变量名/字段名类引用后 0 findings。 | 词面策略示例（如 `dt_token`）不视为实际泄露；撤回的 K8s/Woodpecker 文件不再计入。 |
| 2026-09-18 | `git diff --name-only -- deeptutor` / `git diff --check -- <本轮文件>` | 0 | core `deeptutor/` 无 diff；本轮文件 patch 格式检查通过。 | 工作区存在本任务前已有的 OpenSpec 归档/删除状态，未由本轮改动。 |

## 边界结论

- **可作为仓库内 M1/G1 候选基础制品**：配置契约、目标部署契约校验、smoke/evidence 工具、M1 TMS/OMS 未暴露边界和本地企业回归已经落地。
- **不可作为 A3/G1 通过证据**：K8s/Woodpecker 制品已撤回；仍缺少真实目标环境部署契约、Woodpecker + K8s smoke、真实 ObjectStore/LightRAG、目标 Ingress/TLS、回退演练和审批记录。
- **Upstream mergeability（2026-09-19 更新）**：core diff 不再为空；新增 core patch 均为 upstream-neutral seams：`TurnRequest.resource_ids`、S3-compatible ObjectStore `presign_put`/`head_object`、通用 resources API router、`unified_ws` 可选 `validate_start_turn` policy hook。企业生产策略和具体绑定仍位于 `extensions/enterprise/`；未把 EduPlus2/tenant 业务硬编码进 core orchestrator/session/runtime。

## B2/C1/C2 后续治理边界记录

### B2 多租户/TMS 未开放

- M1 当前固定单租户运行，schema、tenant_id、RLS、resource prefix 和 LightRAG binding 只作为后续多租户兼容前提保留；不开放租户自助注册、租户切换、client/app registry 写入或 TMS UI/API。
- 已验证企业应用未暴露 `/tms`、`/api/v1/tms/*`。伪造 tenant header/query 的通用入口负例由 `test_client_tenant_override_and_http_denials_are_audited` 覆盖；会话 owner guard 由 `test_sdk_and_http_share_owner_guard` 覆盖。
- 后续 B2 前置依赖：真实多租户 tenant lifecycle、client/app registry 权限模型、LightRAG workspace/index-version 多租户隔离、同租户私有 KB 授权、跨租户 release/evidence 权限、TMS route/API/role/scope 方案。
- 保留兼容约束：M1 证据只可声明固定租户 G1 边界；不得把 M1/G1 evidence 标记为 G2，不得用固定租户 tenant_admin 权限推导平台级或跨租户治理权限。

### C1 运营管理闭环未交付

- M1 当前只验证企业应用未暴露 `/oms`、`/api/v1/oms/*`、release/evidence 运营路由；不存在可被 tenant_admin 或伪造 `ops.*` scope 访问的平台级 OMS 能力。
- 已授权的审计能力仅限 EduPlus2 audit query/export：普通 EduPlus2 用户访问 audit/export 为 403；tenant_admin 可查询/导出已脱敏审计摘要。该能力不等同统一 OMS。
- Release evidence 保留位置在本切片只作为目标部署契约字段登记：`evidence_store.kind`、`location_ref`、`retention_days`。示例中的 `object-store:deeptutor-release-evidence/m1-g1` 不是目标环境承诺，真实 A3/G1 必须登记目标 evidence store。
- `m1_g1_cli governance` 可把 release evidence、目标部署契约摘要和 audit export 摘要合成为未来 OMS 输入投影；输出字段含 release id、source/upstream SHA、image digest、schema/runtime、smoke run、approval、unresolved、pipeline run id、audit export 和 evidence store。
- 脱敏策略：evidence、audit export 和 CLI 摘要不得保存 JWT、DeepTutor `dt_token`、client secret、模型 key、完整 profile、用户隐私或原始业务正文；主机、tenant、client、bucket、prefix、registry credential 和 release ref 仅保存短 hash 或 ref kind。
- C1 仍需后续独立 proposal 才能交付：OMS API、OMS UI、跨租户 evidence 查询、release 状态决策、运营角色/权限、审计保留策略管理和生产证据审批流。

### C2 运营治理缺口与依赖

M1/G1 通过不得删除以下 C2 后续待办：

1. 配额与用量：模型 token、LightRAG 检索/导入、ObjectStore 容量、pipeline/runtime 执行用量仍需业务总账与检索遥测按 operation ID 对账。
2. SLA 与执行预留：远端 LightRAG 未确认结束时不得释放执行预留；缺用量需要进入待核算状态，而不是默认成功。
3. Client 治理：EduPlus2 client/app registry、状态变更、暂停/恢复和租户策略来源仍由后续 B2/C2 方案定义；M1 不提供在线治理 UI。
4. 周期撤权与实时性：Handoff/OIDC callback、周期合法性调度、实时撤权 SLA 均未交付；当前只保留 fail-closed 与审计证据。
5. 全局策略：跨租户策略、ops.* 能力、配额规则、告警阈值和 evidence 保留策略不能硬编码进 M1 单租户发布逻辑。
6. 依赖 proposal：B2 多租户/TMS、C1 OMS、C2 governance/SLA、G-H 多执行者/HA、LightRAG 托管生命周期和真实 Woodpecker/K8s A3 验收。

已验证的 M1 governance projection 只输出脱敏治理输入字段，并显式声明：

- `online_policy_mutation = not_available`
- `cross_tenant_governance = not_available`
- `future_oms_input = true`

C2 fail-closed gate 已覆盖：

- `usage_missing`：用量缺失时 `decision=unavailable`
- `lightrag_remote_unconfirmed`：LightRAG 远端未确认结束时 `decision=unavailable`
- `revocation_window_not_implemented`：撤权窗口未实现时 `decision=unavailable`
- `policy_source_inconsistent`：策略 source 不一致时 `decision=unavailable`

即使上述输入全部确认，M1 也只返回 `available_for_evidence_only`，仍不开放在线策略修改或跨租户治理。


## 2026-09-19 资源预上传与 WebSocket 引用执行切片

本切片执行 proposal 中已获确认的资源提交边界：第三方先申请 DeepTutor 发放的 pre-signed upload URL，直传 S3-compatible ObjectStore，提交 turn 时只携带 `prompt + resource_ids`；企业生产 WebSocket 不承载 raw binary、任意 URL、base64、pre-signed upload URL 或调用方自选 key。

### 本切片新增/调整制品

| 类别 | 路径 | 脱敏说明 |
| --- | --- | --- |
| S3-compatible pre-sign seam | `deeptutor/runtime/externalized_providers.py` | 新增短 TTL SigV4 `presign_put` 与 `head_object`；签名 headers 包含 content-type、content-length、`x-amz-meta-sha256`，不输出 access secret。 |
| PG resource binding | `deeptutor/persistence/postgres/object_resources.py` | 新增上传意图、上传完成确认、ready reference 校验；`sha256` 在 M1/G1 生产路径必填；ObjectStore key 仅内部保存，API 响应不返回 key。 |
| Resource HTTP API | `deeptutor/api/routers/resources.py`、`deeptutor/api/main.py`、`extensions/enterprise/src/deeptutor_enterprise/api/application.py` | 新增 `/api/v1/resources/upload-intents` 与 `/api/v1/resources/upload-intents/{resource_id}/complete`；企业 app 显式挂载资源 API 和 `/files/resources`，未加入匿名白名单。 |
| WS 资源引用 seam | `deeptutor/core/turn_request.py`、`deeptutor/api/routers/unified_ws.py`、`extensions/enterprise/src/deeptutor_enterprise/api/application.py` | `start_turn` 接受 `resource_ids`；core WS 提供可选 payload policy hook；企业 production `SocketAuthentication.validate_start_turn` 拒绝 legacy `attachments` 上传 payload，并在 turn 前校验 ready resource binding。 |
| 企业 ObjectStore 装配 | `extensions/enterprise/src/deeptutor_enterprise/bootstrap.py`、`extensions/enterprise/tests/test_application.py` | Enterprise 从 deployment `object_store` binding 装配 S3-compatible ObjectStore；测试只使用 env Secret ref。 |
| 企业 AppShell bootstrap endpoint | `extensions/enterprise/src/deeptutor_enterprise/api/application.py`、`extensions/enterprise/tests/test_application.py` | 企业最小 API 只匿名暴露核心 `GET /api/settings/ui` 的 `theme/language/response_language` bootstrap 投影，解决 demo/frontend AppShell 登录前语言请求 401；完整 settings/admin 配置面仍未挂载，`/api/sessions` 等业务接口继续要求认证。 |
| Demo / dry-run smoke | `web/app/enterprise/eduplus2/fronting-demo/page.tsx`、`web/app/enterprise/eduplus2/fronting-demo/layout.tsx`、`web/lib/eduplus2-fronting-demo*.ts`、`scripts/enterprise/eduplus2_fronting_app_smoke.py` | Demo 在真实 `/api/v1/ws` 对话测试区域内提供文件选择、SHA-256、upload intent、pre-signed PUT、complete、`resource_id` 自动填充和 WS `resource_ids` 提交；已移除独立 pre-signed upload 说明板块；并增加仅限该 route 的 cache bridge，避免本地 immutable page chunk 旧缓存导致文件选择按钮不可见/不可触发；dry-run smoke 展示同一资源链路，不输出 signed URL、token、Secret 或用户正文。 |

### 2026-09-19 命令记录

| 命令 | 退出码 | 脱敏结果摘要 | 未验证项 / 下一步 |
| --- | --- | --- | --- |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/api/test_http_provider_context.py::test_unified_ws_rejects_start_turn_when_auth_provider_denies_payload -q`（RED，实施前） | 1 | 新增测试因 `validated_payload` 未出现失败，证明 core WS 尚未调用 payload policy hook。 | TDD red，仅用于证明测试能捕获缺口。 |
| `PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py::test_enterprise_production_ws_rejects_legacy_payload_and_verifies_resource_refs -q`（RED，实施前） | 1 | 新增测试因 `SocketAuthentication` 缺少 `validate_start_turn` 失败，证明企业生产 WS policy 尚未实现。 | TDD red，仅用于证明测试能捕获缺口。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/api/test_http_provider_context.py::test_unified_ws_rejects_start_turn_when_auth_provider_denies_payload -q && PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py::test_enterprise_production_ws_rejects_legacy_payload_and_verifies_resource_refs -q` | 0 | 2 个新增回归均通过；core WS 在 start_turn 前调用可选 policy hook，企业 production 拒绝 legacy payload 并验证 ready `resource_id`。 | 不等同真实 WebSocket 目标环境 smoke。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/api/test_http_provider_context.py -q` | 0 | 3 passed；WS provider context 与 payload policy hook 回归通过。 | 不连接目标环境。 |
| `PYTHONPATH=. ./.venv/bin/python -m ruff check deeptutor/api/routers/resources.py deeptutor/api/routers/unified_ws.py deeptutor/persistence/postgres/object_resources.py deeptutor/runtime/externalized_providers.py deeptutor/core/turn_request.py extensions/enterprise/src/deeptutor_enterprise/bootstrap.py extensions/enterprise/src/deeptutor_enterprise/api/application.py scripts/enterprise/eduplus2_fronting_app_smoke.py tests/runtime/test_s3_presign.py tests/api/test_turn_protocol_resource_refs.py tests/api/test_http_provider_context.py tests/scripts/test_eduplus2_fronting_app_smoke.py extensions/enterprise/tests/test_application.py` | 0 | All checks passed。 | 无。 |
| `PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -q` | 0 | 7 passed；企业 app 认证/CSRF/owner guard、资源 upload intent/complete、生产 WS resource policy、M1 TMS/OMS 边界回归通过。 | 不连接目标 K8s/Woodpecker。 |
| `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py::test_http_auth_csrf_revoke_and_closed_routes -q`（`/api/settings/ui` RED，实施前） | 1 | 新增断言复现匿名 `GET /api/settings/ui` 返回 `401 Authentication required`，证明企业最小 API 漏挂/漏放行 AppShell bootstrap endpoint。 | TDD red，仅用于证明测试能捕获用户报告的 401。 |
| `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py::test_http_auth_csrf_revoke_and_closed_routes -q` / `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -q` | 0 | 单测通过；整文件 7 passed、1 skipped。匿名 `GET /api/settings/ui` 只返回 `theme/language/response_language`，`/api/sessions` 仍为 401，`PUT /api/settings/ui` 仅因未挂写接口返回 405。 | 本地 ASGI/后端验证，不等同目标 Ingress/K8s。 |
| `curl -i https://deeptutor.lfun.pub/api/settings/ui` after backend restart | 0 | 本地域名经 Next/nginx rewrite 到 `127.0.0.1:8001` 后返回 `200 OK` 与 `{"theme":"snow","language":"en","response_language":"en"}`；直接后端同样 200。 | 使用本地 `deeptutor.lfun.pub`/backend；目标生产域名仍需 V.3 smoke。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/api/test_http_provider_context.py tests/runtime/test_s3_presign.py tests/api/test_turn_protocol_resource_refs.py tests/scripts/test_eduplus2_fronting_app_smoke.py -q` | 0 | 9 passed；S3 pre-sign、WS resource_ids 协议、dry-run smoke 资源链路和 WS policy hook 回归通过。 | 未执行真实 S3 PUT/GET。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx`（新增上传 UI 测试的 RED，实施前） | 1 | 新增测试因页面缺少“选择图片、音频、视频或文档文件”输入失败，证明此前 demo 只有说明/手动 `resource_ids`，未提供真实 pre-signed upload UI。 | TDD red，仅用于证明测试能捕获用户指出的 demo 缺口。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx`（上传 UI 应内嵌到 WS 对话区域的 RED，实施前） | 1 | 测试因仍存在独立 `Resource pre-upload contract` 板块失败，证明 UI 结构尚未按“开始 WebSocket 对话部分完成上传并提交”的要求收敛。 | TDD red，仅用于证明测试能捕获用户指出的交互位置缺口。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx` | 0 | 1 test file passed、9 tests passed；覆盖 demo 页面展示、`dt_token` 不持久化、文件选择/上传控件位于“真实 `/api/v1/ws` 对话测试”区域、独立 pre-signed upload 板块不存在、文件选择后调用 upload intent、pre-signed PUT、complete、自动填入 `resource_id`，并确认 WS `start_turn.resource_ids=["res_demo_image"]` 且 `attachments=[]`，不把 URL/base64 放入 WS payload。 | Vitest 使用 mock pre-signed URL；真实本机 MinIO HTTP API 版本见下方 A2 测试，不代表目标生产资源治理 UI。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx -t "opens the hidden resource file input"`（显式选择文件按钮 RED/GREEN） | 1 → 0 | RED 复现页面没有独立“选择文件”按钮；修复后可见按钮通过 user activation 调用隐藏 `input[type=file].click()`，避免依赖浏览器原生 file input 内部按钮点击区域。 | 单测不打开真实 OS 文件对话框；真实浏览器 filechooser 见下一条。 |
| Playwright real browser probe against `https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo` after frontend rebuild | 0 | `getByRole('button', { name: '选择文件' })` count=1，点击后 `filechooser` event fired=true；本地前端已重新 build/start 到 `127.0.0.1:3782`。 | 使用本地 demo 域名和 headless Chromium；用户浏览器需刷新页面获取新 bundle。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx` after choose-file fix | 0 | 1 test file passed、10 tests passed；既有 upload intent → pre-signed PUT → complete → WS `resource_ids` 回归仍通过。 | Vitest 使用 mock pre-signed URL。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo-upload-picker-bridge.spec.ts`（stale immutable chunk bridge RED/GREEN） | 1 → 0 | RED 复现没有 route-level cache bridge 时旧原生 file input 不会生成独立“选择文件”按钮；GREEN 后 bridge 可把旧 DOM 修补为 visible button → hidden input click，并且 fresh page 不重复插入按钮。 | 单测覆盖旧缓存 DOM 修补逻辑，不代表 OS 文件选择器；真实浏览器验证见下方。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx tests/eduplus2-fronting-demo-upload-picker-bridge.spec.ts` | 0 | 2 test files passed、12 tests passed；上传链路和 cache bridge 回归均通过。 | Vitest 使用 jsdom/mock pre-signed URL。 |
| `cd web && npm run typecheck` | 0 | 前端 TypeScript 检查通过。 | 无。 |
| `cd web && npm run build` / `.secrets/run-local-enterprise-demo-frontend.sh` | 0 / long-running | Next production build 通过；本地 demo 前端已用新 build 在 `127.0.0.1:3782` 启动。 | 本地 frontend，不等同目标 Ingress/K8s。 |
| Chrome live tab reload via CUA against `https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo` after cache bridge rebuild | 0 | 当前用户 Chrome 标签页 reload 后 AX 树出现独立 `button 选择文件`；`getByRole('button', { name: '选择文件' })` 点击触发 `filechooser`，`multiple=true`。 | 仍使用本地域名/本机前端；不自动选择或上传用户文件。 |
| `openspec validate add-m1-g1-single-tenant-production-baseline --strict && openspec validate --all --strict` | 0 | change valid；14 items passed、0 failed。 | 已在 evidence 更新后复跑最终校验。 |
| scoped `git diff --check -- <本切片相关路径>` | 0 | 本切片相关 patch 格式检查无 trailing whitespace / conflict marker。 | 全局 `git diff --check` 仍受无关 `web/public/pdfjs/wasm/LICENSE_*` 既有修改影响；未在本切片处理。 |
| targeted secret leakage scan against current diff | 0 | 扫描私钥块、JWT 形态 token、长 `dt_token`、明文 client secret/API key/AWS key；未发现明文 Secret/token。 | 目标 Woodpecker/K8s 日志仍需上线前另扫。 |
| `~/.codex/skills/local-debug/scripts/local-debug.sh status minio && ~/.codex/skills/local-debug/scripts/local-debug.sh status postgres` | 0 | 本地 MinIO `http://127.0.0.1:9000` 与 PostgreSQL `localhost:5432` 均 ready；未输出 MinIO 明文凭证。 | 本地 debug 栈状态，不等同目标 K8s/ObjectStore。 |
| `~/.codex/skills/local-debug/scripts/local-debug.sh smoke minio && ~/.codex/skills/local-debug/scripts/local-debug.sh smoke postgres` | 0 | MinIO `local-debug` bucket 写读 `smoke.txt` 成功；PostgreSQL `local_debug_smoke` 插入/查询成功。 | 本地 debug smoke，不等同生产依赖验收。 |
| `DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1 PYTHONPATH=. ./.venv/bin/python -m pytest tests/persistence/postgres/business/test_externalized_object_resources.py::test_local_minio_presigned_upload_complete_read_and_delete -q` | 0 | 1 passed；通过真实本地 MinIO 验证 DeepTutor resource binding 的 pre-signed PUT、upload complete、ready reference 校验、PG owner 负例、read 与 delete/cleanup。 | 使用本机 MinIO bucket `local-debug`，未覆盖目标 ObjectStore、HTTP API/WS 全入口、LightRAG。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/persistence/postgres/business/test_externalized_object_resources.py::test_local_minio_presigned_upload_complete_read_and_delete -q` | 0 | 1 skipped；未设置 `DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1` 时默认跳过，避免 CI/普通环境依赖本机 MinIO。 | 无。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/persistence/postgres/business/test_externalized_object_resources.py -q` | 0 | 9 passed、1 skipped；原 PG/ObjectStore fake 回归保持通过，新增本地 MinIO 集成默认 skip。 | 无。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/services/rag/test_lightrag_server_pipeline.py -q` | 0 | 15 passed；LightRAG Server adapter 单元回归覆盖 `/query only_need_context`、references→sources、probe auth/readiness、KB config search 与 indexing refused。 | MockTransport 单元回归，不连接真实 LightRAG Server。 |
| live LightRAG Server smoke against `http://127.0.0.1:9621` using `/health`、`probe_server`、`LightRagServerClient.query_context(..., "hybrid")` 与 `LightRagServerPipeline.search(...)` | 0 | `/health` healthy；auth disabled；core `1.5.8`、api `0347`；pipeline idle；probe ok/reachable/auth_ok；client 与 pipeline 均返回 context（`content_len=74325`）和 `sources_count=2`，source basename 摘要含 `llm-agent-mt-console (1).html`、`ois-solution.md`。 | 本机用户提供的 LightRAG Server；未记录模型 host、工作目录、完整 context 或用户正文；不等同目标环境 LightRAG/KB 验收。 |
| `DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1 PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_local_minio_http_upload_intent_and_ws_resource_policy` | 0 | 1 passed；企业 ASGI HTTP API 使用本机 MinIO 完成 upload intent、pre-signed PUT、upload complete、授权下载，并由企业 WS `validate_start_turn` 接受 ready `resource_id`。 | 使用本地 MinIO `local-debug` bucket 与隔离 PG fixture；不调用真实模型，不等同目标 ObjectStore/K8s smoke。 |
| `PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q <A2/B1 targeted enterprise tests>` | 0 | 4 passed、1 skipped；覆盖资源 HTTP contract、生产 WS 拒绝 legacy payload/验证 resource refs、EduPlus2 WS auth refresh 同身份限制、audit query/export 权限；skip 为未显式开启本地 MinIO 的同一测试。 | 本地隔离 PG/ASGI 回归；真实 MinIO 版本见上一条。 |
| `DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1 PYTHONPATH=. ./.venv/bin/python -m pytest tests/persistence/postgres/business/test_externalized_object_resources.py::test_local_minio_presigned_upload_complete_read_and_delete -q` | 0 | 1 passed；底层 PG resource binding + 本机 MinIO pre-signed PUT、complete、read、delete/cleanup 和 owner 负例通过。 | 本地 MinIO，不覆盖目标 ObjectStore 权限策略。 |
| live LightRAG Server smoke against `http://127.0.0.1:9621` rerun for A2 local debug | 0 | `/health` healthy；core `1.5.8`、api `0347`；probe ok；client 与 pipeline 均返回 hybrid context（`content_len=76999`）和 `sources_count=2`。 | 本机 LightRAG Server；未记录完整 context/模型 host/工作目录；未执行目标 KB 导入/删除/恢复。 |
| `PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python scripts/enterprise/eduplus2_fronting_app_smoke.py --dry-run/--real --token-file .secrets/token-test.secrets --env-file .secrets/.local.secrets` | 2 | 配置检查 ok；real 模式下 discovery/JWKS、m2m token、client resolve 均 ok；输出未泄露 token/secret。 | `token-test.secrets` 中用户 JWT 已过期，`user_jwt=expired`，exchange/auth_refresh 真实用户路径未完成；未提供本地 DeepTutor URL 给脚本。 |
| `DT_EDUPLUS2_REAL_SMOKE=1 <env from .secrets/.local.secrets> PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python -m pytest -q extensions/enterprise/tests/test_eduplus2_real_smoke.py` | 0 | 1 passed；真实 EduPlus2 discovery/JWKS、m2m token、client resolve 正负例通过。 | 不包含真实用户 JWT exchange；不输出 Secret。 |

### 本切片仍未完成/不得勾选项

- 已通过本地 MinIO 验证真实 pre-signed URL PUT/HEAD/read/delete/owner 负例；但未通过目标 S3-compatible ObjectStore 执行 PUT，也未通过目标 ObjectStore 实测权限不足、过期 URL、public-read 拒绝、删除补偿失败等负例。
- 已在企业 production WS turn 前校验 ready resource binding，但尚未把资源 bytes/read URL 接入模型/RAG/multimodal adapter；因此不能声明“多模态模型处理音频/视频/图片”完整交付。
- 已对本机 MinIO + 企业 ASGI 资源 API + WS resource policy + 本机 LightRAG Server 执行 A2 本地调试 smoke；但未执行目标环境 ObjectStore/LightRAG binding、样本 KB 导入/ready/授权引用/删除/恢复、真实 turn 模型/RAG 消费资源、部署版本或清理补偿；A2.2/A2.4 仍阻断完整 G1。
- 未运行目标 Woodpecker + K8s smoke、真实 Ingress/TLS、release rollback 或审批门禁；A3/H/V.3 仍未完成。
- 本切片不勾选 A2.2/A2.3/A2.4/B1.2/B1.4/V.3；只作为本地 contract/API/demo 执行证据。B1 当前真实 EduPlus2 discovery/m2m/resolve 已通过；后续 2026-09-20 又通过浏览器 demo 完成真实登录、HTTP bearer probe、资源上传和 WS `start_turn.resource_ids`，但目标环境 smoke 与 B1 切换证据仍未完成。


## 待完成后续

1. 先完成目标 Woodpecker/K8s 接入契约：server/agent 版本、agent backend、受保护 ref、审批/Secret 发放边界、registry、namespace、Ingress/TLS、SecretStore、发布锁、回退和 evidence 存放位置；之后再实现真实流水线与部署源。
2. 提供受控未过期 EduPlus2 user JWT、目标 DeepTutor URL、ObjectStore 测试前缀、LightRAG 样本 KB 和模型调用预算，运行 `deeptutor_enterprise.smoke` 的真实路径。
3. 保存 release evidence：源码 SHA、upstream SHA、backend/frontend digest、schema version、Secret ref、ObjectStore/LightRAG binding 摘要、smoke run ID、审批人、rollback 结果和未验证项。
4. 对 Woodpecker/K8s 日志与 evidence 执行 secret leakage scan 后，才可勾选 V.3/V.4 的目标环境部分。
5. 用户明确确认实施完成、证据可接受并同意归档前，不执行 OpenSpec archive。

### 2026-09-19 EduPlus2 前置 demo 浏览器登录链路（local-debug）

在本机 `lightrag server: 127.0.0.1:9621`、MinIO、PostgreSQL 已启动的前提下，继续执行 `/enterprise/eduplus2/fronting-demo` 真实浏览器联调。账号来源为 `.secrets/.login-credentials`，执行过程未在 evidence 中记录账号、密码、EduPlus2 token、DeepTutor `dt_token`、cookie 或 client secret。

| 步骤 / 命令 | 结果 | 脱敏证据摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| `confirm-stopped` with temporary maintenance deployment config | 0 | stale executor lease `f077e134-33cd-489b-8082-4059605f334b` 已通过正式 CLI 标记 `stopped`；随后 `.secrets/run-local-enterprise-demo-backend.sh` 启动 enterprise backend `127.0.0.1:8001`。 | 本地恢复操作；不等同 H.2/H.3 发布排空/重叠演练。 |
| `.secrets/run-local-enterprise-demo-frontend.sh` | 0 / long-running | Next build + `next start --hostname 127.0.0.1 --port 3782` 成功；`https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo` 可达。 | 本地前端；非目标 Ingress/TLS。 |
| `curl https://deeptutor.lfun.pub/api/v1/auth/eduplus2/demo/start?...` | 303 | Next middleware 将 `/api/*` 转发到 backend；demo/start 跳转到 EduPlus2 authorization endpoint；无需修改登录页或 `local-ssl.tsv`。 | Python cert bundle 对 mkcert 仍可能不信任；浏览器路径可用。 |
| Playwright 浏览器登录 EduPlus2 测试 realm | 成功回跳 | 首次旧 state 因验证码/长时间尝试过期，返回 `state_invalid`；重新从 demo 页发起新 state 后正常回调。 | state_invalid 是 demo state TTL/重放防护预期行为，不记为成功链路。 |
| 独立 OIDC + direct exchange 诊断 | 成功定位瞬态依赖 | 使用浏览器 SSO cookie 执行 OIDC code flow：`auth_code_received=True`、`token_status=200`、selected `id_token`；JWT public diag：alg `RS256`，kid hash `sha256:66d5c17f4e4d75eb`，issuer `https://eduplus-auth-test.f123.pub/realms/eduplus`，tenant/user 为短 hash。一次 direct exchange 失败为 `RuntimeError: EduPlus2 token endpoint is unavailable`；单独 M2M resolve 在 5s timeout 下耗时约 `4.97s`，说明 demo 首次 `service_unavailable` 是本地/外部 token endpoint 5s 边界瞬态。 | 不输出 token/cookie/secret；未改代码。后续可考虑为 EduPlus2 M2M/OIDC client 增加受控 timeout 配置，避免本地外部链路贴边。 |
| 重新运行 demo 登录链路 | 成功 | Request ID `demo-7b3095b1deb9466c8d2ce5c6f387d8bb`；EduPlus2 Redirect、Authorization Code Token Exchange、DeepTutor Token Exchange、DeepTutor API Probe 均为完成；API probe `authenticated=true`、role `user`；external tenant hash `sha256:8241649609f88ccd`、external user hash `sha256:77ac7d024218f4f3`、internal user hash `sha256:2c2cb0fcc546b4f3`、client registration hash `sha256:55d6a0c2f1d3b604`。 | 本地 demo；不声明生产登录能力或目标环境 B1 完成。 |
| Demo resource section（修正前） | 可见但不完整 | 页面仅展示 `pre-signed upload → prompt + resource_ids` 说明和手动 `resource_ids` 输入；用户指出 demo 没有真实多模态/资源上传功能。 | 已确认这是 demo 缺口，不能作为“demo 体现资源链路”完成证据。 |
| Demo resource upload UI（最终位置修正后） | 可见并有自动化回归 | 独立 pre-signed upload 板块已移除；文件选择、上传并登记资源按钮、上传状态列表、SHA-256/metadata 摘要和 `resource_ids` 输入均内嵌到“真实 `/api/v1/ws` 对话测试”区域。Vitest 覆盖 upload intent → pre-signed PUT → complete → WS `resource_ids` 全链路，且过滤 forbidden `content-length` header，不把 raw/base64/URL 放入 WS。 | 此处记录的是 2026-09-19 状态；2026-09-20 已用 Playwright 浏览器对远程 MinIO path-style 完整上传和 WS `resource_ids` frame capture 复验，见下方新增小节。 |
| Playwright 点击“开始 WebSocket 对话” | 成功 | `/api/v1/ws` 状态 `open`；步骤 `DeepTutor WebSocket Chat` 完成；收到 assistant content：一句话介绍 DeepTutor；事件摘要含 `done`、`session_meta:title`、`result`、`stage_end:responding`、多条 `content/thinking`。 | 使用本地 backend/frontend 与当前模型 profile；不等同目标 Ingress/K8s smoke。 |
| Playwright 点击“立即模拟续签” | 成功 | 步骤 `Token Refresh` 完成；页面显示 `WebSocket 已确认新 dt_token（auth_ack）`，Recent WS events 首条为 `auth_ack`。 | 不记录 refresh token 或 dt_token；实时撤权 SLA/周期合法性调度仍非 M1 交付。 |

结论：在 local-debug 环境下，B1 demo 登录链路已从“静态用户 JWT 过期阻断”推进为真实浏览器 EduPlus2 登录、code exchange、DeepTutor token exchange、HTTP bearer probe、WebSocket `start_turn` 和 `auth_refresh` 全链路通过；用户指出的 demo 资源上传 UI 缺口已修正为可执行的 local/test 预上传演示。2026-09-20 已继续通过真实浏览器完成远程 MinIO pre-signed upload → complete → WS `start_turn.resource_ids` frame capture。该证据仍不替代目标 Woodpecker/K8s/Ingress/ObjectStore/LightRAG 的 G1 smoke，因此不勾选 A3、V.3，也不把 B1 标记为生产完成。

### 2026-09-20 远程 MinIO path-style 与浏览器端到端资源链路复验

用户确认 `minio.f123.pub` 是远程 MinIO 服务后，重新按远程 S3-compatible ObjectStore 调试本地 demo。执行过程未记录账号、密码、EduPlus2 token、DeepTutor `dt_token`、cookie、S3 access key/secret、pre-signed URL 签名参数或用户隐私原文。

| 步骤 / 命令 | 结果 | 脱敏证据摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| Playwright full browser E2E（修正前，证据 `output/playwright/eduplus2-live-e2e-1789835478388.json`） | 上传失败，WS 本身可完成 | `POST /api/v1/resources/upload-intents` 返回 200；浏览器随后访问 `https://study-mate.minio.f123.pub/...` 时 `Failed to fetch`。诊断 `OPTIONS` 该 URL 失败为 TLS hostname mismatch：证书不适用于 `study-mate.minio.f123.pub`。 | 根因是远程 MinIO 不支持当前 virtual-hosted-style bucket 域名证书；不是 `/api/settings/ui`、文件选择按钮或 WS 握手问题。 |
| 更新本地联调 ObjectStore binding | 完成 | `.secrets/deeptutor-local-enterprise-deployment.json` 中 `object_store.path_style=true`，后端重启后 pre-signed URL 使用 `https://minio.f123.pub/study-mate/...` 形态；未输出 S3 secret。 | 仅为本地 `.secrets` 联调配置；生产/目标环境必须用自己的 ObjectStore endpoint/cert/CORS 契约登记。 |
| Playwright full browser E2E（证据 `output/playwright/eduplus2-live-e2e-1789835637386.json`） | 0 | 真实浏览器完成 EduPlus2 登录回跳、DeepTutor API probe、点击可见“选择文件”并触发 filechooser、`POST /api/v1/resources/upload-intents`、浏览器 `PUT` 远程 MinIO、`POST /complete`、自动填充 `resource_id`、点击“开始 WebSocket 对话”、收到 `content/result/done`。无 console/request failed errors。 | 该轮证明远程 MinIO path-style 上传成功；尚未捕获 WS outgoing frame。 |
| Playwright full browser E2E with WS frame capture（证据 `output/playwright/eduplus2-live-e2e-1789835797009.json`） | 0 | `final.ok=true`；上传步骤 `Resource Upload Reference` 完成；`resourceIdsSubmitted=<present>`；`POST /api/v1/resources/upload-intents` 与 `/complete` 均 200；WebSocket URL `wss://deeptutor.lfun.pub/ws/api/v1/ws`；捕获 outgoing `start_turn` frame：`protocol_version=2.0`、`resource_ids_count=1`、`has_resource_ids=true`、`content_present=true`；incoming frames 包含 `session`、`stage_start`、多条 `thinking/content`、`result`、`session_meta:title`、`done`；页面 `DeepTutor WebSocket Chat` 完成。 | 本地 backend/frontend + 本地 HTTPS 反代 + 远程 MinIO + 当前模型 profile；不等同目标 K8s/Woodpecker/Ingress smoke。模型回复未被用作资源内容忠实性评测，仍不能声明多模态/KB/RAG 消费资源完整交付。 |
| Direct WS handshake compare after token refresh | 0 | 使用 fresh demo `dt_token` 对 `ws://127.0.0.1:8001/api/v1/ws` 与 `wss://deeptutor.lfun.pub/ws/api/v1/ws` 分别连接，均回选 `deeptutor-token` subprotocol，`ping` 收到 `pong`。 | 仅验证 WS 握手/反代/认证载体；资源 E2E 以浏览器证据为准。 |

本轮结论：local/test demo 的完整交互已经体现并实测“第三方应用先向 DeepTutor 申请 pre-signed upload URL → 浏览器直传远程 MinIO → complete 形成 DeepTutor resource binding → WebSocket `start_turn` 仅发送 `prompt + resource_ids`”。之前的浏览器上传失败根因是远程 MinIO 应使用 path-style URL，已在本地联调配置修正。该证据可以补充 B1 前置 demo/dry-run smoke 的本地证据，但仍不勾选 B1.2/B1.4，因为任务要求的是目标环境 smoke；也不勾选 A2.2/A2.4，因为仍缺目标 ObjectStore/LightRAG/KB 样本检索、引用返回、audit 关联和清理补偿的完整 G1 证据。

### 2026-09-20 本轮最终验证命令

| 命令 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx tests/eduplus2-fronting-demo-upload-picker-bridge.spec.ts` | 0 | 2 test files passed、12 tests passed；覆盖 demo 上传 UI、pre-signed PUT/complete mock、WS `resource_ids` payload 和 route cache bridge。 | Vitest mock URL；真实浏览器证据见上方 Playwright E2E。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/api/test_http_provider_context.py tests/runtime/test_s3_presign.py tests/api/test_turn_protocol_resource_refs.py tests/scripts/test_eduplus2_fronting_app_smoke.py -q` | 0 | 9 passed；覆盖 WS provider/policy hook、S3 presign、turn protocol resource refs、EduPlus2 smoke 脱敏 contract。 | 不连接目标 K8s/Woodpecker。 |
| `PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py` | 0 | 7 passed、1 skipped；企业 app auth/settings/resource/WS/TMS/OMS 边界回归通过。 | 本地隔离 PG/ASGI；skip 为未显式开启本地 MinIO 的集成项。 |
| `cd web && npm run typecheck` | 0 | 前端 TypeScript 检查通过。 | 无。 |
| `openspec validate add-m1-g1-single-tenant-production-baseline --strict && openspec validate --all --strict` | 0 | change valid；14 items passed、0 failed。 | 无。 |
| `git diff --check -- <本切片相关 tracked/untracked 路径>` | 0 | 本切片相关 diff 无 whitespace/conflict marker。 | 未把无关 `web/public/pdfjs/wasm/LICENSE_*` 纳入本切片检查。 |
| targeted secret leakage scan against tracked diff | 0 | 未发现私钥块、JWT 形态 token、S3/AWS access key、client secret、API key、DeepTutor `dt_token` 明文。 | `.secrets` 与 `output/playwright` 未纳入跟踪文件；目标环境日志仍需上线前扫描。 |

### 2026-09-20 文件选择控件不可点击复查与修正

用户反馈“选择文件”点击无反应且无日志后，重新按真实浏览器行为排查。结论：此前页面依赖 `button -> input.click()` 的 JS 代理触发隐藏 `input[type=file].sr-only`；该模式在用户浏览器/旧缓存 bridge 场景下没有可观察错误但可能不弹出文件选择器。进一步发现 cache bridge 监听 `class/aria-labelledby` 后又无条件写回相同 DOM 属性，存在 MutationObserver 自触发循环风险，会造成回跳页 effect 被饿死、`/demo/result` 不发请求。

本轮修正：

- `web/app/enterprise/eduplus2/fronting-demo/page.tsx`：移除 JS 代理“选择文件”按钮和 `input.click()`，改为可见、原生、可直接点击的 `input[type=file]`；上传仍在真实 `/api/v1/ws` 对话区域内。
- `web/lib/eduplus2-fronting-demo-upload-picker-bridge.ts`：旧缓存修复逻辑改为“移除旧代理按钮 + 露出原生 input”，并且仅在属性/类名实际不同才写 DOM，避免 MutationObserver 自触发循环。
- `web/tests/eduplus2-fronting-demo*.spec.*`：回归改为要求不出现 JS 代理“选择文件”按钮、file input 不为 `sr-only`、具备 `cursor-pointer` 原生可点击样式；旧缓存 bridge 同样不得插入代理按钮。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx -t "uses a visible native resource file input" --reporter verbose`（RED） | 1 | 失败原因为页面仍包含 `<button>选择文件</button>`，证明测试能捕获 JS 代理按钮路径。 | RED 仅用于证明回归测试有效。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo-upload-picker-bridge.spec.ts tests/eduplus2-fronting-demo.spec.tsx` | 0 | 2 test files passed、12 tests passed；fresh page 与 stale bridge 均走原生 file input，不依赖代理按钮。 | jsdom 单元/组件回归。 |
| `cd web && npm run typecheck` | 0 | 前端 TypeScript 检查通过。 | 无。 |
| `cd web && npm run build` | 0 | Next production build 成功；随后本地 `next start` 重新启动到 `127.0.0.1:3782`。 | 本地前端，不等同目标 Ingress/K8s。 |
| Playwright native picker probe（证据 `output/playwright/eduplus2-native-picker-probe-1789840021881.json`） | 0 | 真实浏览器页面中 `input[type=file]` 存在、`inputId=eduplus2-resource-upload-input`、`chooseButtonCount=0`、class 含 `cursor-pointer` 且不含 `sr-only`；点击原生 input 触发 `filechooser`，`multiple=true`；console/request failed 均为空。 | 只验证文件选择控件本身；无需 EduPlus2 登录。 |
| Playwright callback hydration probe | 0 | 使用已有脱敏 demo_session URL 加载回跳页，观察到 `/api/v1/auth/eduplus2/demo/result`、`/api/auth/status`、`/api/settings/ui` 均 200；无 console error/pageerror，证明 MutationObserver 修复后回跳页 effect 正常执行。 | 使用本地 demo_session；不记录 token。 |
| Playwright full E2E after native input fix（证据 `output/playwright/eduplus2-live-e2e-1789840072689.json`） | 1 | 未进入上传阶段；页面明确显示 `service_unavailable（eduplus2_token_endpoint_unavailable）`，Authorization Code Token Exchange 失败。该失败来自外部 EduPlus2 token endpoint 当前不可用，不是文件选择控件或资源上传控件。 | 完整登录+上传+WS 本轮未复验成功；前一次完整资源链路成功证据仍为 `eduplus2-live-e2e-1789835797009.json`。待 EduPlus2 token endpoint 恢复后需重跑完整 E2E。 |

本轮不改变 A2/B1/A3 勾选状态：文件选择控件问题已在 local/test 浏览器层修复并验证；生产/G1 仍需目标环境 Woodpecker/K8s/ObjectStore/LightRAG smoke。

### 2026-09-20 WS 无凭证错误复查与前端防护

用户反馈 WebSocket 出现 `HTTP Authentication failed; no valid credentials available` 后，复查发现后端在无有效 `Sec-WebSocket-Protocol: deeptutor-token,<jwt>` 时会按预期拒绝握手（direct anonymous WS 为 HTTP 403）。前端此前在 API probe 返回 `authenticated=false` 时仍保留内存态 `dt_token`，允许点击“开始 WebSocket 对话”，导致浏览器直接用无效 token 建 WS 并显示底层认证错误。

本轮修正：

- `web/app/enterprise/eduplus2/fronting-demo/page.tsx`：`startWsConversation()` 改为 async；当 API probe 未确认 authenticated 或 token 临近过期时，先调用 demo refresh，再使用 refreshed `dt_token` 建 WS；refresh 失败时显示中文错误并把 WS step 标记为 `auth_refresh_failed`，不再直接触发浏览器底层 HTTP auth failed。
- `web/tests/eduplus2-fronting-demo.spec.tsx`：新增回归 `refreshes a rejected demo token before opening WebSocket`，证明 API probe 拒绝旧 token 时会先调用 `/api/v1/auth/eduplus2/demo/refresh`，并且 WebSocket subprotocol 使用 refreshed token 而非旧 token。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx -t "refreshes a rejected demo token" --reporter verbose`（RED） | 1 | 失败原因为没有调用 `/api/v1/auth/eduplus2/demo/refresh`，只执行了 demo result 与 `/api/auth/status`，证明旧代码会直接尝试 WS。 | RED 仅用于证明测试能捕获该问题。 |
| 同一测试（GREEN） | 0 | 1 passed；点击 WS 前调用 refresh，WS protocols 为 `['deeptutor-token', <refreshed>]`，不包含旧 token。 | jsdom/FakeWebSocket 回归。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx tests/eduplus2-fronting-demo-upload-picker-bridge.spec.ts` | 0 | 2 test files passed、13 tests passed；覆盖资源上传 UI、原生 file input、cache bridge、WS resource_ids、rejected token refresh-before-WS。 | 前端回归，不连接真实 EduPlus2。 |
| `cd web && npm run typecheck` | 0 | 前端 TypeScript 检查通过。 | 无。 |
| `cd web && npm run build` | 0 | Next production build 成功；随后本地 backend/frontend 已重启。 | 本地前端，不等同目标 Ingress/K8s。 |
| 健康检查 | 0 | backend `127.0.0.1:8001` PID `33385`；frontend `127.0.0.1:3782` PID `33436`；`https://deeptutor.lfun.pub/api/settings/ui` 200；`/enterprise/eduplus2/fronting-demo` 200。 | 本地联调。 |
| Playwright native picker probe（证据 `output/playwright/eduplus2-native-picker-probe-1789840731826.json`） | 0 | 原生 file input 存在，`chooseButtonCount=0`，点击触发 `filechooser`，无 console/request failed。 | 未上传用户文件。 |
| Chrome 用户可见新标签 | 0 | 已打开并保留 `https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo?fresh=1`；AX 显示上传控件为原生 file input，未认证前“开始 WebSocket 对话”和“上传并登记资源”均 disabled。 | 用户仍需从该新 demo 标签重新点击“使用 EduPlus2 统一认证测试”；不要继续旧 EduPlus 登录标签的 stale state。 |

本轮仍不勾选 A2/B1/A3 目标环境任务；仅作为 local/test demo 可用性与 WS 认证防护证据。

### 2026-09-20 local-ssl WebSocket URL 构建复查

用户反馈浏览器仍尝试连接 `wss://deeptutor.lfun.pub/api/v1/ws`。复查确认：`local-ssl.tsv` 只把后端 WebSocket 挂在 `/ws` 前缀（`deeptutor.lfun.pub /ws ws 127.0.0.1:8001`），所以浏览器 bundle 必须使用 `wss://deeptutor.lfun.pub/ws/api/v1/ws`。问题根因是此前曾手动 `npm run build`，没有带 `.secrets/run-local-enterprise-demo-frontend.sh` 中的 `NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL`，旧 chunk 因而回退到了默认 `/api/v1/ws`。

本轮处理：

- 停止旧 frontend PID `33436`，使用 `.secrets/run-local-enterprise-demo-frontend.sh` 重新构建并启动 frontend；新 frontend PID `27661` 监听 `127.0.0.1:3782`。
- backend 保持 `127.0.0.1:8001`，local-ssl 路由保持 `/`→frontend、`/ws`→backend。
- 打开新的 Chrome 可测试标签：`https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo?fresh=wsfix`。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| `.secrets/run-local-enterprise-demo-frontend.sh` | 0 / long-running | Next production build 成功，`next start --hostname 127.0.0.1 --port 3782` ready；构建时带入 `NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL="wss://deeptutor.lfun.pub/ws/api/v1/ws"`。 | 本地前端；不等同目标 Ingress/K8s。 |
| built chunk 静态校验 | 0 | 新 chunk `page-34442734e5d8b2fd.js` 包含 `wss://deeptutor.lfun.pub/ws/api/v1/ws`，不包含错误的 `wss://deeptutor.lfun.pub/api/v1/ws`，也不再保留 `NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL` 运行时 env 读取。 | 旧打开标签需刷新，否则仍会运行旧 chunk `page-82cae0c4e0c0b1f8.js`。 |
| HTML chunk 引用校验 | 0 | `https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo?fresh=wsfix2` 引用新 chunk、未引用旧 chunk；页面 HTML 200。 | 浏览器强缓存/已打开 SPA tab 仍需手动刷新或使用新标签。 |
| `curl` 健康检查 | 0 | `https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo?fresh=wsfix` 返回 200；`https://deeptutor.lfun.pub/api/settings/ui` 返回 200。 | 健康检查不执行登录。 |
| refreshed demo token WS handshake | 0 | 使用 demo refresh 后的新 `dt_token` 对 `wss://deeptutor.lfun.pub/ws/api/v1/ws` 发起 WebSocket upgrade，返回 `HTTP/1.1 101 Switching Protocols` 并回选 `Sec-WebSocket-Protocol: deeptutor-token`。 | 仅验证正确 WS URL、local-ssl 反代和认证载体；不记录 token，不跑完整模型 turn。 |
| Playwright native picker probe（证据 `output/playwright/eduplus2-native-picker-probe-1789842086927.json`） | 0 | 新构建页面中原生 file input 存在，`chooseButtonCount=0`，点击触发 `filechooser`，`multiple=true`，无 console/request failed。 | 只验证选择文件控件；完整登录+上传+WS E2E 仍以前述成功证据和后续用户复测为准。 |

本轮结论：当前可测试页面已不再使用错误的 `/api/v1/ws` URL；WS 应走 local-ssl 的 `/ws/api/v1/ws`。若用户旧标签仍报 `wss://deeptutor.lfun.pub/api/v1/ws`，需要刷新或关闭旧 tab 后使用新标签，因为那是旧 chunk 的运行时状态。

### 2026-09-20 resource_ids 图片进入 LLM attachment 链路修正

用户反馈完成上传后点击“开始 WebSocket 对话”，图片没有进入对话。按 WS outbound payload 与后端链路复查，确认前端已发送 `resource_ids`，但 enterprise `SocketAuthentication.validate_start_turn()` 之后只做 ready/binding 校验，`TurnEnvironment.prepare_request()` 和 `ConfiguredTurnRuntime._run_configured_turn()` 未把 ObjectStore 中的资源读取成 `UnifiedContext.attachments`，导致后续 `AgentLoopPipeline.prepare_multimodal_messages()` 收到空附件列表，模型实际只看到文本 prompt。

本轮修正：

- `PreparedTurnEnvironment` 增加仅运行时使用的 `resource_attachments`，不写入请求、事件或消息正文。
- `extensions/enterprise` 的 turn environment 对 `resource_ids` 进行二次 ready/session/purpose 校验，读取 ObjectStore 字节并将图片资源转为 base64 `Attachment(type="image")`。
- 含图片资源时按项目能力表要求所选模型支持 vision；否则 fail closed，避免静默降级为纯文本。
- configured turn 构造 `UnifiedContext` 时传入 `prepared.resource_attachments`，并只在持久化 request snapshot 中记录 `resourceIds` 清单，不持久化图片 base64。
- 本地后端重启时发现旧进程被直接 kill 后遗留 executor lease，已使用受控 `confirm-stopped` 运维命令确认旧执行者停止，再以前台受控 session 重启后端。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| `PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_enterprise_turn_environment_materializes_image_resource_refs_for_llm`（RED） | 1 | 新增回归最初失败于 `AttributeError: 'PreparedTurnEnvironment' object has no attribute 'resource_attachments'`，证明资源在 policy 校验后没有进入 LLM attachment handoff。 | RED 仅用于证明回归测试有效。 |
| 同一测试（GREEN） | 0 | 1 passed；ready `turn_input` 图片资源被读取为 `Attachment(type='image', mime_type='image/png', filename='res_demo_image.png', base64=...)`。 | 使用隔离 ObjectStore fake，不调用真实模型。 |
| `PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_enterprise_turn_environment_materializes_image_resource_refs_for_llm extensions/enterprise/tests/test_application.py::test_enterprise_production_ws_rejects_legacy_payload_and_verifies_resource_refs extensions/enterprise/tests/test_application.py::test_enterprise_resource_upload_intent_and_ws_resource_ids_contract` | 0 | 3 passed；覆盖 pre-signed upload contract、WS policy 只接受 DeepTutor-issued `resource_ids`、后端读取图片并交给 LLM attachment context。 | 不调用外部 LLM。 |
| `PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py` | 0 | 8 passed、1 skipped；企业 app auth/settings/resource/WS/TMS/OMS 边界回归通过。 | 本地隔离 PG/ASGI；skip 为未显式开启的集成项。 |
| `./.venv/bin/python -m ruff check deeptutor/services/session/turns/environment.py deeptutor/services/session/turns/configured.py extensions/enterprise/src/deeptutor_enterprise/runtime.py extensions/enterprise/tests/test_application.py` | 0 | All checks passed。 | 仅检查本轮改动相关 Python 文件。 |
| `./.venv/bin/python -m compileall -q deeptutor/services/session/turns/environment.py deeptutor/services/session/turns/configured.py extensions/enterprise/src/deeptutor_enterprise/runtime.py` | 0 | 修改文件 Python 编译通过。 | 无。 |
| 后端重启健康检查 | 0 | 后端 PID `43814` 监听 `127.0.0.1:8001`；`http://127.0.0.1:8001/api/settings/ui` 与 `https://deeptutor.lfun.pub/api/settings/ui` 均 200；demo 页面 200。 | 后端以前台工具 session 运行；若会话结束需按受控方式停止以释放 executor lease。 |

重要限制：当前本地企业配置 `chat/primary` 是 `qwen3.7-plus`，项目能力表将其视为 text-only。修复后含图片的 turn 不会再被静默当纯文本处理，而是会在模型不支持 vision 时提前拒绝。要完成真实图片识别对话，需要把本地/目标配置切到已声明支持 vision 的模型（例如 `qwen3.8-max` 或 `qwen*-vl` 类模型），或在模型 catalog 中明确声明该模型支持 vision 后再跑完整模型 E2E。

### 2026-09-20 WS start_turn 通用错误继续排查：本地模型切换到 vision

用户继续反馈 WS 返回 `Requested operation is unavailable or invalid`。该字符串来自 enterprise WS `SocketAuthentication.error_message()` 对 `ValueError` 的安全脱敏，不是浏览器或上传控件生成。复查当前后端日志与数据库 RLS 可见数据后确认：

- 最新链路已完成 demo 登录、`upload-intents` 200、`complete` 200、WebSocket accepted。
- 最新图片资源 `res_31b0387e7a9b49bdae4b2219b86ae7e0` 为 `image/jpeg`，状态 `ready`，属于当前 EduPlus2 demo 用户。
- 当时本地企业模型仍为 `qwen3.7-plus`；项目能力表中该模型 `supports_vision=False`，因此后端 start_turn 在读取/校验图片资源后 fail closed，并由 WS 层脱敏成通用错误。

本轮本地 demo 配置处理：

- 将 `.secrets/deeptutor-local-enterprise-deployment.json` 的 `chat/primary` 从 `qwen3.7-plus` 切到项目能力表已声明支持 vision 的 `qwen3.8-max`。
- 使用 Ctrl-C 正常停止旧后端，确保 executor lease 正常释放；随后重启后端。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| 本地 deployment model capability probe | 0 | 切换前 `qwen3.7-plus supports_vision=False`；切换后 `qwen3.8-max supports_vision=True`。 | 这是本地 `.secrets` 配置调整，不属于 tracked 源码 diff。 |
| 后端级资源/模型验证脚本 | 0 | 对最新 ready 图片资源读取 ObjectStore 成功：`mime_type=image/jpeg`、`bytes_read=247308`；当前 `configured_model=qwen3.8-max`、`supports_vision=True`。 | 不触发真实 LLM 调用，因此不验证 provider 最终回答内容。 |
| 后端重启健康检查 | 0 | 后端 PID `74773` 监听 `127.0.0.1:8001`；`https://deeptutor.lfun.pub/api/settings/ui` 返回 200。 | 若前端旧 tab 保留旧 WebSocket/error state，需刷新页面后重新开始对话。 |

结论：本轮通用错误的直接原因是本地 demo 仍选中 text-only 模型；现在本地后端已切换到 vision-capable 模型，可以重新用同一 demo 页面刷新后测试完整图片对话。若 provider 侧实际不接受 `qwen3.8-max` 或账号没有该模型权限，下一步错误会变为 provider/model 调用失败，需要再按 provider 响应处理。

### 2026-09-20 WS auth_refresh 未进入后台 turn 执行上下文导致长图像 turn 被取消

用户反馈模型回复“没有收到试卷内容”。继续按真实浏览器/WS/DB 证据排查后区分出两个现象：

- 用户此前 07:58 的 turn 的 `request_snapshot.resourceIds=[]`，说明那次页面确实没有把资源引用带入 start_turn；需要使用刷新后的 demo 页，并确认 `resource_ids` 文本框中有资源 ID。
- 使用当前页面手动填入已 ready 图片资源 `res_31...` 后，浏览器实际发送帧包含 `resource_ids`，后端 turn events 中模型已读取图片内容（识别到试卷页眉和第 9/10/11 题片段），证明 ObjectStore → attachment → 多模态模型链路已可达。
- 但该完整 turn 超过本地 demo 的 60 秒 `dt_token` TTL 后，被后台授权监控取消为 `Turn authorization is no longer valid`。根因是 WS `auth_refresh` 只更新 `ws.state.enterprise_token`，没有更新 `start_turn` 时复制到后台执行任务的 ContextVar token；后台 `TurnEnvironment.authorize_request("execute")` 仍使用旧 token，长 turn 在 token 过期后被取消，UI 收不到最终 content/done。

本轮修正：

- `extensions/enterprise/src/deeptutor_enterprise/context.py` 增加 `IdentityTokenRef` 与 `bind_identity_reference()`；`current_token()` / `current_identity()` 会解引用可变认证对象。
- `SocketAuthentication.authenticate()` 在 WS 初始化时把当前 ContextVar 绑定为可变认证引用；后台任务复制 ContextVar 时复制的是同一个引用对象。
- `SocketAuthentication.revalidate()` 与 `refresh()` 在新 token 认证通过后同步更新该引用，使已启动的 turn 执行任务后续授权检查使用最新 token。
- 新增回归 `test_websocket_auth_refresh_updates_copied_turn_execution_context`，覆盖 auth_refresh 后后台复制上下文能看到新 token。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| 真实浏览器 WS resource_id 复现脚本（修复前） | 0 / 业务失败 | start_turn frame 含 `resource_ids=[res_31...]`；DB `request_snapshot.resourceIds=[res_31...]`；turn events 显示模型读取图片内容；但 60 秒左右失败为 `Turn authorization is no longer valid`，页面无 Assistant content。 | 使用现有 demo_session 与已上传图片；证明链路可达但长 turn 被旧 token 取消。 |
| `PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_websocket_auth_refresh_updates_copied_turn_execution_context`（RED） | 1 | 失败点为后台 copied context 在 refresh 后仍返回旧 token，证明测试捕获根因。 | 首次 RED 因测试夹具未配置 EduPlus2 audit provider 失败，已用最小 fake audit provider 修正后重新取得目标 RED。 |
| 同一测试（GREEN） | 0 | 1 passed；`auth.refresh()` 后，已复制的后台上下文 `current_token()` 返回 refreshed token。 | 单元级回归，不调用真实 WS。 |
| `PYTHONPATH=extensions/enterprise/src:. ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py` | 0 | 9 passed、1 skipped；企业 app auth/resource/WS/resource materialization/token refresh 回归通过。 | skip 为未显式开启的本地 MinIO 集成项。 |
| `./.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/context.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py` | 0 | All checks passed。 | 仅检查本轮改动相关文件。 |
| `./.venv/bin/python -m compileall -q extensions/enterprise/src/deeptutor_enterprise/context.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py` | 0 | Python 编译通过。 | 无。 |

下一步需要重启本地后端后再跑一次真实 WS 长 turn，确认 UI 能持续收到事件直到 done；前端旧 tab 仍需刷新以确保使用当前 bundle 与最新 token refresh 逻辑。

补充重启与真实 WS E2E 验证：

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| 正常 Ctrl-C 停止旧 backend + `.secrets/run-local-enterprise-demo-backend.sh` 重启 | 0 / long-running | 旧 PID `74773` 正常 shutdown；新 backend PID `27965` 监听 `127.0.0.1:8001`；`https://deeptutor.lfun.pub/api/settings/ui` 返回 200。 | 后端以前台工具 session 运行。 |
| 真实 HTTP upload intent → pre-signed PUT → complete → WS `/ws/api/v1/ws` start_turn E2E | 0 | 新建测试图片并上传为 ready 资源 `res_4ef1e20359264c88a2c254461b0370cf`；WebSocket 收到 `done`，`metadata.status=completed`，`assistant_message_id=59`，`user_message_id=58`；assistant 内容描述了图片中 `DeepTutor`、第 1 题 `1+1=?`、第 2 题等可见结构；`contentFrames=174`，`thinkingChars=4433`，耗时约 82 秒。 | 该 E2E 使用 admin bearer token（TTL 长于 demo dt_token）验证重启后主链路与 WS 事件转发；demo 页 60 秒 token refresh 的后台上下文问题由新增单测覆盖。测试图片使用默认字体，中文在图片中渲染为方块，因此模型只能识别英文/数字与题号结构。 |

当前结论：

- `resource_ids` 只要随 start_turn 发出，后端已能从 ObjectStore 读取图片并交给 vision 模型。
- 后端重启后，WS 订阅可以持续收到事件直到 `done(status=completed)`。
- 针对 EduPlus2 demo 60 秒 `dt_token` 的长 turn 中断问题，后台执行上下文已经改为可被 `auth_refresh` 原地更新；对应回归测试已通过。

### 2026-09-20 demo 页面重载后 resource_ids 丢失导致 WS 仍发空数组

用户继续反馈“仍然未将图片传递过去”。继续按真实 DB/日志分层排查后确认最新失败不是 ObjectStore→LLM 链路问题，而是 demo 页面在重新认证/刷新后丢失已完成上传的 `resource_id`：

- 后端日志显示最新 demo session 完成 `demo/result` 与 `/api/auth/status` 后直接建立 WebSocket；该次没有新的 `/api/v1/resources/upload-intents` 请求。
- PG 最新 turn `turn_f9571aa2af614010bd87827a086f8c1c` 的 `messages.metadata.request_snapshot.resourceIds=[]`，assistant 因此回复未收到试卷内容。
- 同一用户历史 ready 图片资源仍在 `enterprise.resource_objects` 中，但页面重载后只使用 React 内存里的 `resourceIdsInput` 构造 `start_turn`；内存状态为空时就会发送空 `resource_ids`。

本轮修正：

- demo 页面将已完成上传或用户手动填写的 `resource_id` 只保存到 `sessionStorage`（不保存 `dt_token`、URL、base64 或 S3 key），刷新/重新认证后自动恢复到“已完成上传的 resource_ids”输入区。
- `startWsConversation()` 不再只依赖 textarea 当前值，还会合并当前页面中状态为 `done` 的上传条目；即使 textarea 被清空或 React 状态未及时回填，也会把已完成上传资源加入 `start_turn.resource_ids`。
- 上传尚未完成时禁用/阻止“开始 WebSocket 对话”，避免用户在 pre-signed PUT/complete 尚未结束时发起空资源 turn。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| `cd web && npm run test:unit -- --run tests/eduplus2-fronting-demo.spec.tsx`（RED） | 1 | 新增/调整回归最初失败：清空 resource_ids textarea 后 WS payload 为 `resource_ids=[]`；页面预置 `sessionStorage` 后 textarea 仍为空。 | RED 证明测试能捕获本次根因。 |
| 同一测试（GREEN） | 0 | 1 test file passed、12 tests passed；覆盖上传完成后即使 textarea 被清空也会发送 done upload item 的 `resource_id`，以及页面重载后从 `sessionStorage` 恢复 resource_ids 并随 WS 发送。 | jsdom/FakeWebSocket；不调用真实后端。 |
| `cd web && npm run test:unit -- --run tests/eduplus2-fronting-demo-upload-picker-bridge.spec.ts` | 0 | 1 test file passed、2 tests passed；上传控件 cache bridge 回归仍通过。 | 前端单元测试。 |
| `cd web && npm run typecheck` | 0 | TypeScript 检查通过。 | 无。 |
| `cd web && npm run build` | 0 | Next production build 成功，作为前端类型/构建验证。 | 该直接构建不会烘焙 local-ssl 专用 WS URL；最终可测试前端必须使用下一行 `.secrets` 脚本重建。 |
| `.secrets/run-local-enterprise-demo-frontend.sh` | 0 / long-running | 使用 `NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL=wss://deeptutor.lfun.pub/ws/api/v1/ws` 重新 build + start；新 frontend PID `66024` 监听 `127.0.0.1:3782`；`https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo?fresh=resourcefix` 返回 200。 | 本地前端；不等同目标 K8s。前端以前台工具 session 运行。 |
| production bundle 静态校验 | 0 | 新 chunk `web/.next/static/chunks/app/enterprise/eduplus2/fronting-demo/page-1a61f1fcaf5fc959.js` 同时包含 `deeptutor.eduplus2.frontingDemo.resourceIds.v1`、`sessionStorage.getItem/setItem`、上传中阻止文案和正确 `wss://deeptutor.lfun.pub/ws/api/v1/ws`；不含错误 `wss://deeptutor.lfun.pub/api/v1/ws`。 | 静态 bundle 校验。 |
| Playwright production bundle probe | 0 | 打开 `https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo?demo_session=pw-resource-restore&fresh=resourcefix`，用浏览器预置 `sessionStorage` 与 mock token/status；页面 textarea 恢复为 `res_persisted_image`，点击“开始 WebSocket 对话”后 FakeWebSocket 捕获 `socketUrl=wss://deeptutor.lfun.pub/ws/api/v1/ws`、`resource_ids=["res_persisted_image"]`、`attachments=[]`。 | 真实本地 HTTPS 前端 + production bundle；fetch/WS 用 mock，避免记录 token 或调用真实模型。 |

当前结论：如果用户在刷新/重新认证前已经完成上传，新的 demo 页面会从同一浏览器 tab/session 的 `sessionStorage` 恢复 resource id；如果用户在当前页面刚完成上传，点击开始 WS 会从 done upload item 与 textarea 双源合并资源引用。后端已有证据证明只要 `resource_ids` 被发出，图片会进入 ObjectStore→attachment→vision 模型链路。

## 2026-09-22 A2/B1/H 本地与远程依赖收敛复验

用户确认本轮可使用 `.secrets` 中 test 密钥、远程 `minio.f123.pub`、本机 LightRAG Server `127.0.0.1:9621` 和浏览器端真实流程；MCP 暂缓，Woodpecker/K8s 与多租户仍不纳入本轮完成范围。以下证据均为脱敏摘要。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| remote ObjectStore smoke via DeepTutor `S3CompatibleObjectStore` + pre-signed PUT | 0 | endpoint host `minio.f123.pub`、bucket `study-mate`、path-style=true；900 秒 pre-signed PUT 返回 200；HEAD size/hash 与本地 payload 一致；readback 一致；delete 后再次 HEAD 不可用，清理确认。 | 未记录 signed URL、access key、secret key 或对象完整 key；短 TTL 受远端时钟影响，产品默认 900 秒通过。 |
| `DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1 PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q extensions/enterprise/tests/test_application.py::test_local_minio_http_upload_intent_and_ws_resource_policy` | 0 | 1 passed；本地 MinIO + 企业 ASGI 真实 upload intent、pre-signed PUT、complete、授权下载、WS ready resource policy 通过。 | 本地依赖补充验证。 |
| LightRAG live smoke against `http://127.0.0.1:9621` | 0 | `/health` healthy；core `1.5.8`、api `0347`；插入 mock 文档 track 进入 `DocStatus.PROCESSED`；`/query only_need_context` 检索到唯一 marker 与 `crimson-river`，`references_count=4`。 | 本机 LightRAG mock 数据；未写入完整 context 或业务正文。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest -q tests/services/rag/test_lightrag_server_pipeline.py` | 0 | 15 passed；覆盖 LightRAG Server adapter 的 `/query only_need_context`、references→sources、probe auth/readiness、KB config search 与 indexing refused。 | MockTransport 单元回归。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest -q tests/runtime/test_s3_object_store.py::test_s3_object_store_detects_remote_hash_mismatch tests/runtime/test_s3_object_store.py::test_s3_object_store_check_bucket_reports_missing_secret_without_http_or_plaintext tests/runtime/test_s3_object_store.py::test_s3_object_store_put_fails_closed_when_secret_missing` | 0 | 3 passed；覆盖 hash/checksum mismatch、Secret 缺失 fail-closed 与无明文泄露。 | Scoped negatives。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest -q tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_delete_failure_is_queryable_and_retried tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_upload_publish_failure_records_cleanup_job tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_rejects_forged_local_path_and_wrong_resource_binding tests/persistence/postgres/business/test_externalized_object_resources.py::test_object_resource_cleanup_never_deletes_ready_or_foreign_owner_objects` | 0 | 4 passed；覆盖删除补偿、publish 失败 cleanup job、伪造 local path/wrong binding 拒绝、ready/foreign owner 对象不被 cleanup 误删。 | Scoped ObjectStore/resource negatives。 |
| direct model probe for configured `qwen3.8-max` | 0 | OpenAI-compatible text call 200；32x32 红色 PNG vision call 200，返回内容命中红色语义；模型能力矩阵中当前测试模型支持 vision。 | 不记录 API key；不代表音频/视频模型编排完整交付。 |
| Playwright real browser smoke（EduPlus2 SSO → ordinary conversation test） | 0 | 完成 EduPlus2 登录回跳、HTTP options、远程 MinIO pre-signed upload → complete、WebSocket `prompt + resource_ids`、required KB `test`、assistant 图片识别回答“红色”、追问仍回答“红色”；能力清单显示 model/KB/upload 已用于回答。 | 使用本地 backend/frontend + 本地 HTTPS 反代 + 远程 MinIO；非目标 K8s/Woodpecker。 |
| `PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py extensions/enterprise/tests/test_executor.py` | 0 | 22 passed、1 skipped；覆盖 B1 HTTP/WS/auth refresh/resource boundary 与 H 单执行器租约/恢复边界。 | skip 为未显式开启 MinIO 的同一集成项，已另行开启通过。 |
| `PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q tests/agents/chat/test_required_context.py tests/services/session/test_turn_runtime_subscribe.py::test_close_drains_running_turn_before_cancelling tests/services/session/test_turn_runtime_subscribe.py::test_close_cancels_turn_after_drain_timeout` | 0 | 14 passed；覆盖 required context 和 running turn close drain/cancel。 | 本地非 HA 边界测试，不宣称高可用。 |
| targeted diff secret scan against `deeptutor`、`extensions/enterprise`、`tests`、`web`、`docs`、`openspec` | 0 | 未发现私钥块、JWT 形态 token、长 `dt_token`、明文 client secret/API key/S3 secret key。 | 运行过程中的 `.secrets` 和浏览器网络日志不纳入版本控制。 |

本轮据此勾选 A2.2/A2.3/A2.4、B1.2/B1.4、H.2/H.3。仍不勾选 A3/V.3（目标 Woodpecker + K8s smoke、发布/回退/evidence 未跑）、B2.3（多租户负例本轮按用户要求排除）和 V.6（需用户明确确认后才能归档）。

OpenSpec 与 patch 格式最终校验：

```bash
openspec validate add-m1-g1-single-tenant-production-baseline --strict
# Change 'add-m1-g1-single-tenant-production-baseline' is valid

openspec validate --all --strict
# 15 passed, 0 failed

git diff --check -- <本轮相关源码/测试/OpenSpec路径>
# exit 0
```

## 2026-09-24 conversation-test skill 补种纠偏：从本地 builtin 改为 PG + S3 用户层

用户指出上一轮测试 skill 未按约定上传到 S3，而是落在本地 `deeptutor/skills/builtin`。复查确认工作区曾出现 12 个未跟踪的本地 builtin skill 目录；这会让普通对话测试页误以为 skill 已配置，但来源是本地文件系统，不符合 A2 的 ObjectStore 外部化约定。

本轮纠偏：

- 从 `/Users/minwang/Projects/skills` 读取 12 个教学/研究/写作类测试 skill 包。
- 通过 `ExternalizedSkillService.install_tree(force=True)` 写入每个启用用户的用户层 `dynamic_skill`，即 PG `enterprise.resource_objects` 元数据 + 远程 S3/ObjectStore 对象内容。
- 删除错误产生的未跟踪本地 builtin 目录；删除前校验对应目录不在 `git ls-files` 中，且源包仍存在于 `/Users/minwang/Projects/skills`。
- 不记录 S3 credential、JWT、signed URL 或用户明文标识。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| `ExternalizedSkillService.install_tree(...)` seed 脚本 | 0 | 3 个启用用户各写入 12 个 `dynamic_skill`；`failed_or_skipped=[]`；随后通过 `ExternalizedSkillService.read_skill_file()` 读回 36 个用户层 skill。 | 这是本地联调环境的数据补种，不是目标 K8s/Woodpecker 发布。 |
| scoped PG + ObjectStore 复查脚本 | 0 | 每个用户 scoped 查询均有 `dynamic_ready_count=12`；`teach_source=user`；示例对象 key 位于 `tenants/<tenant>/owners/<owner_hash>/dynamic_skill/...`；`teach_size=18646`。 | 输出仅保留 owner hash 前缀和对象 key 前缀，不输出完整对象 key。 |
| 精确删除未跟踪本地 builtin 目录 | 0 | 已移除 `doc-coauthoring`、`grill-me`、`k12-lesson-*`、`research`、`scaffold-exercises`、`teach`、`to-*`、`writing-*` 这 12 个误放本地 builtin 目录；`git status deeptutor/skills/builtin` 不再显示这些未跟踪目录。 | 已保留 `/Users/minwang/Projects/skills` 源包。 |
| 真实后端 `/api/v1/enterprise/conversation-test/options` smoke | 0 | 使用本地进程临时 mint 的当前 tenant token 调用真实 HTTPS 后端，返回 200；12 个补种 skill 全部出现在能力清单中，总 skill 数 17。 | token 不输出、不保存；该 smoke 只验证 options 清单，不调用模型。 |

结论：普通对话测试页现在看到的 12 个测试 skill 已来自用户层 `dynamic_skill`，由 PG + S3/ObjectStore 驱动，不再依赖错误的本地 builtin 目录。

## 2026-09-24 local data 目录外部化纠偏：KB 与模型 Secret 不再依赖 `data/`

用户指出工作区仍存在 `data/` 与 `.local/.../data`，与“业务数据和资源上 PG/S3”的约定冲突。复查确认这不是单纯残留目录问题，存在两个真实运行路径仍会读本地 `data`：

- 本地企业后端启动脚本从 `.local/deeptutor-dev/home/data/user/settings/model_catalog.json` 读取 `DT_MODEL_API_KEY`。
- 普通对话测试页 options 仍通过 core `list_visible_knowledge_bases()` / `KnowledgeBaseManager` 读取本地 `data/knowledge_bases`。

本轮纠偏：

- 将 `DT_MODEL_API_KEY` 迁移到 `.secrets/.local.secrets`，启动脚本只从 Secret 文件加载，不再读取 `data/user/settings/model_catalog.json`。
- 新增企业侧 `knowledge_base_document` 元数据路径：知识库清单从 PG `enterprise.resource_objects` 读取，文档内容通过 `PostgresObjectResourceStore` 写入远程 S3/ObjectStore。
- 企业 `TurnEnvironment` 在模型调用前用 PG/ObjectStore + LightRAG binding 解析 required KB，并把 resolved KB 写入 `context_resolution`；core configured turn 不再 fallback 到本地 KB manager 扫描 `data/knowledge_bases`。
- 为企业 turn 注册受控 `rag` tool override，直接调用部署绑定的 LightRAG Server；`kb_name` 必须来自本轮已解析的 KB。
- 本地 LightRAG 调试绑定写入 ignored deployment config；生产配置仍要求 HTTPS LightRAG endpoint。
- 将旧 `data` 目录和旧 `.local/.../data*` 目录移出仓库到 `/tmp/deeptutor-local-data-archive-20260924095743`，作为临时人工回滚材料；仓库内不再保留运行态 `data` 目录。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| KB seed 脚本（PG + S3/ObjectStore） | 0 | 从旧本地 KB 样本文档一次性补种到 `knowledge_base_document`：3 个启用用户、2 个 KB、15 个文档对象；对象内容经 `PostgresObjectResourceStore.put()` 写入远程 ObjectStore，PG 记录 metadata/status。 | 仅输出计数，不输出对象 key、S3 credential、signed URL 或文档正文。 |
| `.venv/bin/python -m pytest --asyncio-mode=auto extensions/enterprise/tests/test_configuration.py tests/agents/chat/test_required_context.py::test_configured_turn_uses_pre_resolved_kb_without_local_data_probe extensions/enterprise/tests/test_application.py::test_conversation_test_options_are_authenticated_and_non_secret extensions/enterprise/tests/test_application.py::test_conversation_test_options_disable_kbs_when_rag_policy_is_not_enabled -q` | 0 | 7 passed；覆盖 local loopback LightRAG 只允许非 production、production 禁止 HTTP、configured turn 已解析 KB 时不读本地 `data`、options 使用外部化 KB 且 local KB access 被 monkeypatch 为失败仍通过。 | scoped regression。 |
| `.venv/bin/ruff check ...`（本轮 Python 源码/测试） | 0 | All checks passed。 | scoped lint。 |
| 后端/前端重启 | 0 / long-running | backend PID `83053` 监听 `127.0.0.1:8001`，frontend PID `83682` 监听 `*:3782`；`/api/settings/ui` 返回 200，`/enterprise/eduplus2/conversation-test` 返回 200。 | 以前台工具 session 运行，供本地手动测试。 |
| 临时 mint 当前 tenant token 后调用真实 `/api/v1/enterprise/conversation-test/options` | 0 | HTTP 200；`kb_count=2`、`skill_count=17`、`mcp_count=0`；KB statuses 均为 `ready`。未输出 token。 | 使用内部 smoke token，不替代 EduPlus2 浏览器登录 smoke。 |
| `find` runtime data path 复查 | 0 | 排除 `.git`、`.venv`、`web/node_modules`、`web/.next*` 后，仓库内 `data` / `.local/*/data*` / `data.*` 目录为空。重启 backend/frontend 并调用 options 后仍为空。 | `/tmp/deeptutor-local-data-archive-20260924095743` 暂存旧材料，后续确认无回滚需要后可删除。 |

结论：当前本地企业联调路径不再依赖仓库内 `data/` 作为业务状态、模型 Secret、skill 或 KB 权威；普通对话测试页展示的 KB 来自 PG + S3/ObjectStore 元数据，required KB 不会再通过 core local KB manager 读取本地文件。

## 2026-09-24 模型目录纠偏：PG 维护多模型 profile 与 secret ref，Secret provider 保存 key 明文

用户指出“模型 key 不应该只有单个 `.secrets` env；DeepTutor 支持配置多个模型，对应也应有多个 key”。本轮确认并修正设计边界：DB 不保存 key 明文；DB 保存多模型 profile、授权策略和每个 profile 的 `secret_ref`，Secret provider / K8s Secret / env 保存真正 key。

本轮改动：

- 新增企业侧 `model_catalog` 运行态读取：优先从 PG `enterprise.runtime_settings` 的 `model_catalog` 读取活动模型目录；未配置时才回退部署文件。
- `model_catalog` 中每个模型条目只记录 `secret_ref`，运行时再从 PG `enterprise.secret_references` 解析为 Secret provider 引用（当前 local 为 `env:*`）。
- `TurnEnvironment.prepare_request()` 每轮从当前 tenant PG 模型目录解析可用模型，支持同一 `profile_id` 下多个 `model_id` 和各自 secret ref。
- 本地联调 `.secrets/.local.secrets` 已补齐 per-model env 名称；启动脚本会加载所有 `DT_MODEL_API_KEY*`，不再只能加载单个固定 key 名。
- 本地 PG 已补种两个模型 profile：`chat/primary -> qwen3.8-max`、`chat/qwen37_plus -> qwen3.7-plus`，分别绑定独立 secret ref；未输出/保存 key 明文到 evidence。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| local PG seed for `runtime_settings.model_catalog` + `secret_references` | 0 | `runtime_model_catalog_seeded profiles=2 secret_refs=2 values_redacted`。 | 本地联调数据补种；生产应由 SecretStore/治理入口写入相同结构。 |
| `.venv/bin/python -m pytest --asyncio-mode=auto extensions/enterprise/tests/test_application.py::test_enterprise_turn_environment_loads_multi_model_catalog_from_pg extensions/enterprise/tests/test_configuration.py tests/agents/chat/test_required_context.py::test_configured_turn_uses_pre_resolved_kb_without_local_data_probe -q` | 0 | 6 passed；覆盖 PG 多模型目录、两个 secret ref、按 `llm_selection` 选择 advanced 模型并加载对应 key。 | scoped regression。 |
| `.venv/bin/python -m pytest --asyncio-mode=auto extensions/enterprise/tests/test_configuration.py extensions/enterprise/tests/test_application.py::test_conversation_test_options_are_authenticated_and_non_secret extensions/enterprise/tests/test_application.py::test_conversation_test_options_disable_kbs_when_rag_policy_is_not_enabled extensions/enterprise/tests/test_application.py::test_enterprise_turn_environment_loads_multi_model_catalog_from_pg tests/agents/chat/test_required_context.py -q` | 0 | 21 passed。 | targeted regression。 |
| `.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/model_catalog.py extensions/enterprise/src/deeptutor_enterprise/runtime.py extensions/enterprise/src/deeptutor_enterprise/configuration.py extensions/enterprise/tests/test_application.py` | 0 | All checks passed。 | scoped lint。 |
| direct model catalog smoke | 0 | `model_catalog_smoke model=qwen3.7-plus profiles=2 key_loaded=True`；验证 DB 目录可选中第二个模型且能经 secret ref 加载 key。 | 未输出 key 值。 |
| backend restart | 0 / long-running | backend 已重启并加载新的 `DT_MODEL_API_KEY*` env；`/api/settings/ui` 返回 200。 | 运行中本地服务。 |
| runtime data path 复查 | 0 | 正常 backend 接口访问后仓库内仍无运行态 `data/` / `.local/*/data*`。 | pytest 本身可能因 core local fixture 生成临时 `data/user/settings`，验证后已移入 `/tmp/deeptutor-local-data-archive-20260924095743`。 |

状态迁移判断：本轮未新增 DB schema；复用既有 `runtime_settings` 与 `secret_references`，因此不需要新增 SQL migration。对本地已有数据的补种是 local unblock；生产/测试环境应通过治理/SecretStore 写入同样的 `model_catalog` 与 secret refs。
