# add-g1-woodpecker-k8s-release-baseline 执行证据

日期：2026-09-24。范围：OpenSpec proposal 拆分与规划验证。**未触发真实 Woodpecker，未操作目标 Kubernetes/生产集群，未连接 registry、Ingress/TLS、SecretStore 或目标 release evidence store；因此不能声明 A3/G1 发布闭环完成。**

## 拆分来源

本 change 从原 `add-m1-g1-single-tenant-production-baseline` 的 A3/V.3 范围拆出，专门承接目标部署契约、Woodpecker build/push、K8s migration/deploy/smoke、rollback 和 release evidence。固定租户 runtime、resource binding、EduPlus2 demo 和 smoke harness 由 `add-m1-fixed-tenant-runtime-baseline` 提供。

## 命令记录

| 命令 | 退出码 | 摘要 | 未验证项 / 下一步 |
| --- | --- | --- | --- |
| `openspec validate add-g1-woodpecker-k8s-release-baseline --strict` | 0 | Change valid。 | 仅验证 planning artifacts；未接入目标 Woodpecker/K8s。 |
| `openspec validate --all --strict` | 0 | 16 items passed、0 failed。 | A3/D1-D5 全部仍待目标环境实施与证据。 |

## 边界结论

- Woodpecker/K8s 发布拓扑必须来自目标部署契约，不得从固定租户或多租户状态推导。
- 未登记目标契约前，只能实现契约校验、smoke/evidence 工具和待接入说明，不得用占位 pipeline/YAML 标记 A3 完成。
- 未跑真实目标环境前，只能说 proposal 已拆分并通过 OpenSpec 校验，不能宣称 G1 或生产上线完成。

## 2026-09-24 多环境/多生产环境修订验证

用户指出 Woodpecker 需要考虑不同环境部署，且可能存在多个不同生产环境。本轮将 G1 发布基线更新为环境 registry + 显式 `target_env_id` 模型：

- 每个环境登记 `env_id`、`env_class`、`prod_group`、Woodpecker/K8s/Secret/evidence/approval/release lock 契约。
- 支持多个 `env_class=prod`，逐环境审批、部署、smoke、rollback 和留证。
- 禁止默认 `prod`、歧义生产目标、跨环境 Secret/namespace/Ingress/evidence path。
- 一个生产环境通过不得替代其他生产环境。

| 命令 | 退出码 | 摘要 | 未验证项 / 下一步 |
| --- | --- | --- | --- |
| `openspec validate add-g1-woodpecker-k8s-release-baseline --strict` | 0 | Change valid。 | 仅验证 OpenSpec artifact；未接入真实 Woodpecker/K8s/多生产环境。 |
| `openspec validate --all --strict` | 0 | 16 items passed、0 failed。 | D0-D5 仍待目标环境实施与证据。 |

## 2026-09-24 deployment tag 环境解析规则修订验证

用户要求通过 tag 判断部署环境。本轮将 G1 发布基线更新为受保护 deployment tag → `target_env_id` 的强制模型：

- Canonical tag：`deploy/<env_id>/v<major>.<minor>.<patch>[-rc.<n>|-hotfix.<n>]`。
- 完整正则：`^deploy/(?P<env_id>[a-z][a-z0-9-]{1,40})/(?P<version>v[0-9]+\.[0-9]+\.[0-9]+(-(rc|hotfix)\.[0-9]+)?)$`。
- `env_id` 必须精确匹配环境 registry；禁止 `prod`/`production`/`latest`/`stable` 等歧义别名作为部署目标。
- pipeline 不接受手工覆盖环境；tag 与任何手工变量不一致时 fail closed。
- tag object SHA、commit SHA、创建者、审批记录和解析出的 `target_env_id` 必须进入 evidence。
- tag moved/reused、非 deployment tag、未保护 tag、未授权 tag、跨环境 Secret/namespace/evidence path 均必须拒绝。

| 命令 | 退出码 | 摘要 | 未验证项 / 下一步 |
| --- | --- | --- | --- |
| `openspec validate add-g1-woodpecker-k8s-release-baseline --strict` | 0 | Change valid。 | 仅验证 OpenSpec artifact；未实现真实 tag-triggered Woodpecker pipeline。 |
| `openspec validate --all --strict` | 0 | 16 items passed、0 failed。 | D0-D5 仍待目标环境与受保护 tag 规则实作验证。 |

## 2026-09-24 Woodpecker secrets 契约修订验证

用户要求 proposal 明确 Woodpecker 需要哪些 secrets。本轮将 G1 发布基线补充为按 `target_env_id` 隔离的 Woodpecker secrets/ref 矩阵：

- 必需：registry push、K8s deploy、SecretStore/ExternalSecret、PG migrator、runtime secret refs、smoke credentials、evidence store、tag/approval verify。
- 条件性：image signing/attestation、SBOM/vulnerability scanner、notification/change ticket、registry read mirror。
- 禁止：`.secrets` 内容、长期 JWT、DeepTutor `dt_token`、真实用户密码、完整生产配置、DB superuser DSN、ObjectStore root key、SecretStore root token、模型/LightRAG/EduPlus2 明文 secret。
- Pipeline 必须先做 secret preflight，检查存在性、环境归属、最小权限、轮换/过期状态和脱敏 evidence；缺失、过期、跨环境或超权时 fail closed。

| 命令 | 退出码 | 摘要 | 未验证项 / 下一步 |
| --- | --- | --- | --- |
| `openspec validate add-g1-woodpecker-k8s-release-baseline --strict` | 0 | Change valid。 | 仅验证 OpenSpec artifact；未创建真实 Woodpecker secrets。 |
| `openspec validate --all --strict` | 0 | 16 items passed、0 failed。 | D0-D5 仍待目标环境 secrets inventory/preflight 实作验证。 |

## 2026-09-24 Woodpecker 官方文档审查与 secret resolution 修订验证

用户询问“一套流水线是否可以通过替换 `<ENV_KEY>` 动态读取 secrets 来适配所有环境”。本轮查阅 Woodpecker 3.18.x 官方文档后，对 proposal/design/spec 作出以下约束修订：

- 官方支持用 tag 触发和识别环境：`CI_COMMIT_TAG` 在 tag event 中可用，`CI_PIPELINE_EVENT` 包含 `tag`，workflow 支持 `when.event: tag`、`ref` 过滤和 `evaluate` 条件。
- 官方支持在配置中用 `from_secret` 引用 Woodpecker secret，并把 secret 注入 step 环境或 plugin settings；文档示例中的 `from_secret` 是配置解析时已声明的 secret 名称，且参数表达式会在 pipeline 启动前预处理。
- 官方支持 Secret Extension：pipeline 触发时从外部服务返回 secrets，返回项的 `name` 与 pipeline config 中的 `from_secret` 匹配。
- 官方支持 Configuration Extension：pipeline 触发时可以返回新的 Woodpecker YAML 配置。
- 因此，G1 不应依赖 shell step 里先计算 `ENV_KEY` 再动态改变 `from_secret: DT_${ENV_KEY}_...` 的 secret 名称；除非目标 Woodpecker 版本实测并记录证据，否则该模式不能作为完成依据。
- 已将推荐模式改为 Secret Extension + 稳定逻辑 secret 名；备选为 Configuration Extension 生成静态 `from_secret`；native-only 兜底为按环境静态声明 secrets/steps 并用 `when.ref` 过滤。

官方文档来源：

- https://woodpecker-ci.org/docs/usage/environment
- https://woodpecker-ci.org/docs/usage/workflow-syntax
- https://woodpecker-ci.org/docs/usage/secrets
- https://woodpecker-ci.org/docs/usage/extensions/secret-extension
- https://woodpecker-ci.org/docs/usage/extensions/configuration-extension

| 命令 | 退出码 | 摘要 | 未验证项 / 下一步 |
| --- | --- | --- | --- |
| `openspec validate add-g1-woodpecker-k8s-release-baseline --strict` | 0 | Change valid。 | 仅验证 OpenSpec artifact；未接入真实 Secret Extension/Configuration Extension 或 Woodpecker server。 |
| `openspec validate --all --strict` | 0 | 16 items passed、0 failed。 | D0-D5 仍待目标环境 secrets inventory、扩展/静态配置和 tag-triggered pipeline 实作验证。 |

## 2026-09-24 本地 G1 release baseline 门禁实现

本轮实现范围：**本地可验证的发布契约、tag gate、Secret preflight、digest manifest、rollback 决策、evidence 写入/泄露扫描、示例 Woodpecker pipeline、K8s release source 与证据模板**。仍未触发真实 Woodpecker，未推送 registry，未操作目标 Kubernetes/Ingress/TLS/SecretStore/ObjectStore/LightRAG/EduPlus2 test binding，因此不得宣称任何目标环境 G1 已通过。

新增/更新的主要制品：

- `extensions/enterprise/src/deeptutor_enterprise/g1_release.py`
- `extensions/enterprise/src/deeptutor_enterprise/g1_release_cli.py`
- `extensions/enterprise/tests/test_g1_release_baseline.py`
- `extensions/enterprise/g1-release-environments.example.json`
- `.woodpecker/g1-release.yml`
- `scripts/g1/collect-secret-preflight-status.sh`
- `deploy/kubernetes/g1-release/{backend.yaml,migration-job.yaml,networkpolicy.yaml}`
- `docs/enterprise/g1-release-evidence-template.md`
- `openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-local-gates-v1/`

覆盖能力：

- 环境 registry schema：含 `test-cn`、`pre-cn`、`prod-cn-east`、`prod-overseas-a`，支持多个 `env_class=prod`，每个环境分离 tag pattern、approval policy、secret refs、K8s namespace/Ingress、locks、rollback policy 与 evidence prefix。
- Canonical deployment tag：`deploy/<env_id>/v<major>.<minor>.<patch>[-rc.<n>|-hotfix.<n>]`；非 tag event、非 canonical tag、未登记环境、歧义 `prod`、未保护 tag、生产未审批、手工环境覆盖、tag moved/reused 均 fail closed。
- Woodpecker secrets：pipeline 使用稳定逻辑 `from_secret`（如 `REGISTRY_PUSH_TOKEN`、`KUBE_DEPLOY_TOKEN`），不使用 shell 动态拼接 `DT_${ENV_KEY}` secret 名；本地 preflight 只输出存在性、环境归属、最小权限和轮换状态，不输出值。
- Build/digest/evidence：release manifest 拒绝 mutable image tag，只接受 `@sha256` digest；evidence 路径按 `target_env_id/version` 分区；泄露扫描覆盖 `.secrets`、JWT、`dt_token`、client secret、模型 key、Kubeconfig/private key/Woodpecker secret 明文等标记。
- K8s release source：示例 backend 强制 `replicas: 1` + `Recreate`，migration Job 记录 release/migration lock 与 `schema_history` drift check，NetworkPolicy 默认限制。
- Rollback：兼容旧 digest 时生成 rollback + smoke 决策；不兼容或缺旧 digest 时进入 maintenance/forward-fix、停止写入，不自动降库。

TDD 记录：

```bash
PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_g1_release_baseline.py -o asyncio_mode=auto
# RED 1：6 failed，缺少 deeptutor_enterprise.g1_release / g1_release_cli。
# GREEN 1：6 passed，完成核心门禁模块与 CLI。

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_g1_release_baseline.py::test_g1_example_registry_pipeline_and_k8s_sources_are_contract_driven \
  -o asyncio_mode=auto
# RED 2：FileNotFoundError，示例 registry/pipeline/K8s/evidence 模板缺失。
# GREEN 2：1 passed，补齐示例制品；过程中移除注释里残留的禁止片段 DT_${ENV_KEY}。

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_g1_release_baseline.py::test_secret_preflight_status_script_outputs_only_metadata \
  -o asyncio_mode=auto
# RED 3：collect-secret-preflight-status.sh 不存在，命令退出 127。
# GREEN 3：1 passed，脚本仅输出元数据，不泄露 env secret 值。

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_g1_release_baseline.py -o asyncio_mode=auto
# 8 passed
```

本地脱敏 evidence artifact：

```bash
PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m deeptutor_enterprise.g1_release_cli matrix \
  --registry extensions/enterprise/g1-release-environments.example.json \
  --output openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-local-gates-v1/matrix

scripts/g1/collect-secret-preflight-status.sh prod-cn-east \
  > openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-local-gates-v1/available-secrets-prod-cn-east.json

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m deeptutor_enterprise.g1_release_cli preflight \
  --registry extensions/enterprise/g1-release-environments.example.json \
  --target-env-id prod-cn-east \
  --available-secrets openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-local-gates-v1/available-secrets-prod-cn-east.json \
  --output openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-local-gates-v1/preflight

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m deeptutor_enterprise.g1_release_cli trigger \
  --registry extensions/enterprise/g1-release-environments.example.json \
  --event tag \
  --ref refs/tags/deploy/prod-cn-east/v1.4.0 \
  --tag deploy/prod-cn-east/v1.4.0 \
  --tag-object-sha cccccccccccccccccccccccccccccccccccccccc \
  --commit-sha aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --actor release-manager \
  --approval-id approval-local-example \
  --protected-ref --approved \
  --output openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-local-gates-v1/trigger
# 上述命令及 release evidence 生成均完成；release-evidence-scan.json ready=true。
```

重要未验证项 / 阻断：

- 未在真实 Woodpecker server/agent 上用受保护 deployment tag 触发。
- 未接入真实 Secret Extension / Configuration Extension；示例 pipeline 假定目标环境提供稳定逻辑 secret 名。
- 未实际 build/push backend/frontend 镜像，digest 为本地示例值。
- 未获取真实 release/migration lock，未执行真实 schema migration/bootstrap Job。
- 未对任何目标 K8s namespace apply/rollout，未经真实 Ingress/TLS 调用 fixed-tenant runtime smoke。
- 未演练真实 rollback/maintenance、agent interruption、registry push failure、rollout timeout、LightRAG unavailable、ObjectStore 权限不足等外部故障。
- 未验证普通 `tenant_admin`、伪造 `ops.*` scope 或跨环境用户对真实 evidence store 的访问边界。

Upstream mergeability review（V.3）：

- 本 proposal 的实现未修改 DeepTutor core runtime；新增代码集中在 `extensions/enterprise/`、`.woodpecker/`、`deploy/kubernetes/g1-release/`、`scripts/g1/`、`docs/enterprise/` 与 OpenSpec artifacts。
- 通用 seam：无新增 core seam；G1 发布逻辑通过企业扩展包 CLI/模型与外部 Woodpecker/K8s source 接入，避免在 orchestrator、session lifecycle、registry、tool/capability execution 或 persistence primitives 中硬编码 EduPlus2/tenant-specific 规则。
- Upstream merge 风险：低。风险主要在新增 `.woodpecker/g1-release.yml` 与 `deploy/kubernetes/g1-release/` 可能需随目标 Woodpecker/K8s 版本调整；不影响 upstream/main 合并 core 文件。
- 回归命令：`PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q extensions/enterprise/tests/test_g1_release_baseline.py -o asyncio_mode=auto`；后续真实环境接入前还需运行 `openspec validate add-g1-woodpecker-k8s-release-baseline --strict` 与 `openspec validate --all --strict`。

最终本地验证（实现轮次）：

```bash
./.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/g1_release.py \
  extensions/enterprise/src/deeptutor_enterprise/g1_release_cli.py \
  extensions/enterprise/tests/test_g1_release_baseline.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_g1_release_baseline.py \
  extensions/enterprise/tests/test_m1_g1_baseline.py \
  -o asyncio_mode=auto
# 23 passed

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# Change 'add-g1-woodpecker-k8s-release-baseline' is valid

openspec validate --all --strict
# Totals: 16 passed, 0 failed (16 items)
```

