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
| Demo / dry-run smoke | `web/app/enterprise/eduplus2/fronting-demo/page.tsx`、`web/lib/eduplus2-fronting-demo.ts`、`scripts/enterprise/eduplus2_fronting_app_smoke.py` | Demo 和 dry-run smoke 展示 pre-signed upload → `prompt + resource_ids`，不输出 signed URL、token、Secret 或用户正文。 |

### 2026-09-19 命令记录

| 命令 | 退出码 | 脱敏结果摘要 | 未验证项 / 下一步 |
| --- | --- | --- | --- |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/api/test_http_provider_context.py::test_unified_ws_rejects_start_turn_when_auth_provider_denies_payload -q`（RED，实施前） | 1 | 新增测试因 `validated_payload` 未出现失败，证明 core WS 尚未调用 payload policy hook。 | TDD red，仅用于证明测试能捕获缺口。 |
| `PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py::test_enterprise_production_ws_rejects_legacy_payload_and_verifies_resource_refs -q`（RED，实施前） | 1 | 新增测试因 `SocketAuthentication` 缺少 `validate_start_turn` 失败，证明企业生产 WS policy 尚未实现。 | TDD red，仅用于证明测试能捕获缺口。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/api/test_http_provider_context.py::test_unified_ws_rejects_start_turn_when_auth_provider_denies_payload -q && PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py::test_enterprise_production_ws_rejects_legacy_payload_and_verifies_resource_refs -q` | 0 | 2 个新增回归均通过；core WS 在 start_turn 前调用可选 policy hook，企业 production 拒绝 legacy payload 并验证 ready `resource_id`。 | 不等同真实 WebSocket 目标环境 smoke。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/api/test_http_provider_context.py -q` | 0 | 3 passed；WS provider context 与 payload policy hook 回归通过。 | 不连接目标环境。 |
| `PYTHONPATH=. ./.venv/bin/python -m ruff check deeptutor/api/routers/resources.py deeptutor/api/routers/unified_ws.py deeptutor/persistence/postgres/object_resources.py deeptutor/runtime/externalized_providers.py deeptutor/core/turn_request.py extensions/enterprise/src/deeptutor_enterprise/bootstrap.py extensions/enterprise/src/deeptutor_enterprise/api/application.py scripts/enterprise/eduplus2_fronting_app_smoke.py tests/runtime/test_s3_presign.py tests/api/test_turn_protocol_resource_refs.py tests/api/test_http_provider_context.py tests/scripts/test_eduplus2_fronting_app_smoke.py extensions/enterprise/tests/test_application.py` | 0 | All checks passed。 | 无。 |
| `PYTHONPATH=extensions/enterprise/src ./.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -q` | 0 | 7 passed；企业 app 认证/CSRF/owner guard、资源 upload intent/complete、生产 WS resource policy、M1 TMS/OMS 边界回归通过。 | 不连接目标 K8s/Woodpecker。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/api/test_http_provider_context.py tests/runtime/test_s3_presign.py tests/api/test_turn_protocol_resource_refs.py tests/scripts/test_eduplus2_fronting_app_smoke.py -q` | 0 | 9 passed；S3 pre-sign、WS resource_ids 协议、dry-run smoke 资源链路和 WS policy hook 回归通过。 | 未执行真实 S3 PUT/GET。 |
| `cd web && npx vitest run tests/eduplus2-fronting-demo.spec.tsx` | 0 | 1 test file passed、8 tests passed；demo 展示并构造 `prompt + resource_ids`，不把 URL/base64 放入 WS payload。 | 不代表生产资源治理 UI。 |
| `openspec validate add-m1-g1-single-tenant-production-baseline --strict && openspec validate --all --strict` | 0 | change valid；14 items passed、0 failed。 | 已在 evidence 更新后复跑最终校验。 |
| `git diff --check` | 0 | patch 格式检查无 trailing whitespace / conflict marker。 | 工作区仍包含本 proposal 前已有 archive/delete 状态；未提交。 |
| targeted secret leakage scan against current diff | 0 | 扫描私钥块、JWT 形态 token、长 `dt_token`、明文 client secret/API key/AWS key；仅命中 `client_secret: SecretReference` 字段定义类 false positive，未发现明文 Secret/token。 | 词面字段名/Secret ref 类型不视为泄露；目标 Woodpecker/K8s 日志仍需上线前另扫。 |
| `~/.codex/skills/local-debug/scripts/local-debug.sh status minio && ~/.codex/skills/local-debug/scripts/local-debug.sh status postgres` | 0 | 本地 MinIO `http://127.0.0.1:9000` 与 PostgreSQL `localhost:5432` 均 ready；未输出 MinIO 明文凭证。 | 本地 debug 栈状态，不等同目标 K8s/ObjectStore。 |
| `~/.codex/skills/local-debug/scripts/local-debug.sh smoke minio && ~/.codex/skills/local-debug/scripts/local-debug.sh smoke postgres` | 0 | MinIO `local-debug` bucket 写读 `smoke.txt` 成功；PostgreSQL `local_debug_smoke` 插入/查询成功。 | 本地 debug smoke，不等同生产依赖验收。 |
| `DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1 PYTHONPATH=. ./.venv/bin/python -m pytest tests/persistence/postgres/business/test_externalized_object_resources.py::test_local_minio_presigned_upload_complete_read_and_delete -q` | 0 | 1 passed；通过真实本地 MinIO 验证 DeepTutor resource binding 的 pre-signed PUT、upload complete、ready reference 校验、PG owner 负例、read 与 delete/cleanup。 | 使用本机 MinIO bucket `local-debug`，未覆盖目标 ObjectStore、HTTP API/WS 全入口、LightRAG。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/persistence/postgres/business/test_externalized_object_resources.py::test_local_minio_presigned_upload_complete_read_and_delete -q` | 0 | 1 skipped；未设置 `DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1` 时默认跳过，避免 CI/普通环境依赖本机 MinIO。 | 无。 |
| `PYTHONPATH=. ./.venv/bin/python -m pytest tests/persistence/postgres/business/test_externalized_object_resources.py -q` | 0 | 9 passed、1 skipped；原 PG/ObjectStore fake 回归保持通过，新增本地 MinIO 集成默认 skip。 | 无。 |

### 本切片仍未完成/不得勾选项

- 已通过本地 MinIO 验证真实 pre-signed URL PUT/HEAD/read/delete/owner 负例；但未通过目标 S3-compatible ObjectStore 执行 PUT，也未通过目标 ObjectStore 实测权限不足、过期 URL、public-read 拒绝、删除补偿失败等负例。
- 已在企业 production WS turn 前校验 ready resource binding，但尚未把资源 bytes/read URL 接入模型/RAG/multimodal adapter；因此不能声明“多模态模型处理音频/视频/图片”完整交付。
- 未执行 LightRAG 样本 KB 导入/ready/检索/授权引用/删除/恢复；A2.2/A2.4 仍阻断完整 G1。
- 未运行目标 Woodpecker + K8s smoke、真实 Ingress/TLS、release rollback 或审批门禁；A3/H/V.3 仍未完成。
- 本切片不勾选 A2.2/A2.3/A2.4/B1.2/V.3；只作为本地 contract/API/demo 执行证据。


## 待完成后续

1. 先完成目标 Woodpecker/K8s 接入契约：server/agent 版本、agent backend、受保护 ref、审批/Secret 发放边界、registry、namespace、Ingress/TLS、SecretStore、发布锁、回退和 evidence 存放位置；之后再实现真实流水线与部署源。
2. 提供受控未过期 EduPlus2 user JWT、目标 DeepTutor URL、ObjectStore 测试前缀、LightRAG 样本 KB 和模型调用预算，运行 `deeptutor_enterprise.smoke` 的真实路径。
3. 保存 release evidence：源码 SHA、upstream SHA、backend/frontend digest、schema version、Secret ref、ObjectStore/LightRAG binding 摘要、smoke run ID、审批人、rollback 结果和未验证项。
4. 对 Woodpecker/K8s 日志与 evidence 执行 secret leakage scan 后，才可勾选 V.3/V.4 的目标环境部分。
5. 用户明确确认实施完成、证据可接受并同意归档前，不执行 OpenSpec archive。
