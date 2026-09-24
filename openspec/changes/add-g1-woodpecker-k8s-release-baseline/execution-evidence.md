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