## 2026-09-24 code review 修复轮次

Reviewer 指出 2 个 Critical 与 4 个 Important 风险。本轮按 TDD 补充失败测试并修复：

- **Critical 1：trigger gate 不再信任 pipeline 硬编码布尔值。** `g1_release_cli trigger` 现在必须传入 `--trusted-metadata` JSON；metadata 需包含 protected ref、approval、actor、tag object SHA、commit SHA 与 trust source。`.woodpecker/g1-release.yml` 移除 `--protected-ref --approved`，改为要求外部受信 verifier 提供 metadata file；缺失时 fail closed。示例 pipeline 标注为 non-runnable skeleton，避免误导为已可生产执行。
- **Critical 2：Secret preflight collector 不再默认伪造 scope/最小权限/轮换 current。** `scripts/g1/collect-secret-preflight-status.sh` 缺少 metadata 时输出 `scope_env_id=""`、`least_privilege=false`、`rotation_state="unknown"`；`secret_preflight()` 因此 fail closed，只有 Secret Extension/SecretStore 权限系统提供显式 metadata 后才可通过。
- **Important 3：digest 绑定目标环境 registry。** `build_release_manifest()` 要求 backend/frontend digest 分别匹配当前环境 registry 的 `/backend@sha256:`、`/frontend@sha256:`；`decide_rollback()` 要求 rollback digest 匹配当前环境 backend repo。
- **Important 4：环境 registry 增强跨环境 ref 校验。** registry validator 现在检查 registry repo/credential、K8s cluster/namespace/Ingress/TLS/SecretStore/RBAC/NetworkPolicy、data plane refs、release/migration/maintenance locks、rollback previous release ref 与 evidence scopes 都含当前 `env_id`（credential ref 使用 `<ENV_KEY>`）。
- **Important 5：secret leakage scan 增强 JSON key 检测。** 对 JSON evidence 结构化扫描 `client_secret`、`*_api_key`、`password`、`authorization`、`bearer`、`kubeconfig`、`secret_value` 等敏感 key，并保留原文本模式扫描。
- **Important 6：pipeline 可执行性边界明确。** `.woodpecker/g1-release.yml` 明确为 contract skeleton；真实 digest resolve/apply/smoke/rollback/evidence scan 仍需目标 Woodpecker/K8s 接入后补齐，因此相关真实入口 tasks 继续未勾选。

RED/GREEN：

```bash
PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_g1_release_baseline.py::test_g1_release_cli_trigger_requires_trusted_metadata \
  extensions/enterprise/tests/test_g1_release_baseline.py::test_secret_preflight_status_script_outputs_only_metadata \
  extensions/enterprise/tests/test_g1_release_baseline.py::test_release_manifest_and_rollback_digest_must_match_target_env_registry \
  extensions/enterprise/tests/test_g1_release_baseline.py::test_environment_registry_rejects_cross_environment_resources \
  extensions/enterprise/tests/test_g1_release_baseline.py::test_secret_leakage_scan_detects_json_secret_keys \
  extensions/enterprise/tests/test_g1_release_baseline.py::test_g1_example_registry_pipeline_and_k8s_sources_are_contract_driven \
  -o asyncio_mode=auto
# RED：6 failed，分别覆盖无 trusted metadata、collector 伪造 metadata、digest 跨环境、跨环境 namespace/ref、JSON secret key 漏检、pipeline 硬编码 --approved/--protected-ref。
# GREEN：6 passed。

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_g1_release_baseline.py \
  extensions/enterprise/tests/test_m1_g1_baseline.py \
  -o asyncio_mode=auto
# 27 passed

./.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/g1_release.py \
  extensions/enterprise/src/deeptutor_enterprise/g1_release_cli.py \
  extensions/enterprise/tests/test_g1_release_baseline.py
# All checks passed!
```

更新后的本地脱敏 evidence artifact 位于：

`openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-local-gates-v3/`

该 artifact 使用 `trusted-trigger-metadata-prod-cn-east.json` fixture 和显式 secret metadata 生成；`release-evidence-scan.json` 为 `ready=true`。v1/v2 目录仅保留为历史尝试记录；v2 因 shell 环境变量拼接失败不作为有效证据。

Minor follow-up：补充 `deploy/kubernetes/g1-release/README.md`，明确 `deeptutor-runtime`、`deeptutor-migrator`、`deeptutor-runtime-secrets`、`deeptutor-migrator-secrets`、`deeptutor-deployment-config` 等由目标环境契约预置并由 preflight 校验，当前目录是 release-source skeleton 而非完整 cluster bootstrap 包。

最终复验（含 code review 修复与 Minor follow-up）：

```bash
./.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/g1_release.py \
  extensions/enterprise/src/deeptutor_enterprise/g1_release_cli.py \
  extensions/enterprise/tests/test_g1_release_baseline.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_g1_release_baseline.py \
  extensions/enterprise/tests/test_m1_g1_baseline.py \
  -o asyncio_mode=auto
# 27 passed

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# Change 'add-g1-woodpecker-k8s-release-baseline' is valid

openspec validate --all --strict
# Totals: 16 passed, 0 failed (16 items)
```

## 2026-09-24 semantic naming follow-up for Woodpecker/K8s release artifacts

用户指出实际流水线不能使用 `g1`/`m1` 这类里程碑编号命名，应使用语义化名称。本轮保留 OpenSpec change id `add-g1-woodpecker-k8s-release-baseline` 作为既有 proposal 身份，但将可运行/可引用的 Woodpecker/K8s release 制品改为 `protected-k8s-release`：

- `.woodpecker/protected-k8s-release.yml`
- `extensions/enterprise/protected-k8s-release-environments.example.json`
- `extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release.py`
- `extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release_cli.py`
- `extensions/enterprise/tests/test_protected_k8s_release_baseline.py`
- `scripts/protected-k8s-release/collect-secret-preflight-status.sh`
- `deploy/kubernetes/protected-k8s-release/{backend.yaml,migration-job.yaml,networkpolicy.yaml,README.md}`
- `docs/enterprise/protected-k8s-release-evidence-template.md`

语义化 artifact 已重新生成：

`openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-local-gates-v1/`

验证摘要：

```bash
PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  -o asyncio_mode=auto
# 12 passed

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m deeptutor_enterprise.protected_k8s_release_cli matrix \
  --registry extensions/enterprise/protected-k8s-release-environments.example.json \
  --output openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-local-gates-v1/matrix

scripts/protected-k8s-release/collect-secret-preflight-status.sh prod-cn-east \
  > openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-local-gates-v1/available-secrets-prod-cn-east.json

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m deeptutor_enterprise.protected_k8s_release_cli preflight \
  --registry extensions/enterprise/protected-k8s-release-environments.example.json \
  --target-env-id prod-cn-east \
  --available-secrets openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-local-gates-v1/available-secrets-prod-cn-east.json \
  --output openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-local-gates-v1/preflight
# ready=true, error_codes=[]

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m deeptutor_enterprise.protected_k8s_release_cli trigger \
  --registry extensions/enterprise/protected-k8s-release-environments.example.json \
  --event tag \
  --ref refs/tags/deploy/prod-cn-east/v1.4.0 \
  --tag deploy/prod-cn-east/v1.4.0 \
  --trusted-metadata openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-local-gates-v1/trusted-trigger-metadata-prod-cn-east.json \
  --output openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-local-gates-v1/trigger
# ready=true, trust_source=local-test-vcs-protected-tag-api

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m deeptutor_enterprise.protected_k8s_release_cli scan-evidence \
  --path openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-local-gates-v1 \
  --output openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-local-gates-v1
# ready=true, error_codes=[]
```

仍未触发真实 Woodpecker，未推送 registry，未操作目标 Kubernetes/Ingress/TLS/SecretStore/ObjectStore/LightRAG/EduPlus2 test binding；因此真实入口和生产环境完成项继续保持未勾选。

最终复验（语义化命名 follow-up 后）：

```bash
./.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release.py \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release_cli.py \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  extensions/enterprise/tests/test_m1_g1_baseline.py \
  -o asyncio_mode=auto
# 27 passed

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# Change 'add-g1-woodpecker-k8s-release-baseline' is valid

openspec validate --all --strict
# Totals: 16 passed, 0 failed (16 items)
```

## 2026-09-24 Study Mate Woodpecker shape 对齐与语义命名修复

用户确认 DeepTutor repo 已在 Woodpecker 中建立后，本轮参考 `../study-mate/.woodpecker/system-deploy.yml` 的流水线形态，对当前 `protected-k8s-release` 流水线做源侧优化。实际运行制品继续使用语义化命名 `protected-k8s-release`；proposal id 中的历史里程碑编号不扩散到 `.woodpecker/`、脚本、K8s source 或 evidence 模板名称。

源侧调整：

- `.woodpecker/protected-k8s-release.yml` 从 non-runnable skeleton 调整为可接入的 native-static baseline：pinned `plugin-git:2.8.1` clone、`workspace`/`labels`、pinned `ci-tools:alpine-3.22.4`、Kaniko `v1.14.0-debug`、`prepare-release-metadata`、逐环境静态 `from_secret` + `when.ref`、pre-deploy digest check、secret preflight、deploy/status/evidence scan。
- CLI 新增 `prepare-metadata`，复用 trusted trigger gate，生成可 `source` 的 `.deeptutor-release.env`，包含 `target_env_id`、version、release tag、image tag、release id、registry repo、evidence dir、K8s namespace/Ingress/TLS 和 lock refs；不写入 token。
- `collect-secret-preflight-status.sh` 保持缺 metadata 时 fail closed，同时支持 `SECRET_PREFLIGHT_METADATA_JSON` 由可信 Secret/SecretStore metadata 注入 scope、least privilege、rotation 和 permission summary。
- Secret preflight metadata JSON 只接受白名单元数据字段；`least_privilege` 会归一化为布尔值，字符串 `"false"` 不会被 Python truthiness 误判为通过，未知字段（例如 secret 明文字段）不会复制到输出。
- K8s source 新增 `deploy.sh` / `status.sh`；`deploy.sh` 在任何 `kubectl` 前强制 `DEEPTUTOR_DEPLOY_APPROVED=yes`，按 digest 渲染 migration/backend manifests，等待 migration Job 与 backend rollout；`status.sh` 输出 namespace scoped 状态。
- `backend.yaml` / `migration-job.yaml` 统一使用 `${DEEPTUTOR_RUNTIME_IMAGE_DIGEST}`，避免 mutable tag。
- `.dockerignore` 补充 `.secrets/`、`.codegraph/`、`.superpowers/`、`.worktrees/`、`**/.env`、`**/.env.*`，避免本地 secret/config/cache 进入 Docker build context。
- 文档 `docs/enterprise/05-woodpecker-kubernetes-pipeline.md` 补充 `prepare-metadata` 和 native-static/static secret 形态说明。

本轮 evidence artifact：

`openspec/changes/add-g1-woodpecker-k8s-release-baseline/execution-artifacts/2026-09-24-protected-k8s-release-woodpecker-study-mate-v2/`

其中：

- `pipeline-yaml-parse.txt`：`.woodpecker/protected-k8s-release.yml` 可被 YAML parser 解析，当前 18 个 steps。
- `prepare-metadata-command.json`、`.deeptutor-release.env`、`metadata/trigger-gate.json`：本地 fixture 验证 `prepare-metadata` 输出可 source 且 trigger gate ready。
- `semantic-name-scan.txt`：当前运行制品未命中 `g1/m1` 命名、`NON-RUNNABLE`、`DT_${ENV_KEY}`、`--approved`、`--protected-ref` 或 `deploy/prod/**` 等禁止模式。
- `verification-summary.txt`：记录本轮已完成的测试与检查摘要。

本轮验证命令：

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
pipeline = yaml.safe_load(Path('.woodpecker/protected-k8s-release.yml').read_text(encoding='utf8'))
print(type(pipeline).__name__, len(pipeline.get('steps', [])))
PY
# dict 18

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  -o asyncio_mode=auto
# 14 passed

./.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release.py \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release_cli.py \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  extensions/enterprise/tests/test_m1_g1_baseline.py \
  -o asyncio_mode=auto
# 29 passed

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests -o asyncio_mode=auto
# 240 passed, 3 skipped
```

真实环境边界：本轮仍未在 Woodpecker server 上触发 tag run，未推送 registry，未连接真实 K8s/Ingress/TLS/SecretStore/ObjectStore/LightRAG/EduPlus2 test binding，未实测 rollback/maintenance。因此 D2.2、D3.2、D4.2、D5.2 等真实入口任务保持未勾选，不能宣称任何目标环境已完成生产发布。

### 2026-09-24 test-cn secret 规划收敛：优先复用现有 global secrets，禁止 Helm 部署路径

用户明确原则：已有 Woodpecker global secrets 可满足时，不再为 DeepTutor repo 建立同义 repo-level alias；当前部署必须走原生 Kubernetes YAML，不使用 Helm。本轮对 test-cn 首跑规划做如下收敛：

- `REGISTRY_PUSH_USERNAME` / `REGISTRY_PUSH_TOKEN` 直接引用 global `DOCKER_USERNAME` / `DOCKER_PASSWORD`。
- `KUBECONFIG` 和 logical `KUBE_DEPLOY_TOKEN` 均引用 global `kubeconfig_test`，作为原生 `kubectl` deploy credential；不再引用 `helm_deploy_api_token`。
- `.secrets/woodpecker-secrets/test.secrets` 仅保留 repo 需要新建或派生的 test-cn secrets；对已由 global 满足的项只保留注释说明，不创建 repo alias。
- `deploy/kubernetes/protected-k8s-release/deploy.sh` 仍只执行 `kubectl apply/wait/rollout status` 原生 YAML 路径。

覆盖检查结果：test-cn 相关 `from_secret` 共 14 个；11 个由 `.secrets/woodpecker-secrets/test.secrets` 规划文件提供，3 个由 Woodpecker global secrets 提供（`DOCKER_USERNAME`、`DOCKER_PASSWORD`、`kubeconfig_test`），缺失 0。`helm` / `helm_deploy_api_token` 在当前 test-cn 流水线、规划文件和相关测试中不再出现。

### 2026-09-24 test-cn secret 生成脚本固化

本轮新增 `scripts/protected-k8s-release/prepare-test-woodpecker-secrets.py`，将此前临时生成 `.secrets/woodpecker-secrets/test.secrets` 的逻辑固化为可复跑脚本。脚本遵循以下规则：

- 已存在的 Woodpecker global secrets（`DOCKER_USERNAME`、`DOCKER_PASSWORD`、`kubeconfig_test`）只在输出文件中以注释标识，不生成 repo-level alias。
- test-cn registry push、kubectl deploy credential 均直接由流水线 `from_secret` 引用 global secret。
- 脚本只为缺少 global 来源或需要派生/随机生成的 test-cn 项输出 repo secret 条目。
- 输出文件权限设置为 `0600`。
- 输出不包含 Helm 部署路径；当前 deploy 脚本仍只使用原生 Kubernetes YAML + `kubectl apply/wait/rollout status`。

新增脚本的 TDD 记录：先新增 `test_prepare_test_woodpecker_secrets_prefers_existing_global_kubectl_and_registry`，RED 为脚本不存在；实现脚本后转绿，并修正输出说明中残留的 Helm 字样。

验证摘要：

```bash
PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  -o asyncio_mode=auto
# 15 passed

./.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release.py \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release_cli.py \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  scripts/protected-k8s-release/prepare-test-woodpecker-secrets.py
# All checks passed!
```

### 2026-09-24 native K8s YAML placeholder quoting 与可解析性核对

用户追问 K8s YAML 是否已准备好后，补充做了源 YAML 级别检查。先新增回归测试，确认未加引号的 flow-style placeholder 会导致 YAML parser 在 `backend.yaml` 的 Ingress `hosts: [${DEEPTUTOR_INGRESS_HOST}]` 处失败；随后将 K8s manifest 中 release-time placeholder 统一加引号，避免原始模板和渲染后 YAML 因 `${...}` / digest / host / lock ref 字符串被误解析。

覆盖对象：

- `deploy/kubernetes/protected-k8s-release/backend.yaml`：Deployment / Service / Ingress，按 digest、release id、target env、Ingress host/TLS secret 渲染。
- `deploy/kubernetes/protected-k8s-release/migration-job.yaml`：migration/bootstrap Job，按 digest、release id、target env 和 release/migration lock ref 渲染。
- `deploy/kubernetes/protected-k8s-release/networkpolicy.yaml`：native NetworkPolicy baseline。

新增测试：

- `test_protected_k8s_yaml_sources_parse_before_and_after_release_substitution`：对三个 YAML 源文件同时验证“模板源可被 YAML parser 解析”和“release 变量替换后仍可被 YAML parser 解析”，并确认 source/rendered 的 kind 列表一致。

验证摘要：

```bash
PYTHONPATH=. pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_yaml_sources_parse_before_and_after_release_substitution -q
# RED: yaml.parser.ParserError: expected ',' or ']', but got '{' at hosts: [${DEEPTUTOR_INGRESS_HOST}]

PYTHONPATH=. pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_yaml_sources_parse_before_and_after_release_substitution -q
# 1 passed

python3 - <<'PY'
from pathlib import Path
from string import Template
import yaml
root=Path('deploy/kubernetes/protected-k8s-release')
values={
 'DEEPTUTOR_RUNTIME_IMAGE_DIGEST':'registry.example/deeptutor/test-cn/runtime@sha256:'+'1'*64,
 'DEEPTUTOR_RELEASE_ID':'test-cn-v1.4.0',
 'DEEPTUTOR_TARGET_ENV_ID':'test-cn',
 'DEEPTUTOR_INGRESS_HOST':'deeptutor-test-cn.example.internal',
 'DEEPTUTOR_TLS_SECRET_NAME':'deeptutor-test-cn-tls',
 'DEEPTUTOR_RELEASE_LOCK_REF':'postgres:test-cn/release_locks',
 'DEEPTUTOR_MIGRATION_LOCK_REF':'postgres:test-cn/migration_locks',
}
for path in sorted(root.glob('*.yaml')):
    source_docs=[doc for doc in yaml.safe_load_all(path.read_text(encoding='utf8')) if doc]
    rendered_docs=[doc for doc in yaml.safe_load_all(Template(path.read_text(encoding='utf8')).safe_substitute(values)) if doc]
    print(path.name, [(d.get('kind'), d.get('metadata',{}).get('name')) for d in rendered_docs])
PY
# backend.yaml [('Deployment', 'deeptutor-backend'), ('Service', 'deeptutor-backend'), ('Ingress', 'deeptutor-backend')]
# migration-job.yaml [('Job', 'deeptutor-protected-k8s-release-migrate-test-cn-v1.4.0')]
# networkpolicy.yaml [('NetworkPolicy', 'deeptutor-protected-k8s-release-default-deny')]

bash -n deploy/kubernetes/protected-k8s-release/deploy.sh
bash -n deploy/kubernetes/protected-k8s-release/status.sh
# shell syntax OK

PYTHONPATH=. ./.venv/bin/python -m pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 16 passed

./.venv/bin/python -m ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py deploy/kubernetes/protected-k8s-release --select E,F,I,UP,B
# All checks passed!

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# Change 'add-g1-woodpecker-k8s-release-baseline' is valid

openspec validate --all --strict
# Totals: 16 passed, 0 failed (16 items)
```

边界：本轮验证仍是源侧/模板侧与本地 parser/shell 检查，尚未携带真实 test-cn kubeconfig 对 API server 执行 server-side dry-run 或真实 apply；因此真实 K8s/Ingress/TLS/RBAC/SecretStore 可达性仍属于 D1.2/D3.2 的未验证项。

### 2026-09-24 多副本执行拓扑、HPA overlay 与运行态一致性门禁

用户确认 `backend_executor_replicas` 需要允许大于 1，并要求评估程序在多副本下的一致性问题。本轮结论与调整：

- 发布契约新增 `runtime_coordination` 与 `autoscaling` 字段；`backend_executor_replicas>1` 或 HPA 必须声明 `rolling-replicated-agent`、Redis coordination、共享 turn lease、fencing token、共享事件/命令流、worker-lost recovery 与一致性 evidence ref，否则 fail closed。
- `backend.yaml` 的 `replicas` 改为由 `DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS` 渲染，`DEEPTUTOR_EXECUTION_MODE` 随拓扑渲染为 `single` / `replicated`，并注入 `DEEPTUTOR_TURN_COORDINATION_BACKEND`、`DEEPTUTOR_REDIS_KEY_PREFIX`。
- 新增原生 Kubernetes HPA overlay：`deploy/kubernetes/protected-k8s-release/patches/autoscaling/hpa.yaml`；`deploy.sh` 仅在 `DEEPTUTOR_HPA_ENABLED=true` 时 `kubectl apply`，不引入 Helm。
- `deploy.sh` 在任何 `kubectl` 前检查 replicas/HPA 与 execution mode、coordination backend 的一致性；多副本或 HPA 缺 Redis 时直接失败。
- 程序运行态同步调整：企业组合根现在从环境变量构造 coordination 配置，不读取/创建本地 runtime settings；Redis coordination 模式下不再获取单执行者 `ExecutorLease`，避免多 Pod 被应用层 advisory lock 退化为单实例。
- Redis coordination 模式下启动恢复改为只处理 Redis 已过期 turn lease；不会把其他 Pod 正在执行的 nonterminal turn 批量标为 `worker_lost`。单副本 memory 模式继续保持旧的单执行者 lease + 显式 crash recovery 语义。

TDD 记录：

```bash
.venv/bin/python -m pytest extensions/enterprise/tests/test_enterprise_runtime_coordination.py -q
# RED 1：3 failed，缺少 _build_enterprise_runtime_coordination，enterprise bootstrap 仍无法按 env 构造 Redis coordination。
# GREEN 1：3 passed，完成 env-driven memory/Redis coordination 构造。

.venv/bin/python -m pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_release_cli_prepares_sourceable_release_metadata extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_yaml_sources_parse_before_and_after_release_substitution -q
# RED 2：2 failed，release metadata 未输出 DEEPTUTOR_EXECUTION_MODE，backend YAML 仍固定 single。
# GREEN 2：2 passed，execution mode 按单副本/多副本拓扑渲染。

.venv/bin/python -m pytest extensions/enterprise/tests/test_enterprise_runtime_coordination.py -q
# RED 3：2 failed，Redis coordination 模式仍缺少禁用 singleton ExecutorLease 的 helper，startup recovery 仍会批量失败 nonterminal turns。
# GREEN 3：5 passed，Redis 模式不需要 singleton lease，recover() 只走 Redis expired-lease recovery。
```

本轮验证摘要：

```bash
.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  extensions/enterprise/tests/test_enterprise_runtime_coordination.py -q
# 23 passed

.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -q
# 25 passed, 1 skipped

.venv/bin/python -m pytest extensions/enterprise/tests/test_process_rebuild.py::test_full_process_file_guard_and_explicit_crash_rebuild -q
# 1 passed

.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/bootstrap.py \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release.py \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release_cli.py \
  extensions/enterprise/tests/test_enterprise_runtime_coordination.py \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  scripts/protected-k8s-release/prepare-test-woodpecker-secrets.py
# All checks passed!

python3 - <<'PY'
from pathlib import Path
from string import Template
import yaml
root = Path('deploy/kubernetes/protected-k8s-release')
values = {
    'DEEPTUTOR_RUNTIME_IMAGE_DIGEST': 'registry.example/deeptutor/test-cn/runtime@sha256:' + '1' * 64,
    'DEEPTUTOR_RELEASE_ID': 'test-cn-v1.4.0',
    'DEEPTUTOR_TARGET_ENV_ID': 'test-cn',
    'DEEPTUTOR_INGRESS_HOST': 'deeptutor-test-cn.example.internal',
    'DEEPTUTOR_TLS_SECRET_NAME': 'deeptutor-test-cn-tls',
    'DEEPTUTOR_RELEASE_LOCK_REF': 'postgres:test-cn/release_locks',
    'DEEPTUTOR_MIGRATION_LOCK_REF': 'postgres:test-cn/migration_locks',
    'DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS': '3',
    'DEEPTUTOR_EXECUTION_MODE': 'replicated',
    'DEEPTUTOR_TURN_COORDINATION_BACKEND': 'redis',
    'DEEPTUTOR_REDIS_KEY_PREFIX': 'deeptutor-test-cn',
    'DEEPTUTOR_HPA_MIN_REPLICAS': '3',
    'DEEPTUTOR_HPA_MAX_REPLICAS': '12',
    'DEEPTUTOR_HPA_TARGET_CPU_UTILIZATION_PERCENTAGE': '70',
}
for rel in ('backend.yaml', 'migration-job.yaml', 'networkpolicy.yaml', 'patches/autoscaling/hpa.yaml'):
    path = root / rel
    source_docs = [doc for doc in yaml.safe_load_all(path.read_text(encoding='utf8')) if doc]
    rendered_docs = [doc for doc in yaml.safe_load_all(Template(path.read_text(encoding='utf8')).safe_substitute(values)) if doc]
    print(rel, [(d.get('kind'), d.get('metadata', {}).get('name')) for d in rendered_docs])
    assert [d['kind'] for d in source_docs] == [d['kind'] for d in rendered_docs]
PY
# backend.yaml [('Deployment', 'deeptutor-backend'), ('Service', 'deeptutor-backend'), ('Ingress', 'deeptutor-backend')]
# migration-job.yaml [('Job', 'deeptutor-protected-k8s-release-migrate-test-cn-v1.4.0')]
# networkpolicy.yaml [('NetworkPolicy', 'deeptutor-protected-k8s-release-default-deny')]
# patches/autoscaling/hpa.yaml [('HorizontalPodAutoscaler', 'deeptutor-backend')]

bash -n deploy/kubernetes/protected-k8s-release/deploy.sh
bash -n deploy/kubernetes/protected-k8s-release/status.sh
# shell syntax OK

.venv/bin/python -m pytest extensions/enterprise/tests -q
# 249 passed, 3 skipped

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# Change 'add-g1-woodpecker-k8s-release-baseline' is valid

openspec validate --all --strict
# Totals: 16 passed, 0 failed (16 items)
```

仍未验证项：尚未在真实 Woodpecker server 上触发受保护 deployment tag run，未连接真实 test-cn K8s API 做 server-side dry-run/apply，未实测 Redis SecretStore 注入、真实 HPA metrics、真实 Ingress/TLS smoke 或多 Pod 并发 turn 压测。因此 D1.2/D2.2/D3.2/D4.2/D5.2 等真实入口任务仍不勾选，不能宣称目标环境发布闭环完成。

### 2026-09-24 Woodpecker test-cn secrets、K8s 预置与原生 YAML server-side dry-run

本轮按用户确认继续推进 test-cn 首次真实流水线前置准备，仍未触发受保护 deployment tag run。

Woodpecker 状态（仅记录名称/范围，不记录 secret value）：

- Repo：`LFunTech/DeepTutor` 已在 Woodpecker 中启用；当前尚无历史 pipeline run。
- 已写入 repo-level tag secrets：
  - `DT_RELEASE_TRUSTED_TRIGGER_METADATA_JSON`
  - `DT_TEST_CN_SECRETSTORE_ROLE`
  - `DT_TEST_CN_PG_MIGRATOR_DSN`
  - `DT_TEST_CN_APP_DB_SECRET_REF`
  - `DT_TEST_CN_OBJECTSTORE_SECRET_REF`
  - `DT_TEST_CN_LIGHTRAG_API_SECRET_REF`
  - `DT_TEST_CN_EDUPLUS2_CLIENT_SECRET_REF`
  - `DT_TEST_CN_SMOKE_TOKEN_ISSUER_SECRET`
  - `DT_TEST_CN_EVIDENCE_STORE_WRITE_TOKEN`
  - `DT_TEST_CN_VCS_TAG_VERIFY_TOKEN`
  - `DT_TEST_CN_SECRET_PREFLIGHT_METADATA_JSON`
- test-cn registry push 与 K8s deploy 不新增 repo 专属 secrets，复用 global secrets：`DOCKER_USERNAME`、`DOCKER_PASSWORD`、`kubeconfig_test`。
- Org-level 仅看到通用/其他项目 secret 名称，未作为本次 DeepTutor test-cn pipeline 的 registry/kube 主凭证来源。

Kubernetes test 环境状态（目标 env=`test`，context=`default`，namespace=`deeptutor-test-cn`；不输出 Secret data）：

- 已创建/确认 namespace：`deeptutor-test-cn`。
- 已预置对象：
  - ServiceAccount：`deeptutor-runtime`、`deeptutor-migrator`
  - Secret：`deeptutor-runtime-secrets`、`deeptutor-migrator-secrets`、`deeptutor-registry-pull`
  - ConfigMap：`deeptutor-deployment-config`
- 注意：本轮临时预置的 Secret metadata 尚缺 `deeptutor.ai/environment` / `deeptutor.ai/managed-by` 标签；不影响 Kubernetes 引用，但正式环境预置脚本化时应补齐标签以方便审计与防跨环境误用。

本轮发现并修复的发布源问题：

- `deploy.sh` 之前没有 apply `networkpolicy.yaml`，导致 NetworkPolicy 文件存在但真实发布路径未启用。现已在 migration Job 前 apply 原生 NetworkPolicy。
- `networkpolicy.yaml` 补充 DNS、PostgreSQL、HTTPS、Redis coordination egress 端口，避免 default-deny 阻断运行态必要依赖。
- migration Job 原名称 `deeptutor-protected-k8s-release-migrate-${DEEPTUTOR_RELEASE_ID}` 在长环境名/语义版本下会超过 Kubernetes label/name 限制。现改为 `dt-migrate-${DEEPTUTOR_RELEASE_ID}`。
- `DEEPTUTOR_RELEASE_ID` 改为 Kubernetes DNS-label 安全 token，例如 `prod-cn-east-v1-4-0`；原始语义版本仍保留在 `DEEPTUTOR_RELEASE_VERSION` / `DEEPTUTOR_RELEASE_TAG` 中。
- migration Job command 增加固定租户 bootstrap：当 `DEEPTUTOR_BOOTSTRAP_ADMIN_USERNAME` 存在时，要求 `DEEPTUTOR_BOOTSTRAP_ADMIN_PASSWORD` 并执行 `deeptutor-enterprise ... bootstrap --password-env DEEPTUTOR_BOOTSTRAP_ADMIN_PASSWORD`。

新增/更新 TDD 断言：

```bash
PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_example_registry_pipeline_and_k8s_sources_are_contract_driven -q
# RED：deploy.sh 未包含 render_manifest "${manifest_dir}/networkpolicy.yaml"
# GREEN：1 passed

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_yaml_sources_parse_before_and_after_release_substitution -q
# RED：prod-overseas-a-v1.4.0-hotfix.1 migration Job name 长度为 71，超过 63
# GREEN：1 passed，Job name 改为 dt-migrate-prod-overseas-a-v1-4-0-hotfix-1
```

真实 test 集群 server-side dry-run（未持久化 Deployment/Job/Ingress/HPA）：

```bash
kubectl --kubeconfig /Users/minwang/.kube/test-config --context default \
  -n deeptutor-test-cn apply --dry-run=server -f -
# networkpolicy.yaml: networkpolicy.networking.k8s.io/deeptutor-protected-k8s-release-default-deny created (server dry run)
# migration-job.yaml: job.batch/dt-migrate-prod-overseas-a-v1-4-0-hotfix-1 created (server dry run)
# backend.yaml: deployment.apps/deeptutor-backend created (server dry run); service/deeptutor-backend created (server dry run); ingress.networking.k8s.io/deeptutor-backend created (server dry run)
# patches/autoscaling/hpa.yaml: horizontalpodautoscaler.autoscaling/deeptutor-backend created (server dry run)
```

本轮最终验证摘要：

```bash
.venv/bin/ruff check \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release_cli.py \
  extensions/enterprise/src/deeptutor_enterprise/bootstrap.py \
  extensions/enterprise/tests/test_enterprise_runtime_coordination.py \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  deploy/kubernetes/protected-k8s-release \
  scripts/protected-k8s-release
# All checks passed!

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# protected-k8s-release.yml lint passes with warning:
# clone.git Specified clone image does not match allow list, netrc is not injected
# 该 clone image 与 ../study-mate/.woodpecker/system-deploy.yml 一致，暂记录为平台 allow-list 警告。

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py extensions/enterprise/tests/test_enterprise_runtime_coordination.py -q
# 23 passed

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests -q
# 249 passed, 3 skipped

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# Change 'add-g1-woodpecker-k8s-release-baseline' is valid

openspec validate --all --strict
# Totals: 16 passed, 0 failed (16 items)
```

当前边界与下一步：

- 已完成：test-cn repo/global secret 映射、test namespace 基础对象预置、原生 Kubernetes YAML server-side dry-run、Woodpecker YAML lint、本地测试与 OpenSpec strict validation。
- 未完成：尚未 commit/push proposal 相关变更；尚未推送 `deploy/test-cn/v...` tag，因此 Woodpecker build/push/migration/deploy/smoke/rollback/evidence 真实入口任务仍未完成。
- 由于工作区包含其他未关联修改，后续若触发流水线，应使用精确 path staged commit，不能 `git add .`。

补充边界：`DT_RELEASE_TRUSTED_TRIGGER_METADATA_JSON` 当前来自 `.secrets/woodpecker-secrets/test.secrets` 的静态 JSON，字段包含 `protected_ref`、`approved`、`approval_id`、`actor`、`tag_object_sha`、`commit_sha`、`trust_source`。这足以让 baseline gate 读取“受信元数据”并验证字段/格式，但尚未接入实时 VCS protected-tag/approval API，因此不能把首次 test-cn run 解释为完整生产级 tag protection 验证。正式化时应由受信 verifier 在 tag 创建后动态写入或挂载该 metadata。

### 2026-09-24 test-cn pipeline #1 首跑失败与修复

已推送 commit `1edfeab59d61e1dd6760ea7c2487509c117123ad` 并创建 tag `deploy/test-cn/v1.4.0-rc.1`。Woodpecker pipeline `#1` 被触发，但在 `validate-release-trigger` 失败，后续步骤 skipped。

失败日志摘要（不含 secret value）：

```text
trusted metadata is required; do not infer protection or approval in YAML
```

根因：Woodpecker repo-level secret 名称在实际 repo 中被规范化为小写，例如 `dt_release_trusted_trigger_metadata_json`，而 pipeline 使用 `from_secret: DT_RELEASE_TRUSTED_TRIGGER_METADATA_JSON`。因此 `TRUSTED_TRIGGER_METADATA_JSON` 未被注入。

修复：`.woodpecker/protected-k8s-release.yml` 中所有 `DT_*` repo-level `from_secret` 引用改为小写；global secrets 维持现状：`DOCKER_USERNAME`、`DOCKER_PASSWORD`、`kubeconfig_test`。

验证：

```bash
woodpecker-cli repo secret ls LFunTech/DeepTutor
# repo secrets 显示为 dt_release_trusted_trigger_metadata_json、dt_test_cn_* 小写名称

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_example_registry_pipeline_and_k8s_sources_are_contract_driven -q
# 1 passed
```

下一次触发必须使用新 tag，例如 `deploy/test-cn/v1.4.0-rc.2`；不移动已失败的 `rc.1` tag。

### 2026-09-24 test-cn pipeline #3 失败与二次修复

在重新写入非空 repo secrets 后，重新触发 `deploy/test-cn/v1.4.0-rc.2` 生成 Woodpecker pipeline `#3`，仍在 `validate-release-trigger` 失败。

失败表现：日志仍显示 `test -n ""`。进一步对照 Woodpecker Secrets 文档后确认真正根因：Woodpecker 会在 pipeline 启动前预处理 `${VAR}` 表达式；在 commands 中使用 secret 环境变量必须写成 `$${VAR}`，否则 `${TRUSTED_TRIGGER_METADATA_JSON:-}` 会被预处理为空字符串。

修复：

- `.woodpecker/protected-k8s-release.yml` 的 `validate-release-trigger` 和 `prepare-release-metadata` 中，将运行时 secret 判断从 `${TRUSTED_TRIGGER_METADATA_JSON:-}` / `${PROTECTED_K8S_RELEASE_TRUSTED_METADATA_FILE:-}` 改为 `$${TRUSTED_TRIGGER_METADATA_JSON:-}` / `$${PROTECTED_K8S_RELEASE_TRUSTED_METADATA_FILE:-}`。
- 保留 shell 本地变量与普通 `$VAR` 形式，不额外泄露 secret。

验证：

```bash
woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_example_registry_pipeline_and_k8s_sources_are_contract_driven -q
# 1 passed

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已失败 tag。

### 2026-09-24 test-cn pipeline #4 失败与三次修复

`deploy/test-cn/v1.4.0-rc.3` 触发 Woodpecker pipeline `#4` 后，`validate-release-trigger` 已不再被 `${VAR}` 预处理为空阻断，进入 Python CLI，但失败于 ci-tools 镜像缺少运行 CLI 所需的 `pydantic`：

```text
ModuleNotFoundError: No module named 'pydantic'
```

修复：所有运行 `deeptutor_enterprise.protected_k8s_release_cli` 的 ci-tools 步骤在调用前安装最小依赖 `pydantic>=2,<3`。该依赖仅用于 release gate/preflight/evidence scan 的 Pydantic registry 模型校验，不安装 DeepTutor 全量运行依赖。

验证：

```bash
woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_example_registry_pipeline_and_k8s_sources_are_contract_driven -q
# 1 passed

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

### 2026-09-24 test-cn pipeline #6 失败与四次修复

`deploy/test-cn/v1.4.0-rc.4` 触发 Woodpecker pipeline `#6` 后，`validate-release-trigger` 在安装 `pydantic` 时失败：

```text
ERROR: Could not install packages due to an OSError: Missing dependencies for SOCKS support.
```

根因：ci-tools 运行环境继承了 SOCKS proxy 相关环境变量，但 pip 环境缺少 SOCKS 支持。修复为 pip 安装 release gate 最小依赖时显式禁用 proxy：`python -m pip install --proxy "" --no-cache-dir --break-system-packages 'pydantic>=2,<3'`。

验证：

```bash
woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_example_registry_pipeline_and_k8s_sources_are_contract_driven -q
# 1 passed

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

### 2026-09-24 test-cn pipeline #7 失败与五次修复

`deploy/test-cn/v1.4.0-rc.6` 触发 Woodpecker pipeline `#7` 后，pip 仍报 SOCKS support 缺失。`--proxy ""` 未覆盖运行环境中的 proxy 变量。

修复：pip 安装命令改为通过 `env -u` 显式清除 `SOCKS_PROXY/socks_proxy/ALL_PROXY/all_proxy/HTTPS_PROXY/https_proxy/HTTP_PROXY/http_proxy` 后再执行安装。

验证：

```bash
woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_example_registry_pipeline_and_k8s_sources_are_contract_driven -q
# 1 passed

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

### 2026-09-24 test-cn pipeline #9 卡在在线依赖安装与第六次修复

`deploy/test-cn/v1.4.0-rc.7` 触发 Woodpecker pipeline `#9` 后，`validate-release-trigger` 进入 `pip install pydantic>=2,<3`，不再报 SOCKS support 错误，但持续从 PyPI 下载并出现 read timeout/大依赖下载，导致 release gate 依赖外网与包仓库可用性。为避免长时间占用 agent，已停止该流水线，最终状态为 `killed`。

根因：release gate CLI 位于源码树内，但顶层导入依赖 `protected_k8s_release.py` 的 Pydantic 模型，导致最早的门禁步骤必须在线安装依赖。对受保护发布门禁而言，这会把“校验 tag 与 release contract”的 fail-closed 前置步骤耦合到外网包下载，不适合作为企业发布基线。

修复：`deeptutor_enterprise.protected_k8s_release_cli` 增加 stdlib-only fallback：当 runner 镜像没有 `pydantic` 时，CLI 的 `trigger` / `prepare-metadata` / `preflight` / `scan-evidence` 使用内置的最小发布契约解析、tag 校验、secret preflight 与 evidence 扫描；本地和完整依赖环境仍继续走 Pydantic 模型校验。`.woodpecker/protected-k8s-release.yml` 移除所有在线 `pip install pydantic` 命令，release gate 不再依赖运行时下载 Python 包。

新增回归验证：测试通过 `sitecustomize.py` 在子进程中屏蔽 `pydantic` 导入，执行 `prepare-metadata` 并确认可生成 `trigger-gate.json` 与 `.deeptutor-release.env`。

验证：

```bash
.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release_cli.py extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 19 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已失败或 killed 的既有 tag。

### 2026-09-24 test-cn pipeline #11 暴露 top-level variables 不注入运行时环境

`deploy/test-cn/v1.4.0-rc.8` 触发 Woodpecker pipeline `#11` 后，`validate-release-trigger` 不再进行在线 pip 安装，但在读取 registry 文件时失败：

```text
IsADirectoryError: [Errno 21] Is a directory: '.'
```

日志显示命令中的 `--registry "$REGISTRY_FILE"` 在运行时变为空值，`Path("")` 被解析为当前目录。根因：pipeline 顶层 `variables:` 不是 Woodpecker step 运行时环境变量注入机制；Woodpecker 官方环境变量文档要求通过 step-level `environment:` 注入运行时变量，且 `${VAR}` 会经历配置预处理。当前 release pipeline 的常量（registry path、evidence path、env 文件名）无需作为运行时可变项。

修复：移除顶层 `variables:` 块，将 release gate 所需常量改为命令中的显式语义路径，例如 `extensions/enterprise/protected-k8s-release-environments.example.json`、`release-evidence/gate`、`.deeptutor-release.env`、`.deeptutor-image.env`。新增测试确保 pipeline 不再依赖 `$REGISTRY_FILE` 或顶层 `variables:`。

验证：

```bash
.venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release_cli.py extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 19 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.8` tag。

### 2026-09-24 test-cn pipeline #12 构建镜像步骤缺少 python 与第七次修复

`deploy/test-cn/v1.4.0-rc.9` 触发 Woodpecker pipeline `#12` 后，`validate-release-trigger`、`prepare-release-metadata` 和 `secret-preflight-test-cn` 均已通过，说明 release gate 的 secret 注入、tag 解析、stdlib fallback 与 test-cn secret preflight 已进入可运行状态。后续失败发生在 `build-runtime-image-test-cn`：

```text
/bin/sh: python: not found
```

根因：Kaniko debug 镜像不是 Python 工具镜像，pipeline 使用 `python -c` 生成 Docker config 的 base64 auth 字段。Study Mate 的 Woodpecker 流水线在 Kaniko 步骤中直接写入 Docker config 的 `username` / `password` 字段，不依赖 Python。

修复：所有 Kaniko build 步骤改为写入：

```json
{"auths":{"<registry>":{"username":"<masked>","password":"<masked>"}}}
```

并移除 Kaniko 步骤中的 `python -c` / `base64.b64encode` 依赖。新增测试确保 pipeline 不再包含 `base64.b64encode`，并保留 `username/password` Docker config 形式。

验证：

```bash
.venv/bin/ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 19 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.9` tag。

### 2026-09-24 test-cn pipeline #14 构建镜像 registry contract 与 proxy 修复

`deploy/test-cn/v1.4.0-rc.10` 触发 Woodpecker pipeline `#14` 后，`validate-release-trigger`、`prepare-release-metadata`、`secret-preflight-test-cn` 均通过。`build-runtime-image-test-cn` 已越过 Python 依赖问题，但 Kaniko 在 push permission check 阶段失败：

```text
checking push permission for "registry.example/deeptutor/test-cn/runtime:deploy-test-cn-v1.4.0-rc.10"
proxyconnect tcp: dial tcp: lookup socks5h ... no such host
```

根因有两层：

1. 当前被流水线实际使用的 release registry contract 仍是 `registry.example/...` 示例域名，不能作为真实 test-cn push 目标。
2. runner 环境存在 SOCKS/HTTP proxy 变量；Kaniko/Go 对该 proxy URL 处理失败，访问 registry 时不应继承这些代理变量。

修复：

- `extensions/enterprise/protected-k8s-release-environments.example.json` 中各环境 registry repository 从 `registry.example/deeptutor/<env>` 调整为实际 Woodpecker 可访问的 `docker-hub.f123.pub/lfun/deeptutor/<env>`，仍按环境隔离 repository。
- Kaniko build 和 manifest pre-deploy check 步骤在访问 registry 前显式 `unset SOCKS_PROXY/socks_proxy/ALL_PROXY/all_proxy/HTTPS_PROXY/https_proxy/HTTP_PROXY/http_proxy`。
- 新增测试确保 example registry 不再包含 `registry.example`，并覆盖 proxy unset 与 Docker config username/password 形式。

验证：

```bash
.venv/bin/ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 19 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.10` tag。

### 2026-09-24 test-cn pipeline #16 Docker Hub base image 拉取超时与第九次修复

`deploy/test-cn/v1.4.0-rc.11` 触发 Woodpecker pipeline `#16` 后，release gate、metadata 和 secret preflight 仍通过。Kaniko 开始解析 Dockerfile，并失败于直接访问 Docker Hub base image：

```text
Retrieving image node:22-slim from registry index.docker.io
error building image: Get "https://index.docker.io/v2/": dial tcp ...:443: i/o timeout
```

根因：受保护发布流水线应使用 Woodpecker/集群可访问的 registry mirror，不能依赖 runner 直接访问 `index.docker.io`。当前 Dockerfile 将 `node:22-slim`、`python:3.11-slim` 写死在 `FROM` 中。

修复：

- Dockerfile 增加 `ARG NODE_IMAGE=node:22-slim` 与 `ARG PYTHON_IMAGE=python:3.11-slim`，默认保持本地/普通 Docker 构建兼容。
- Woodpecker Kaniko 步骤追加 build args：`NODE_IMAGE=$${registry_host}/library/node:22-slim`、`PYTHON_IMAGE=$${registry_host}/library/python:3.11-slim`，在 CI 中通过内部 registry/mirror 拉取 base image。
- 新增测试覆盖 Dockerfile base image build args 与 pipeline Kaniko build args。

验证：

```bash
.venv/bin/ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 19 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.11` tag。

### 2026-09-24 test-cn pipeline #18 内部基础镜像路径修正

`deploy/test-cn/v1.4.0-rc.12` 触发 Woodpecker pipeline `#18` 后，release gate、metadata 和 secret preflight 继续通过。Kaniko 已按 build args 访问内部 registry，但失败于不存在的 mirror repository：

```text
GET https://docker-hub.f123.pub/v2/library/node/manifests/22-slim: NOT_FOUND: repository library/node not found
```

根因：内部 registry 中可用的 Node/Python base image 命名不在 `library/*` 路径。已通过 registry tag list（仅检查状态与 tag 名，不输出凭据）确认可用路径包括 `base/node:22-bookworm` 与 `base/python:3.11-slim`。

修复：Woodpecker Kaniko build args 从 `library/node:22-slim` / `library/python:3.11-slim` 改为 `base/node:22-bookworm` / `base/python:3.11-slim`。Dockerfile 默认值保持 Docker Hub 官方镜像，只有 CI 覆盖到内部 registry。

验证：

```bash
.venv/bin/ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 19 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.12` tag。

### 2026-09-24 test-cn pipeline #20 Kaniko 单快照超时与第十次修复

`deploy/test-cn/v1.4.0-rc.13` 触发 Woodpecker pipeline `#20` 后，release gate、metadata 和 secret preflight 继续通过。Kaniko 已成功拉取内部 base image，并完成前端 `npm ci` 与 Next.js production build；失败发生在 Kaniko 对 `frontend-builder` 大文件系统执行单快照时，日志最后停在：

```text
INFO[0580] Taking snapshot of full filesystem...
```

随后步骤失败（约 14.5 分钟后停止），没有进入后续 image push/pre-deploy check。根因：pipeline 使用 `--single-snapshot --snapshot-mode=redo`，在包含完整 Node toolchain、`node_modules` 与 Next.js build 输出的阶段上会触发超大的全文件系统快照，容易超过 Woodpecker/agent 的步骤运行窗口。Study Mate 的 Kaniko 流水线未使用单快照，而是使用 `--cache-copy-layers`。

修复：所有 Kaniko build 步骤改为 Study Mate 同款模式：

- `--context=dir:///woodpecker/src`、`--dockerfile=Dockerfile`；
- `--cache=true --cache-copy-layers --cache-repo ...`；
- 移除 `--single-snapshot` 与 `--snapshot-mode=redo`。

新增测试确保 pipeline 包含 `--cache-copy-layers`，且不再包含单快照参数。

验证：

```bash
.venv/bin/ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 19 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.13` tag。

### 2026-09-24 test-cn pipeline #22 npm 依赖下载耗时与第十一次修复

`deploy/test-cn/v1.4.0-rc.14` 触发 Woodpecker pipeline `#22` 后，release gate、metadata 和 secret preflight 继续通过。Kaniko 已使用 `--cache-copy-layers`，但 `npm ci --legacy-peer-deps` 仍长时间运行并依赖默认 npm registry；为避免继续占用 agent，已手动停止该流水线。停止前状态：build step `killed`，后续 pre-deploy/deploy canceled。

根因：Dockerfile 内的 `npm ci` 与后续 Python dependency install 默认面向公网 registry；在当前 Woodpecker/集群网络中应显式使用可访问的内部/国内镜像源。Study Mate 的流水线也显式设置 npm mirror。

修复：

- Dockerfile 增加 `ARG NPM_REGISTRY` 与 `ARG PIP_INDEX_URL`，默认分别保持 `https://registry.npmjs.org/` 与 `https://pypi.org/simple`，不破坏普通本地构建。
- frontend builder 阶段执行 `npm config set registry "${NPM_REGISTRY}"`。
- python-base/production 阶段设置 `PIP_INDEX_URL`，requirements 安装显式使用 `--index-url "${PIP_INDEX_URL}"`。
- Woodpecker Kaniko 步骤传入 `NPM_REGISTRY=https://mirror.f123.pub/repository/npm/` 与 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。

验证：

```bash
.venv/bin/ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 19 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已停止的 `rc.14` tag。

### 2026-09-24 test-cn pipeline #23 Kaniko npm layer快照失败与第十二次修复

`deploy/test-cn/v1.4.0-rc.15` 触发 Woodpecker pipeline `#23` 后，npm registry mirror 生效，`npm ci` 从约 4 分钟降到约 2 分钟，但 build step 仍失败在 npm layer 之后的 Kaniko 全文件系统快照：

```text
added 950 packages in 2m
INFO[0151] Taking snapshot of full filesystem...
```

根因：即使移除了 `--single-snapshot`，Dockerfile 中独立的 `RUN npm ci ...` 仍要求 Kaniko 对包含完整 root `node_modules` 的层做快照。该层文件数量过大，容易被 Woodpecker/agent 资源或超时策略中断。最终 production image 只需要 Next standalone 输出、static 与 public，并不需要保留 builder 阶段根目录 `node_modules`。

修复：重排 frontend-builder 阶段：先复制 package 与 web source，再在单个 `RUN` 中完成 npm registry 配置、`npm ci --legacy-peer-deps --no-audit --no-fund`、`.env.local` 写入、`npm run build`，最后 `rm -rf node_modules "${HOME}/.npm"`。这样 Kaniko 对该 RUN 做最终快照时保留 `.next/standalone` 等产物，但不再快照庞大的根 `node_modules`。

验证：

```bash
.venv/bin/ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 19 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# lint passes with the known clone image allow-list warning

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# valid
```

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.15` tag。

### 2026-09-24 test-cn pipeline #25 apt 外网源超时与第十三次修复

`deploy/test-cn/v1.4.0-rc.16` 触发 Woodpecker pipeline `#25` 后，release gate、metadata 和 secret preflight 继续通过。Kaniko 已完成前端构建并进入 `python-base` 阶段，但 `apt-get update` 仍使用默认 Debian 外网源：

```text
Get:1 http://deb.debian.org/debian bookworm InRelease
Get:3 http://deb.debian.org/debian-security bookworm-security InRelease
Fetched 9379 kB in 9min 29s
```

随后 build step 被 killed，未进入后续 pre-deploy/deploy。根因：前序修复只覆盖 base image、npm 和 PyPI，Dockerfile 内的 apt 源仍是默认外网源；在当前 Woodpecker agent 网络下 apt 下载过慢，会消耗 Kaniko build 时间窗口。同时 PyPI 源应使用已明确的内网镜像 `https://mirror.f123.pub/repository/pypi/`，而不是公网 PyPI/TUNA PyPI。

修复：

- Dockerfile 增加可覆盖的 `APT_DEBIAN_MIRROR` / `APT_SECURITY_MIRROR` build args，并在 `python-base` 与 `production` 两个会执行 `apt-get` 的阶段改写 `/etc/apt/sources.list.d/debian.sources` 或 `/etc/apt/sources.list` 后再 `apt-get update`。
- Woodpecker Kaniko build args 显式使用 Tsinghua Debian 镜像：`http://mirrors.tuna.tsinghua.edu.cn/debian` 与 `http://mirrors.tuna.tsinghua.edu.cn/debian-security`。
- Woodpecker PyPI build arg 改为内网 `https://mirror.f123.pub/repository/pypi/`。
- Dockerfile 增加 Rustup/Cargo 镜像 build args；CI 中使用 Tsinghua `rustup` 和 Cargo sparse index，避免后续 Rust 依赖构建继续访问默认源。
- 新增/更新测试覆盖 apt/PyPI/Rustup/Cargo 镜像 build args，并禁止回退到 `PIP_TRUSTED_HOST` 或旧公网 PyPI 源。

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.16` tag。

### 2026-09-24 test-cn pipeline #26 Cargo 镜像源修正

`deploy/test-cn/v1.4.0-rc.17` 触发 Woodpecker pipeline `#26` 后，release gate、metadata 和 secret preflight 均通过，build step 已使用 Tsinghua apt 与内网 PyPI build args。随后根据目标环境镜像策略调整，停止该流水线，避免旧 Cargo mirror 配置继续推进到部署阶段。

修复：

- 保留 apt 使用 Tsinghua Debian mirror、PyPI 使用内网 `https://mirror.f123.pub/repository/pypi/`、Rustup 使用 Tsinghua mirror。
- 将 Woodpecker Kaniko build arg `CARGO_REGISTRY_MIRROR` 改为内网 Cargo/Rust 镜像：`sparse+https://mirror.f123.pub/repository/rust/`。
- 更新测试，确保流水线不再回退到 Tsinghua crates.io sparse index，而是使用内网 Cargo mirror。

下一次触发使用新 commit 和新 tag；不移动已停止的 `rc.17` tag。

### 2026-09-24 test-cn pipeline #27 python-base 大层 snapshot 与第十四次修复

`deploy/test-cn/v1.4.0-rc.19` 触发 Woodpecker pipeline `#27` 后，release gate、metadata 和 secret preflight 均通过。build step 日志确认镜像源策略已经生效：

- Kaniko build args 使用 Tsinghua apt、内网 PyPI `https://mirror.f123.pub/repository/pypi/` 和内网 Cargo mirror `sparse+https://mirror.f123.pub/repository/rust/`。
- apt 从 Tsinghua 下载 151MB 用约 25s，明显改善此前 `deb.debian.org` 下仅 apt index 就 9m29s 的问题。
- Rustup stable toolchain 安装完成，Cargo config 写入内网 mirror。

新的失败点不是镜像源，而是 Kaniko 在安装完 apt build dependencies 和 Rust toolchain 后执行 `Taking snapshot of full filesystem...`，日志没有后续错误行即 step failure，属于与前端 `node_modules` 层类似的大层 snapshot/runner 资源问题。

修复：

- 将 `python-base` 中 requirements 复制提前。
- 将 apt build dependencies、Rustup/Cargo 配置、pip install 合并到单个 `RUN`，避免形成单独的 apt/Rust 大层。
- 在同一 `RUN` 的末尾删除 `/root/.cargo`、`/root/.rustup`，并 `apt-get purge --auto-remove` build-only 依赖，再清理 apt/tmp 目录，让 Kaniko snapshot 最终状态而不是完整编译环境。
- 更新测试，确保 `python-base` 只有一个 build RUN，且顺序为 apt/rust setup → pip install → purge/cleanup。

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.19` tag。

### 2026-09-24 test-cn pipeline #29 PyPI simple endpoint 与并行编译拆分

`deploy/test-cn/v1.4.0-rc.20` 触发 Woodpecker pipeline `#29` 后，release gate、metadata 和 secret preflight 均通过。build step 已确认：

- Kaniko build args 使用 Tsinghua apt mirror；
- PyPI 已切换到内网 `https://mirror.f123.pub/repository/pypi/`；
- Cargo mirror 已切换到内网 `sparse+https://mirror.f123.pub/repository/rust/`；
- `python-base` 大层清理逻辑生效，apt 与 Rustup 均已完成。

新的失败点发生在 pip 解析 PyPI index：

```text
Looking in indexes: https://mirror.f123.pub/repository/pypi/
ERROR: Could not find a version that satisfies the requirement PyYAML>=6.0 (from versions: none)
ERROR: No matching distribution found for PyYAML>=6.0
```

根因：内部 Nexus PyPI repository 的根路径返回仓库 HTML 页面，pip 需要使用 PEP 503 simple API endpoint；实测 `https://mirror.f123.pub/repository/pypi/simple/pyyaml/` 返回 package link 列表，而 `/repository/pypi/PyYAML/` 不是 pip index。

同时，Kaniko 仍承担 npm build 与 pip/Rust dependency build；这些步骤即使通过镜像源优化，也会让最终 build step 串行等待并继续承担大文件系统 snapshot 风险。按照 Study Mate 流水线模式和当前发布需求，本次将构建拆成可并行步骤：

- `compile-frontend-<env>`：使用 `docker-hub.f123.pub/base/node:22-bookworm`，通过内部 npm mirror 构建 Next standalone/static/public artifacts 到 `.deeptutor-build/frontend/`。
- `compile-python-deps-<env>`：使用 `docker-hub.f123.pub/base/python:3.11-slim`，通过 Tsinghua apt、内网 PyPI simple endpoint、Tsinghua rustup 和内网 Cargo mirror 构建 Python prefix 到 `.deeptutor-build/python-prefix/`。
- `build-runtime-image-<env>`：依赖两个 compile steps，只用 `Dockerfile.protected-runtime` 将 artifacts、runtime apt deps、Node runtime 与应用源码装配为最终镜像并推送 digest；不再在 Kaniko 内执行 npm/pip/Rust 编译。

修复：

- 新增 `scripts/protected-k8s-release/build-frontend-artifact.sh` 与 `build-python-prefix-artifact.sh`，分别产出前端和 Python dependency artifacts。
- 新增 `Dockerfile.protected-runtime`，只做 runtime image 装配，不含 frontend-builder/python-base 编译阶段。
- Woodpecker 每个环境新增 `compile-frontend-*` 与 `compile-python-deps-*` 两个并行步骤，`build-runtime-image-*` 改为依赖这两个步骤。
- `.dockerignore` 对 `.deeptutor-build/**` 增加显式 re-include，确保 Next standalone 中的最小 `node_modules` 不会被全局 ignore 规则排除。
- PyPI index 统一改为 `https://mirror.f123.pub/repository/pypi/simple/`，避免 pip 读取仓库根页面导致 package 为空。
- 更新测试契约，覆盖并行步骤、runtime assembler Dockerfile、镜像源、artifact 目录和 Kaniko 仅装配路径。

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.20` tag。

### 2026-09-24 test-cn pipeline #30 并行步骤首跑结果与第十五次修复

`deploy/test-cn/v1.4.0-rc.21` 触发 Woodpecker pipeline `#30` 后，release gate、metadata、secret preflight 通过；`compile-frontend-test-cn` 与 `compile-python-deps-test-cn` 在同一时间启动，确认拆分后的 Woodpecker DAG 可以并行执行。

并行首跑暴露两个步骤内问题：

1. 前端 step 完成 `npm ci` 后运行 Next build，但 artifact 脚本只查找 `web/.next/standalone`。当前仓库存在可由 `DEEPTUTOR_NEXT_DIST_DIR` 或历史 launcher 路径产生的 `.next-deeptutor` 输出模式，脚本缺少对实际 dist dir 的兜底，失败于：

   ```text
   cp: cannot stat 'web/.next/standalone': No such file or directory
   ```

2. Python deps step 独立运行在 Python 容器内，没有继承 Kaniko build step 里的 proxy 清理。apt 访问 Tsinghua mirror 时走到了不可用代理/端口，`apt-get update` 只给 warning 并继续，随后 install 阶段找不到包：

   ```text
   Err:1 http://mirrors.tuna.tsinghua.edu.cn/debian bookworm InRelease
     Connection failed
   E: Unable to locate package curl
   ```

修复：

- 前端 artifact 脚本按 `DEEPTUTOR_NEXT_DIST_DIR` 定位 standalone/static，并兜底检查 `.next` 与 `.next-deeptutor`，找不到时输出候选目录用于下一轮诊断。
- Python artifact 脚本在 apt 前清理 `SOCKS_PROXY`/`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`，并写入 apt no-proxy 配置。
- `apt-get update` 改为 `APT::Update::Error-Mode=any`，mirror 失败时直接在 update 阶段 fail closed，避免继续到误导性的 “Unable to locate package”。

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.21` tag。

### 2026-09-24 test-cn pipeline #31 apt proxy 修复验证与前端 standalone 等待修正

`deploy/test-cn/v1.4.0-rc.22` 触发 Woodpecker pipeline `#31` 后，release gate、metadata、secret preflight 通过；`compile-frontend-test-cn` 与 `compile-python-deps-test-cn` 再次并行启动。

已验证：Python deps step 的 proxy 清理和 apt no-proxy 配置生效，apt 从 Tsinghua mirror 成功获取 151MB 构建依赖，修复了 #30 的 apt index/包定位问题。

新的失败点仍在前端 artifact step：`npm ci` 成功，Next build 输出停留在 webpack production build 阶段后，脚本立即检查 standalone artifact，未等到 `standalone` 目录出现即 fail closed：

```text
Creating an optimized production build ...
Using tsconfig file: tsconfig.deeptutor-build-132.json
Next standalone output not found; searched .next, .next and .next-deeptutor
```

本地用同一 Node 22 版本运行 `DEEPTUTOR_NEXT_DIST_DIR=.next-ci-probe npm run build` 证明 Next build 会在后续阶段生成 `standalone/server.js`；因此流水线脚本应对 Next/worker 输出存在异步落盘或日志延迟的情况做 bounded wait，而不是在 `npm run build` 返回后立即判失败。

修复：

- `build-frontend-artifact.sh` 在 `npm run build` 后增加最长 180 秒 bounded wait，轮询 `DEEPTUTOR_NEXT_DIST_DIR`、`.next`、`.next-deeptutor` 的 `standalone`/`static` 输出。
- 找不到 artifact 时输出 `.next*` 候选目录，便于下一轮区分“构建未完成”“输出目录不同”或“standalone 未生成”。

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.22` tag。

### 2026-09-24 test-cn pipeline #33 前端构建 worker/内存限制修正

`deploy/test-cn/v1.4.0-rc.23` 触发 Woodpecker pipeline `#33` 后，并行 compile DAG 再次生效。`compile-python-deps-test-cn` 已继续通过 apt mirror 下载/安装阶段，旧 apt proxy 问题未复现。

前端 step 在增加 bounded wait 后仍未生成 standalone；诊断输出显示 `web/.next` 存在，但未出现 `standalone` 目录：

```text
Waiting for Next standalone output (170s elapsed)...
Next standalone output not found; searched .next, .next and .next-deeptutor
web/.next
```

流水线日志仍停在 webpack production build 初始阶段，未进入本地可见的 `Compiled successfully`、TypeScript、page data 或 trace collection 阶段。根因判断为前端编译在 Woodpecker Node 容器中按宿主 CPU 数默认扇出过多 worker（Next 16 默认约 `cpus - 1`，当前日志/本地表现为 17 workers），叠加 `NODE_OPTIONS=--max-old-space-size=4096` 对内存受限容器不友好，导致 build 子进程未产出 standalone。

修复：

- 前端 compile step 的 `NODE_OPTIONS` 从 4096MiB 下调到 2048MiB，参考 Study Mate 的 Node build 配置，避免单进程声明过大 heap。
- 新增 `DEEPTUTOR_NEXT_BUILD_CPUS=1`，artifact 脚本据此导出 `CIRCLE_NODE_TOTAL=2`，利用 Next 默认 `CIRCLE_NODE_TOTAL - 1` 逻辑将生产构建 worker 数限制为 1，避免在 Woodpecker 容器内按宿主核心数过度并发。
- 保留 bounded wait 与目录诊断，下一轮可验证 standalone 是否产生；过期 #33 已停止以释放 runner 资源。

下一次触发使用新 commit 和新 tag；不移动已失败/已停止的 `rc.23` tag。

### 2026-09-24 test-cn pipeline #34 前端直接 Next build 兜底

`deploy/test-cn/v1.4.0-rc.25` 触发 Woodpecker pipeline `#34`（`rc.24` tag 已推送但未被 Woodpecker webhook 创建 pipeline，因此使用下一不可变 tag）。release gate、metadata、secret preflight 通过；并行 compile steps 启动。

前端 step 在限制 worker/heap 后仍表现为 `npm run build` 过早返回，日志停在：

```text
Creating an optimized production build ...
Using tsconfig file: tsconfig.deeptutor-build-133.json
Waiting for Next standalone output ...
```

这说明问题不只是 worker 数；更像是 `web/scripts/build.mjs` 在该 Woodpecker Node 容器内对内部 `next build` 子进程状态传播不稳定。本地同 Node 22 版本运行 wrapper 可完整产出 standalone，说明代码本身可构建。

修复：

- 保留 `npm run build`（继续执行仓库 wrapper 中的 pdfjs asset copy、tsconfig 保护和普通路径）。
- 若 wrapper 返回后没有 standalone，立即以 `node ./node_modules/next/dist/bin/next build --webpack` 直接运行 Next build 作为 CI fallback，再进入 bounded wait。
- 保留 `DEEPTUTOR_NEXT_BUILD_CPUS=1` 与 2048MiB heap 限制，避免 fallback 也按宿主 CPU 过度并发。
- 过期 #34 已停止以释放 runner 资源。

下一次触发使用新 commit 和新 tag；不移动已停止的 `rc.25` tag。

### 2026-09-25 test-cn pipeline #35 直接 Next build 复现与脚本简化

`deploy/test-cn/v1.4.0-rc.26` 触发 Woodpecker pipeline `#35` 后，release gate、metadata、secret preflight 通过；并行 compile steps 启动。

前端 step 进入新增 fallback，但仍未生成 standalone：

```text
Next standalone output not present after npm run build; retrying with direct next build...
Creating an optimized production build ...
Waiting for Next standalone output ...
Next standalone output not found; searched .next, .next and .next-deeptutor
web/.next
```

同时，Python deps step 已越过 apt、Rustup，并进入 Python/Rust dependency build 阶段，说明并行拆分后 Python side 的镜像源和 proxy 修复方向有效。

为定位前端问题，使用同类 Linux Node 镜像 `docker-hub.f123.pub/base/node:22-bookworm` 在本地容器中复现：

- `node ./scripts/build.mjs` 在 macOS bind mount 上会卡在 `copyPdfjsAssets` 删除/覆盖 pdfjs wasm 目录，属于本地挂载权限/目录语义问题，不作为 CI 根因。
- 直接运行 `node ./node_modules/next/dist/bin/next build --webpack`，并设置 `DEEPTUTOR_NEXT_DIST_DIR=.next-linux-probe-direct`、`CIRCLE_NODE_TOTAL=2`、`NODE_OPTIONS=--max-old-space-size=2048`，能在 Linux Node 镜像内完成编译、TypeScript、page generation、trace collection，并产出 `.next-linux-probe-direct/standalone/server.js`。

结论：在 CI artifact 脚本中继续通过 `npm run build` wrapper 会引入额外不确定性；前端 compile step 应直接调用 Next build，同时单独执行 wrapper 中必要的 pdfjs asset copy。

修复：

- `build-frontend-artifact.sh` 改为 `npm ci` 后执行 `node ./scripts/copy-pdfjs-assets.mjs`，再直接执行 `node ./node_modules/next/dist/bin/next build --webpack`。
- 保留 `DEEPTUTOR_NEXT_BUILD_CPUS=1`、2048MiB heap 和 bounded artifact wait。
- 测试契约更新为禁止前端 artifact 脚本再使用 `npm run build`。
- 过期 #35 已停止以释放 runner 资源。

下一次触发使用新 commit 和新 tag；不移动已停止的 `rc.26` tag。

### 2026-09-25 test-cn pipeline #36 workspace artifact 前端构建失败与 artifact-image 架构修正

`deploy/test-cn/v1.4.0-rc.27` 触发 Woodpecker pipeline `#36` 后，release gate、metadata、secret preflight 均通过；`compile-frontend-test-cn` 与 `compile-python-deps-test-cn` 在同一时间启动，继续证明拆分后的 DAG 可以并行执行。

已验证：`compile-python-deps-test-cn` 完整成功。日志确认 apt 使用 Tsinghua Debian mirror，pip 使用内网 PEP 503 simple endpoint `https://mirror.f123.pub/repository/pypi/simple/`，Rustup 使用 Tsinghua mirror，Cargo 使用内网 `sparse+https://mirror.f123.pub/repository/rust/`。该结果证明 Python dependency 编译侧的 mirror/secrets/proxy 修复有效。

前端 step 仍未产出 standalone：`npm ci` 成功，直接 Next build 输出停留在 webpack production build 初始阶段后返回，bounded wait 仅看到 `web/.next`，没有 `web/.next/standalone`：

```text
Creating an optimized production build ...
Waiting for Next standalone output (170s elapsed)...
Next standalone output not found; searched .next, .next and .next-deeptutor
web/.next
```

经过 #31、#33、#34、#35、#36 多轮修复后，继续在 Woodpecker command container 中把 Next standalone 写入 workspace artifact 已经表现出架构性不稳定：问题不在 mirror，也不在 Python side，而在前端构建产物从 Node command step 到 Kaniko runtime context 的路径。为避免继续叠加脚本级 workaround，本次改为 artifact-image 架构：

- `compile-frontend-<env>` 改用 Kaniko 构建 `Dockerfile --target=frontend-builder`，通过内部 npm mirror 产出并推送 `$DEEPTUTOR_REGISTRY_REPOSITORY/frontend-build:$DEEPTUTOR_IMAGE_TAG`。
- `compile-python-deps-<env>` 改用 Kaniko 构建 `Dockerfile --target=python-base --skip-unused-stages`，通过 Tsinghua apt、内网 PyPI simple、Tsinghua Rustup 和内网 Cargo mirror 产出并推送 `$DEEPTUTOR_REGISTRY_REPOSITORY/python-deps:$DEEPTUTOR_IMAGE_TAG`。
- `build-runtime-image-<env>` 保持依赖两个 compile steps，但不再读取 `.deeptutor-build/**` workspace artifact；它通过 `FRONTEND_ARTIFACT_IMAGE` 和 `PYTHON_DEPS_IMAGE` build args 引用两个中间镜像。
- `Dockerfile.protected-runtime` 新增外部 artifact stages，只从 `frontend-artifact` 复制 `.next/standalone`、`.next/static`、`public`，从 `python-deps` 复制 `/usr/local/lib/python3.11/site-packages` 与 `/usr/local/bin`；最终 runtime stage 仍不包含 frontend-builder/python-base 编译逻辑，也不执行 npm/pip/Rust 编译。
- 删除不再使用的 workspace artifact scripts，并将 `.deeptutor-build/` 明确加入 `.dockerignore`（同时撤销 re-include），避免本地残留 artifact 被错误带入 Kaniko context。
- 更新测试契约，覆盖 `--target=frontend-builder`、`--target=python-base --skip-unused-stages`、`frontend-build`/`python-deps` artifact images、runtime external stages 以及镜像源 build args。

下一次触发使用新 commit 和新 tag；不移动已失败的 `rc.27` tag。

### 2026-09-25 test-cn pipeline #37 artifact-image 并行拆分已验证与 runtime base 再拆分

`deploy/test-cn/v1.4.0-rc.28` 触发 Woodpecker pipeline `#37` 后，已确认前端与 Python 依赖编译被拆为独立 Kaniko artifact-image steps，且二者在 `prepare-release-metadata` 后同时启动：

- `compile-frontend-test-cn`：`Started=1790268001`，`Stopped=1790268036`，`State=success`，推送 `frontend-build:$DEEPTUTOR_IMAGE_TAG`。
- `compile-python-deps-test-cn`：`Started=1790268001`，`Stopped=1790268579`，`State=success`，推送 `python-deps:$DEEPTUTOR_IMAGE_TAG`。
- `secret-preflight-test-cn` 同期启动并成功，说明 build/preflight DAG 已并行化。

后续 `build-runtime-image-test-cn` 能成功解析并复制上述 artifact images，但日志显示 runtime final stage 在复制大体积 `/usr/local/lib/python3.11/site-packages` 与 frontend standalone 后，仍为多个小型 `RUN` 指令反复执行 Kaniko full filesystem snapshot：`mkdir`、`groupadd/useradd/chown`、`cat > supervisord.conf`、`sed`、`cat > programs.conf`、`cat > start-backend.sh`、`chmod`、`cat > start-frontend.sh` 等步骤每次约消耗 110–130 秒。该瓶颈不是编译失败，而是最终装配阶段的小层过多导致 Kaniko snapshot 成本叠加。

按“编译/装配职责拆开并行”的原则继续修正：

- 新增 `Dockerfile.protected-runtime-base`，只构建 runtime OS/base layer：Tsinghua apt mirror、supervisor/git/OpenCV runtime libs、Node runtime 复制、npm/npx symlink、`deeptutor` 非 root 用户和 `/app/data` 目录骨架。
- Woodpecker 为每个环境新增 `build-runtime-base-<env>` step，依赖 `prepare-release-metadata`，与 `compile-frontend-<env>`、`compile-python-deps-<env>` 并行推送 `runtime-base:$DEEPTUTOR_IMAGE_TAG`。
- `build-runtime-image-<env>` 依赖三类 artifact images：`runtime-base`、`frontend-build`、`python-deps`；最终 `Dockerfile.protected-runtime` 从 `RUNTIME_BASE_IMAGE` 开始，只复制 runtime config/scripts、Python deps、frontend standalone 和应用源码，不再运行 apt/npm/pip/Rust，也不再用 heredoc/sed/chmod 生成 runtime 文件。
- runtime 进程配置与启动脚本迁移为受版本控制文件：`deploy/docker-runtime/supervisord.conf`、`programs.conf`、`start-backend.sh`、`start-frontend.sh`、`entrypoint.sh`、`healthcheck.py`；脚本权限在源码中固定，避免镜像最终阶段额外 `chmod`。

下一次触发使用新 commit 和新 tag；不移动已触发的 `rc.28` tag。

### 2026-09-25 test-cn pipeline #37 migration Job 缺少 enterprise CLI 修正

`deploy/test-cn/v1.4.0-rc.28` 的 `build-runtime-image-test-cn` 最终成功并推送 runtime digest，`pre-deploy-check-test-cn` 成功解析 digest，随后 `deploy-test-cn` 创建 `dt-migrate-test-cn-v1-4-0-rc-28` migration Job。只读检查 test 集群显示该 Job `Failed`，Pod 进入 `Error`，脱敏日志为：

```text
acquire release-lock and migration-lock for test-cn/test-cn-v1-4-0-rc-28
/bin/sh: 2: deeptutor-enterprise: not found
```

根因：protected runtime image 只复制 core `deeptutor/` 与 `deeptutor_cli/`，没有把 `extensions/enterprise/src/deeptutor_enterprise` 纳入镜像；migration Job 依赖的 `deeptutor-enterprise` console script 也未通过 package install 生成。因此部署阶段不能调用企业 schema/bootstrap CLI。

修复：

- `Dockerfile.protected-runtime` 复制 `extensions/enterprise/src/deeptutor_enterprise/` 到 `/app/extensions/enterprise/src/deeptutor_enterprise/`。
- `migration-job.yaml` 改为显式设置 `PYTHONPATH=/app:/app/extensions/enterprise/src`，并用 `python -m deeptutor_enterprise.cli ...` 调用 schema plan/apply/verify/bootstrap，避免依赖未安装的 console script。
- 同步修正原生 K8s runtime 端口：容器暴露 backend `8001` 和 frontend `3782`；readinessProbe 使用 `backend-http`，Service/Ingress 走 `frontend-http`，NetworkPolicy 允许 `3782` 与 `8001`，与 runtime image 的 supervisord 启动脚本保持一致。

下一次触发使用新 commit 和新 tag；不移动已失败/运行中的 `rc.28` tag。

### 2026-09-25 test-cn pipeline #38 三路并行构建跑通，deploy 阻断于环境 migrator DSN

`deploy/test-cn/v1.4.0-rc.29` 触发 Woodpecker pipeline `#38`，使用 commit `c1357855` 的三路 artifact-image DAG：

- `compile-frontend-test-cn`、`compile-python-deps-test-cn`、`build-runtime-base-test-cn` 和 `secret-preflight-test-cn` 均在 `prepare-release-metadata` 后同一时间启动（`Started=1790271375`）。
- `compile-frontend-test-cn` 成功，`Stopped=1790271503`。
- `compile-python-deps-test-cn` 成功，`Stopped=1790271504`。
- `build-runtime-base-test-cn` 成功，`Stopped=1790271668`。
- `secret-preflight-test-cn` 成功，`Stopped=1790271515`。
- `build-runtime-image-test-cn` 从 `runtime-base`、`frontend-build`、`python-deps` 三个 artifact images 装配最终 runtime，成功，`Started=1790271668`，`Stopped=1790272085`。
- `pre-deploy-check-test-cn` 成功，`Stopped=1790272091`。

与 #37 相比，runtime final stage 不再出现多个 heredoc/sed/chmod 之后的 full filesystem snapshot 链；剩余耗时主要为从 artifact images 保存/复制 `.next`、`site-packages`、`/usr/local/bin` 和应用源码，这是最终装配必须成本。

随后 `deploy-test-cn` 创建 `dt-migrate-test-cn-v1-4-0-rc-29` migration Job。Job 失败，脱敏日志为：

```text
acquire release-lock and migration-lock for test-cn/test-cn-v1-4-0-rc-29
企业操作失败（PostgresConfigurationError）；检查配置、权限和运行状态
```

只在内存中比较 K8s Secret 与 `.secrets/woodpecker-secrets/test.secrets` 的 DSN 值，不输出明文，结论为：

- K8s `deeptutor-migrator-secrets` 中 `DEEPTUTOR_POSTGRES_DATABASE_URL` 与 `DEEPTUTOR_POSTGRES_MIGRATION_DATABASE_URL` 相同。
- `.secrets/woodpecker-secrets/test.secrets` 中 `DT_TEST_CN_PG_MIGRATOR_DSN` 与上述两个 K8s DSN 相同。
- 使用该 DSN 只读查询当前账号权限：当前账号不是 superuser，且没有 `CREATEROLE` 或 `CREATEDB`，不能由流水线/agent 安全派生独立 migrator role。

结论：#38 已验证并行构建/推送/ digest pre-check 链路；剩余 deploy 阻断项是 test-cn 环境未提供与 runtime DSN 分离的 migrator DSN。根据 G1 要求，不能在代码中绕过 `postgres_migration_not_separate`，需要环境侧预置独立 migrator role/DSN，并同步更新 K8s `deeptutor-migrator-secrets` 与 Woodpecker `DT_TEST_CN_PG_MIGRATOR_DSN` 后再触发下一 tag。

为避免 Woodpecker deploy step 等待 `kubectl wait` 到 900s 超时，已停止 #38；不移动已触发的 `rc.29` tag。

### 2026-09-25 deploy 前置校验：相同 runtime/migrator PostgreSQL DSN fail-fast

基于 #38 的根因，新增 deploy 脚本前置校验：在 apply NetworkPolicy / migration Job 之前，只读取目标 namespace 中 `deeptutor-migrator-secrets` 的 `DEEPTUTOR_POSTGRES_DATABASE_URL` 与 `DEEPTUTOR_POSTGRES_MIGRATION_DATABASE_URL` 两个 K8s Secret data 项并比较 base64 结果；若二者均存在且相同，立即 fail closed，输出不含 DSN 明文的错误，要求环境侧预置独立 migrator DSN。

该修复不会尝试用当前低权限运行账号派生 migrator role，也不会绕过企业扩展中的 `postgres_migration_not_separate` 检查；它只把已知环境错误从 migration Job 失败/等待超时前移到 deploy step 早期，避免重复消耗 Woodpecker runner。

RED/GREEN：

```bash
PYTHONPATH=. .venv/bin/pytest \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_deploy_script_fails_fast_when_runtime_and_migrator_pg_dsn_match -q
# RED：deploy.sh 未检查 deeptutor-migrator-secrets，fake kubectl 允许后续 apply/rollout，命令返回 0，测试期望 fail-fast 失败。
# GREEN：新增 K8s Secret base64 等值校验后，1 passed；stderr 只包含 secret/key 名与“provision a separate migrator DSN”，不包含 DSN 明文，且未执行 apply。
```

下一步：test-cn 环境仍需更新 Woodpecker/K8s secret，使 `DEEPTUTOR_POSTGRES_MIGRATION_DATABASE_URL` 指向独立 migrator role/DSN；在此之前不应继续打新的 deploy tag，除非明确只验证 fail-fast 行为。

本轮提交前验证：

```bash
woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# exit 0；保留既有 clone.git allow-list warning。

.venv/bin/ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 20 passed

bash -n deploy/kubernetes/protected-k8s-release/deploy.sh
# exit 0

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# Change valid

openspec validate --all --strict
# 16 passed, 0 failed

docker build --check -f Dockerfile.protected-runtime-base .
# Check complete, no warnings found.

docker build --check -f Dockerfile.protected-runtime .
# Check complete, no warnings found.

git diff --check
# exit 0
```

### 2026-09-25 用户决策更新：test-cn 使用同一个 PostgreSQL 连接

用户确认 `DT_TEST_CN_PG_MIGRATOR_DSN` 不需要独立 migrator role/DSN，按 test-cn 当前环境约束使用与标准数据库连接一致的 PostgreSQL DSN。本节 supersede 前一节“相同 runtime/migrator PostgreSQL DSN fail-fast”的实现决策；#38 的构建链路结论仍有效，但 deploy 不再因 migration/runtime DSN 值相同而 fail closed。

本轮调整：

- `PostgresDeploymentConfig.resolve_migration()` 允许 migration DSN 与 runtime DSN 使用同一个环境变量引用或同一个 DSN 值。
- `deploy/kubernetes/protected-k8s-release/deploy.sh` 删除 `deeptutor-migrator-secrets` 中两个 PG DSN data 项相同即失败的前置校验。
- protected K8s deploy 测试改为验证 shared runtime/migrator DSN 不会被本地 deploy 脚本阻断，仍会继续 apply 原生 Kubernetes YAML 并 rollout。
- test-cn secret 生成与示例环境 registry 中 PG metadata 文案改为 shared PostgreSQL deployment connection，不再描述为独立 migration role。

RED/GREEN：

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/persistence/postgres/test_configuration.py::test_migration_resolution_accepts_runtime_dsn_reference_or_value_without_leaking -q
# RED：from_mapping/resolve_migration 仍拒绝 shared runtime DSN。
# GREEN：1 passed。

PYTHONPATH=. .venv/bin/pytest \
  extensions/enterprise/tests/test_postgres_configuration_adapter.py::test_schema_cli_accepts_shared_runtime_dsn_and_rejects_canonical_conflict -q
# RED：enterprise schema CLI 使用 --dsn-env DEEPTUTOR_DATABASE_URL 时仍报 PostgresConfigurationError。
# GREEN：1 passed。

PYTHONPATH=. .venv/bin/pytest \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_deploy_script_allows_shared_runtime_and_migrator_pg_dsn -q
# RED：deploy.sh 仍因两个 K8s Secret data 值相同而 fail-fast。
# GREEN：1 passed。
```

风险/边界：该变更仅取消“必须使用独立 DB role”的配置门禁；实际 schema apply/verify 是否成功仍取决于 test-cn 当前 DB 用户是否拥有已存在 schema 的验证权限以及必要 DDL 权限。若后续 migration Job 进入数据库权限错误，应按真实错误继续排查，而不是恢复 DSN 分离门禁。

本轮 shared PostgreSQL connection 提交前验证：

```bash
.venv/bin/ruff check \
  deeptutor/persistence/postgres/configuration.py \
  extensions/enterprise/tests/test_postgres_configuration_adapter.py \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py \
  tests/persistence/postgres/test_configuration.py \
  scripts/protected-k8s-release/prepare-test-woodpecker-secrets.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest tests/persistence/postgres/test_configuration.py -q
# 23 passed

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_postgres_configuration_adapter.py -q
# 5 passed

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 20 passed

woodpecker-cli lint .woodpecker/protected-k8s-release.yml
# exit 0；保留既有 clone.git allow-list warning。

bash -n deploy/kubernetes/protected-k8s-release/deploy.sh
# exit 0

git diff --check
# exit 0

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# Change valid

openspec validate --all --strict
# 16 passed, 0 failed
```

### 2026-09-25 test-cn pipeline #39 shared DSN 生效，阻断于 DB DDL 权限；deploy wait 修正

`deploy/test-cn/v1.4.0-rc.30` 触发 Woodpecker pipeline `#39`，使用 commit `ad11c1bd`：

- release trigger、metadata 均成功。
- `compile-frontend-test-cn`、`compile-python-deps-test-cn`、`build-runtime-base-test-cn`、`secret-preflight-test-cn` 均在 `Started=1790305807` 同时启动并成功。
- `build-runtime-image-test-cn` 成功，`pre-deploy-check-test-cn` 成功。
- `deploy-test-cn` 创建 `dt-migrate-test-cn-v1-4-0-rc-30` migration Job。

K8s 只读排查结果：Job 已 `Failed`，Pod `Error`，不是仍在执行。Woodpecker 卡住的直接原因是 deploy 脚本仍在用 `kubectl wait --for=condition=complete` 等待 Job Complete；当 Job 进入 Failed 时不会被该条件识别，只能等到 900s timeout。

脱敏 Pod 日志：

```text
acquire release-lock and migration-lock for test-cn/test-cn-v1-4-0-rc-30
{"pending": ["0001_identity_sessions", "0002_account_profiles_devices", "0003_device_usage_precision", "0004_notebook_entries_categories", "0005_learning", "0006_reading", "0007_session_resources", "0008_cron", "0009_partner_runtime_status", "0010_matrix_store", "0011_marginnote_store", "0012_offline_import_stage", "0013_courses", "0014_externalized_runtime", "0001_federated_access", "0002_profile_permission_snapshots", "0003_revocation_state", "0004_audit_export_jobs"]}
企业操作失败（InsufficientPrivilege）；检查配置、权限和运行状态
```

结论：shared DSN 配置门禁已生效，`schema plan` 可以运行并列出 pending migrations；真实阻断点变为 `schema apply` 阶段数据库账号权限不足。当前 test-cn 数据库尚未初始化 DeepTutor enterprise schema，且使用的同一个 DB 账号不足以执行首轮 DDL/role/grant 迁移。

本轮脚本修复：

- `deploy.sh` 不再使用 complete-only `kubectl wait`。
- 新增 Job condition 轮询：检测 `Complete=True` 返回成功，检测 `Failed=True` 立即输出 pods/logs/describe 并退出 1，避免占用 Woodpecker runner 等完整 timeout。
- 保留 `DEEPTUTOR_MIGRATION_TIMEOUT`，支持秒数或 `s`/`m` 后缀；新增 `DEEPTUTOR_MIGRATION_POLL_INTERVAL_SECONDS`。

RED/GREEN：

```bash
PYTHONPATH=. .venv/bin/pytest \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py::test_protected_k8s_deploy_script_exits_when_migration_job_fails_without_wait_timeout -q
# RED：deploy.sh 调用了 complete-only kubectl wait。
# GREEN：1 passed，失败 Job 立即收集日志并退出，不进入 rollout。
```

验证：

```bash
.venv/bin/ruff check extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=. .venv/bin/pytest extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 21 passed

bash -n deploy/kubernetes/protected-k8s-release/deploy.sh
# exit 0

git diff --check
# exit 0
```

后续：若继续坚持 test-cn 使用单一 DB 连接，则该连接必须具备初始化企业 schema 所需的 DDL/role/grant 权限，或由 DBA 预先初始化全部 pending migrations。否则下一次 deploy 会快速失败在同一 `InsufficientPrivilege` 根因，而不会再卡 900s。

### 2026-09-25 test-cn Pod 内 PostgreSQL 连接与权限探测

按用户要求，通过 Kubernetes 上的临时 Pod 从集群内实际连接数据库，验证 `deeptutor-migrator-secrets` 提供的 PostgreSQL 连接是否真实可用。探测 Pod 使用 #39 migration Job 同一个 runtime image，并从同一个 `deeptutor-migrator-secrets` 注入环境变量；探测完成后已删除 Pod。未输出 DSN、密码或 kubeconfig secret。

临时 Pod：`dt-pg-probe-1790307685`，namespace：`deeptutor-test-cn`，node：`test-worker6`。

脱敏探测结论：

```json
{
  "connect": {"ok": true},
  "env_present": {
    "DEEPTUTOR_POSTGRES_DATABASE_URL": true,
    "DEEPTUTOR_POSTGRES_MIGRATION_DATABASE_URL": true
  },
  "session": {
    "database": "deeptutor",
    "user": "deeptutor",
    "schema": "public",
    "server_addr": "10.5.3.11/32",
    "server_port": 5432
  },
  "role_capabilities": {
    "superuser": false,
    "createrole": false,
    "createdb": false,
    "database_create": true,
    "enterprise_schema_exists": false,
    "migration_stage_schema_exists": false,
    "runtime_role_exists": false
  },
  "ddl_probes": {
    "create_schema_rollback": {"ok": true},
    "create_role_rollback": {
      "ok": false,
      "type": "InsufficientPrivilege",
      "sqlstate": "42501",
      "message": "permission denied to create role"
    }
  },
  "schema_owners": []
}
```

结论：

- 从 Kubernetes Pod 内到 PostgreSQL 的网络、认证和基本查询真实可用。
- 当前连接用户为 `deeptutor`，连接数据库为 `deeptutor`。
- 该用户可以创建 schema（事务内 `CREATE SCHEMA` 探测成功并回滚）。
- 该用户没有 `CREATEROLE`，且 `dt_enterprise_app` role 尚不存在；首个 migration `0001_identity_sessions.sql` 会尝试创建 `dt_enterprise_app`，因此 #39 的 `schema apply` 失败根因与 Pod 探测一致：`InsufficientPrivilege / permission denied to create role`。
- 如果继续坚持使用单一 PostgreSQL 连接，需要在数据库侧预先创建 `dt_enterprise_app`，或授予当前连接用户足够的 role/grant 初始化权限；否则迁移仍会失败。

### 2026-09-25 单库单数据库用户迁移模型修正

用户确认当前系统只使用一个 PostgreSQL 数据库和一个数据库用户；迁移、verify 与运行态使用同一目标库连接。权限边界由 DeepTutor 应用层鉴权、scope、owner guard、审计和受控入口执行，不再通过数据库内独立运行角色表达业务权限。本节 supersede 上一节关于“必须预先创建 `dt_enterprise_app` 或授予 CREATEROLE”的后续结论；#39 的 Pod 探测仍保留为根因证据。

实现调整：

- Core 与 EduPlus2 扩展迁移 SQL 不再创建固定 `dt_enterprise_app` role，不再执行面向该 role 的 GRANT/REVOKE。
- 租户表继续 `ENABLE ROW LEVEL SECURITY` 并保留 policy，用于 catalog drift 校验和未来角色拆分防线；当前单用户 owner 模式不再使用 `FORCE ROW LEVEL SECURITY`，避免 owner 连接被数据库 RLS 机制阻断迁移/运行。
- PostgreSQL runtime 连接检查允许当前用户是目标库/schema/table owner，但仍拒绝 superuser、createdb、createrole、bypassrls 以及可通过成员关系获得这些能力的用户。
- `MigrationRunner`/企业扩展 runner 接受旧 role-grant/forced-RLS migration checksum 作为兼容历史，但仍执行真实 catalog、constraint、policy 与 RLS flag 校验；新库写入新的 checksum。
- 测试 fixture 改为创建一次性、仅限当前测试库的非特权 owner 用户，覆盖迁移、verify 与应用路径；不再依赖固定 `dt_enterprise_app`。
- `extensions/enterprise/README.md`、`docs/enterprise/06-postgresql-native-store-plan.md` 与本 G1 design/spec 已同步为单库单用户模型。

Fresh verification：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/ruff check $(git diff --name-only | grep -E '\.py$')
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_connection.py \
  tests/persistence/postgres/test_notebook_migration.py \
  tests/persistence/postgres/test_learning_migration.py \
  tests/persistence/postgres/test_reading_migration.py -q
# 120 passed

PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest --asyncio-mode=auto \
  extensions/enterprise/tests/test_persistence.py \
  extensions/enterprise/tests/test_identity.py \
  extensions/enterprise/tests/test_application.py \
  extensions/enterprise/tests/test_cli.py \
  extensions/enterprise/tests/test_cli_recovery.py \
  extensions/enterprise/tests/test_executor.py \
  extensions/enterprise/tests/test_sessions.py \
  extensions/enterprise/tests/test_restore.py \
  extensions/enterprise/tests/test_preflight.py \
  extensions/enterprise/tests/test_process_rebuild.py \
  extensions/enterprise/tests/test_postgres_configuration_adapter.py \
  extensions/enterprise/tests/test_eduplus2_federated_access.py -q
# 144 passed, 1 skipped

PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest --asyncio-mode=auto \
  tests/api/test_default_pg_book_course_consumers.py \
  tests/api/test_default_pg_question_bank.py \
  tests/api/test_default_pg_runtime.py \
  tests/app/test_default_pg_sdk.py \
  tests/cli/test_pg_accounts.py \
  tests/cli/test_default_pg_cli.py \
  tests/persistence/postgres/test_accounts.py \
  tests/persistence/postgres/test_identity_session_core.py \
  tests/persistence/postgres/test_zero_sqlite_runtime_guard.py \
  tests/services/session/test_turn_repository.py -q
# 50 passed, 2 warnings

PYTHONPATH=.:extensions/enterprise/src .venv/bin/ruff check $(git diff --name-only | grep -E '\.py$') && \
PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_business_fixtures.py \
  tests/persistence/postgres/test_migration_stage.py -q && \
git diff --check
# All checks passed; 9 passed; git diff --check exit 0

PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest --asyncio-mode=auto \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 21 passed

openspec validate add-g1-woodpecker-k8s-release-baseline --strict
# Change 'add-g1-woodpecker-k8s-release-baseline' is valid

openspec validate --all --strict
# 16 passed, 0 failed

git diff --check
# exit 0
```

后续：需要 commit/push 后触发新的 test-cn deployment tag；新的真实流水线应复用现有 test-cn DB 连接执行迁移，不再因 `CREATE ROLE` / `CREATEROLE` 阻断。

### 2026-09-25 test-cn pipeline #40 PostgreSQL 14 迁移语法兼容修正

`deploy/test-cn/v1.4.0-rc.31` 触发 Woodpecker pipeline `#40`，使用 commit `8007be34`。

结果：

- release trigger、metadata、frontend artifact image、python deps artifact image、runtime base artifact image、secret preflight、runtime image build 和 pre-deploy check 均成功。
- `deploy-test-cn` 创建 migration Job `dt-migrate-test-cn-v1-4-0-rc-31` 后失败。
- #39 的 `CREATEROLE` 阻断已消失；本次失败发生在 core migration `0005_learning` 的 SQL 语法解析阶段。

Woodpecker/K8s 失败摘要（脱敏）：

```text
job.batch/dt-migrate-test-cn-v1-4-0-rc-31 created
{"pending": ["0001_identity_sessions", "0002_account_profiles_devices", "0003_device_usage_precision", "0004_notebook_entries_categories", "0005_learning", ...]}
企业操作失败（SyntaxError）；检查配置、权限和运行状态
```

临时只读/回滚式语法探测显示真实 PostgreSQL 版本为 `server_version_num=140024`，根因是迁移中使用了 PostgreSQL 15+ 才支持的 column-list `ON DELETE SET NULL (...)` 语法。具体失败点：

```text
psycopg.errors.SyntaxError: syntax error at or near "("
LINE 89: ...hs(tenant_id,owner_id,path_id) ON DELETE SET NULL (path_ref)
```

实现修正：

- 移除 core migrations 与 catalog 中所有 `ON DELETE SET NULL (<column>)` / `ON DELETE SET NULL(<column>)` 形式，避免依赖 PostgreSQL 15+ 语法。
- `0005_learning.sql`：`mastery_path_operations.path_ref` 不再使用 column-list SET NULL；新增 `BEFORE DELETE ON enterprise.mastery_paths` trigger，将相关 `path_ref` 置空后再删除 path。
- `0006_reading.sql`：reading active material FK 改为普通 deferrable FK；保留应用层先清理 active material 的既有逻辑，并新增 `BEFORE DELETE ON enterprise.reading_workspace_materials` trigger 兜底清理 workspace/session 的 `active_material_id`。
- `0007_session_resources.sql`：`session_objects.session_ref` 不再使用 column-list SET NULL；新增 `BEFORE DELETE ON enterprise.sessions` trigger，将相关 `session_ref` 置空后再删除 session。
- 新增迁移资源测试，禁止再次引入 column-list `ON DELETE SET NULL`。

Fresh verification：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/ruff check \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_reading_migration.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_learning_migration.py \
  tests/persistence/postgres/test_reading_migration.py \
  tests/persistence/postgres/test_session_resource_migration.py -q
# 66 passed, 1 warning

git diff --check
# exit 0
```

Kubernetes test-cn 回滚式语法探测：使用 #40 runtime image，挂载修复后的 migration SQL/catalog 到 `/app/deeptutor/persistence/postgres/migrations/*`，使用同一个 `deeptutor-migrator-secrets` DB 连接，在单事务中执行全部 pending core + EduPlus2 migrations，最后显式 rollback。未输出 DSN/密码。

```text
{'server_version_num': '140024'}
TRY core 0001_identity_sessions
...
TRY core 0014_externalized_runtime
TRY extension 0001_federated_access
...
TRY extension 0004_audit_export_jobs
syntax probe ok; transaction rolled back
```

临时 probe Job 与 ConfigMap 已从 `deeptutor-test-cn` namespace 删除。下一步需要提交该兼容修复并触发 `deploy/test-cn/v1.4.0-rc.32`。

### 2026-09-25 test-cn pipeline #42 schema apply/verify 通过，bootstrap 前 PG14 角色检查修正

`deploy/test-cn/v1.4.0-rc.32` 触发 Woodpecker pipeline `#42`，使用 commit `5a55844f`。

结果：

- release trigger、metadata、并行 artifact image、secret preflight、runtime image build、pre-deploy check 均成功。
- `deploy-test-cn` 中 migration Job `dt-migrate-test-cn-v1-4-0-rc-32` 执行：
  - `schema plan` 列出所有 pending migrations；
  - `schema apply` 返回 `{"schema": "apply", "success": true}`；
  - `schema verify` 返回 `{"schema": "verify", "success": true}`。
- 说明 #40 的 PostgreSQL 14 migration SQL 语法问题已修复，test-cn 数据库已成功初始化/验证 DeepTutor + EduPlus2 schema。
- 新失败点发生在随后 bootstrap 阶段，类型为 `UndefinedColumn`。

脱敏 traceback 通过同 image / 同 ConfigMap / 同 Secret 的临时 debug Job 获取：

```text
psycopg.errors.UndefinedColumn: column m.inherit_option does not exist
LINE 6:     WHERE m.inherit_option OR m.set_option OR m.admin_option
```

根因：runtime `Database` 的受限角色检查直接引用了 PostgreSQL 16+ 的 `pg_auth_members.inherit_option` / `set_option` 列；test-cn PostgreSQL 为 `server_version_num=140024`，这些列不存在。

实现修正：

- `_RESTRICTED_ROLE_SQL` 改为通过 `to_jsonb(m)->>'inherit_option'` / `set_option` / `admin_option` 读取成员关系选项，避免直接引用不存在的 catalog 列。
- 对 PG16+：继续按 grant option 判断可继承/可 SET/admin membership 路径。
- 对 PG14：缺少 `inherit_option`/`set_option` 时保守视为 membership reachable，从而仍能拒绝通过成员关系到达 superuser/createdb/createrole/bypassrls 的用户。
- 增加单元测试，禁止重新直接引用 `m.inherit_option` / `m.set_option`。

Fresh verification：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/ruff check \
  deeptutor/persistence/postgres/connection.py \
  tests/persistence/postgres/test_connection.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_connection.py -q
# 57 passed
```

Kubernetes test-cn 连接探测：使用 #42 runtime image，挂载修复后的 `connection.py`，同 ConfigMap/Secret，仅打开 `Database` 连接，不执行 bootstrap 写入；临时 Job/ConfigMap 已删除。

```text
{'database_open': True, 'server_version_num': '140024', 'user': 'deeptutor'}
```

后续：提交修正并触发 `deploy/test-cn/v1.4.0-rc.33`。由于 #42 已成功完成 schema apply/verify，下一次 migration Job 应进入空 plan/verify，然后继续 bootstrap 与后续 rollout/smoke。

### 2026-09-25 test-cn pipeline #44 bootstrap 事务 timeout 兼容修正

`deploy/test-cn/v1.4.0-rc.33` 触发 Woodpecker pipeline `#44`，使用 commit `0f2acf5b`。

结果：

- release trigger、metadata、并行 artifact image、secret preflight、runtime image build、pre-deploy check 均成功。
- `deploy-test-cn` 中 migration Job `dt-migrate-test-cn-v1-4-0-rc-33` 执行：
  - `schema plan` 返回 `{"pending": []}`；
  - `schema apply` 返回 `{"schema": "apply", "success": true}`；
  - `schema verify` 返回 `{"schema": "verify", "success": true}`。
- 说明 #42 的 schema 已持久化成功，#44 不再执行 DDL。
- 新失败点发生在 bootstrap 事务打开阶段，类型为 `UndefinedObject`。

根因：`Database.transaction()` 无条件执行 `set_config('transaction_timeout', ...)`；`transaction_timeout` 是 PostgreSQL 17+ 参数，test-cn PostgreSQL 14.24 不支持。

实现修正：

- `Database` / `SyncDatabase` open 时使用 `current_setting('transaction_timeout', true)` 检测目标库是否支持该 GUC。
- 支持时继续设置 `statement_timeout` + `transaction_timeout`。
- 不支持时自动 fallback，只设置 `statement_timeout` 与 scope 上下文，避免 PG14 报 `UndefinedObject`。
- 增加单元测试覆盖 fallback 选择。

Fresh verification：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/ruff check \
  deeptutor/persistence/postgres/connection.py \
  tests/persistence/postgres/test_connection.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_connection.py -q
# 58 passed
```

Kubernetes test-cn 事务探测：使用 #44 runtime image，挂载修复后的 `connection.py`，同 ConfigMap/Secret，执行真实 `Database.transaction()` 但不写入业务数据；临时 Job/ConfigMap 已删除。

```text
{'transaction_open': True,
 'tenant_id': '671bf679-1b58-57e9-9fe0-a59158f1c2af',
 'user_id': '@probe',
 'statement_timeout': '15s',
 'transaction_timeout': None}
```

后续：提交修正并触发 `deploy/test-cn/v1.4.0-rc.34`。下一次应继续 bootstrap，然后进入 rollout/smoke。

### 2026-09-25 test-cn pipeline #46 runtime 配置挂载、真实域名与对象存储 path-style 修正

`deploy/test-cn/v1.4.0-rc.34` 触发 Woodpecker pipeline `#46`，使用 commit `cfb2b57b`。

结果：

- release trigger、metadata、并行编译、secret preflight、runtime image build、pre-deploy check 均成功。
- migration Job `dt-migrate-test-cn-v1-4-0-rc-34` 成功：
  - `schema plan` 返回 `{"pending": []}`；
  - `schema apply` / `schema verify` 均成功；
  - bootstrap 成功返回 admin 账户摘要。
- 后续 Deployment/Service/Ingress 创建成功，但 backend rollout 超时：`deployment "deeptutor-backend" exceeded its progress deadline`。

根因链路：

1. backend Deployment 只注入 `deeptutor-runtime-secrets`，没有挂载 `deeptutor-deployment-config`，也没有设置 `DEEPTUTOR_POSTGRES_CONFIG=/etc/deeptutor/deployment.json`；Pod startup 报 `postgres_config_missing`。
2. 挂载配置后，`deployment.json` 是 enterprise 部署合同，包含 `object_store`、`lightrag`、`eduplus2` 等扩展段；默认 runtime 原先按严格 core PG config 解析，报 `postgres_config_invalid`。
3. 修复 PG 字段投影后，runtime 能识别对象存储，但 test-cn ConfigMap 中 `object_store.path_style=false` 使 S3 客户端访问 bucket virtual-host。Pod 内网络探测显示 endpoint host 的 DNS/TCP/TLS 正常，而 bucket virtual-host TLS 失败（`SSLCertVerificationError`）。将 test-cn 预置 ConfigMap 的 `object_store.path_style` 修为 `true` 后，对象存储健康探测返回 `objectstore_ready`。
4. 用户确认 test 环境域名应为 `llm-agent-test.f123.pub`，因此将 active environment registry 的 test-cn Ingress host 从占位域名改为真实域名，并放宽 registry 校验：Ingress host 可以是业务域名，不强制包含 env id；隔离边界继续由 namespace、cluster refs、Secret refs、locks、registry path 与 evidence prefix 保证。

实现修正：

- backend 原生 Kubernetes YAML 挂载 `deeptutor-deployment-config`，并设置 `DEEPTUTOR_POSTGRES_CONFIG=/etc/deeptutor/deployment.json`。
- `load_default_postgres_config()` 对同一部署合同投影 `PostgresDeploymentConfig` 字段；`PostgresDeploymentConfig.from_file()` 保持严格行为不变。
- 默认 runtime 在没有 `DEEPTUTOR_OBJECTSTORE_*` env-only 配置时，从部署合同的 `object_store` 段构造 `S3ObjectStoreConfig`，Secret 值仍只通过 `env:<name>` 解析。
- `extensions/enterprise/protected-k8s-release-environments.example.json` 的 test-cn Ingress host 改为 `llm-agent-test.f123.pub`。
- test-cn live ConfigMap 已将非敏感 `object_store.path_style` 修为 `true`；`.secrets/deeptutor-local-enterprise-deployment.json` 原本已为 `true`。

Fresh verification：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/ruff check \
  deeptutor/app/postgres_runtime.py \
  tests/api/test_default_pg_runtime.py \
  extensions/enterprise/src/deeptutor_enterprise/protected_k8s_release.py \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/pytest --asyncio-mode=auto \
  tests/api/test_default_pg_runtime.py \
  extensions/enterprise/tests/test_protected_k8s_release_baseline.py -q
# 29 passed
```

Kubernetes test-cn 探测（使用 #46 runtime image，挂载修复后的 `postgres_runtime.py`，同 ConfigMap/Secret）：

```text
{"available": true, "code": "objectstore_ready", "object_store_configured": true, "retryable": false}
{"config": "/etc/deeptutor/deployment.json", "object_store_configured": true, "runtime_started": true}
```

临时探测 Job/ConfigMap 已删除。后续：提交修正并触发 `deploy/test-cn/v1.4.0-rc.35`，预期 backend Pod 能完成 startup/readiness，然后继续 ingress/smoke 证据采集。
