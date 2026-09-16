# migrate-all-sqlite-state-to-postgresql final handoff

更新时间：2026-09-15。本文是该 OpenSpec change 的最终交接索引与可审核切换/回退手册；它不是生产 cutover 授权、发布授权、commit 授权或 archive 授权。

## 1. 完成状态与边界

- 本 change 目标：默认 Web/API/WS、CLI、SDK、后台、内置工具和受支持可选渠道的 DeepTutor 业务状态改为 PostgreSQL-only；SQLite/PocketBase 仅作为离线只读旧源或旧格式 fixture。
- 当前任务状态以 `tasks.md` 和 `execution-evidence.md` 为准：1.1–1.47 与 2.1–2.8 已完成或待本文完成后勾选；A2/S3/LightRAG/HugeGraph、B1/B2、C1/C2、G1 生产发布流水线、H 多执行者/HA 不因本 change 完成而自动完成。
- 真实业务数据导入、生产停写窗口、cutover、发布、commit/push/PR、OpenSpec sync/archive 仍需独立授权。
- `.codegraph/` 是本地常驻索引，已由 `.gitignore` 排除，不属于提交制品。

## 2. 版本、制品和证据索引

| 类别 | 证据 / 制品 | 状态 |
| --- | --- | --- |
| OpenSpec 范围 | `proposal.md`、`design.md`、`specs/postgres-only-runtime/spec.md`、`specs/postgres-business-stores/spec.md`、`specs/sqlite-to-postgres-cutover/spec.md`、`inventory.md`、`inventory-baseline.md` | 本 change 验收基准 |
| 执行证据 | `execution-evidence.md` | 逐 task 记录测试、人工验收、边界 |
| SQLite 残余分类 | `sqlite-reference-classification.md` | 运行态禁止路径与离线例外分类 |
| Matrix 协议 | `matrix-storage-protocol.md` | nio 0.26.0 / vodozemac 0.10.0 协议与线程模型 |
| 容量评估 | `capacity-assessment.md`、`.superpowers/sdd/tasks/task-1.47-capacity-p0-results.json`、P1 自动装载记录见 `execution-evidence.md` | P1 一学年容量/重尾验收；不外推 P2/HA |
| Root wheel | `/tmp/deeptutor-task-2.6-dist-7TGlY5/root/deeptutor-1.6.7-py3-none-any.whl` | SHA256 `07387a1f04ee0d55e02d71debd388187e454d2b78661fa28c3c6d4aa089d857b` |
| CLI-only wheel | `/tmp/deeptutor-task-2.6-dist-7TGlY5/cli/deeptutor_cli-1.6.7-py3-none-any.whl` | SHA256 `22761a6727f38fe9f49556a1a486772d151bdf31decd080ac50c733cf800f049` |
| 真实模型 smoke | 临时脱敏事件文件 `/tmp/deeptutor-task-2.5-model-probe.jsonl` 与隔离 smoke 输出目录；摘要见 `execution-evidence.md` 2.5 | 用户人工验收完成；仓库不保存 Secret/token/DSN |
| 企业文档 | `docs/enterprise/readme.md`、`00`–`13`、`docs/postgresql-runtime-runbook.md`、默认 README/CLI-only README/compose 文档 | 已同步 PG-only 当前状态与边界 |

## 3. 迁移 manifest / report 交接要求

### 3.1 Schema migration manifest

- 统一 schema 历史继续使用 `enterprise.schema_history`，本 change 后当前迁移集合为：
  1. `0001_identity_sessions`
  2. `0002_account_profiles_devices`
  3. `0003_device_usage_precision`
  4. `0004_notebook_entries_categories`
  5. `0005_learning`
  6. `0006_reading`
  7. `0007_session_resources`
  8. `0008_cron`
  9. `0009_partner_runtime_status`
  10. `0010_matrix_store`
  11. `0011_marginnote_store`
  12. `0012_offline_import_stage`
- 启动进程只 verify；apply 必须由维护身份运行。运行角色不得拥有 `migration_stage` 权限，也不得拥有 DDL/owner/superuser/bypass RLS 权限。
- 任一 checksum/catalog/RLS/FK/index/policy drift 都阻断业务启动；不得手改 `schema_history` 或跳过 verify。

### 3.2 离线源 manifest / report

真实 SQLite/PocketBase 源导入前必须单独生成并审核 manifest/report；本 change 的测试只使用隔离合成数据，没有导入用户真实旧库。真实 manifest 至少包含：

- freeze ID、源应用/进程停写证据、操作者、生成时间、源清单；
- SQLite Backup API 产物或 PocketBase 只读 export 的文件哈希、sidecar/WAL/SHM 声明、schema 版本、表/集合计数；
- source ID/fingerprint、旧 user/resource → 目标 tenant/owner/resource 映射；
- 每域 row count、内容摘要、引用图、ID 映射、失败/未知机器引用；
- verify/report 输出以及是否允许 promotion；
- 所有 Secret、token、DSN、PocketBase 凭证均不得写入 manifest/report。

## 4. 实际入口正负例验收矩阵

| 入口 / 域 | 正例覆盖 | 负例覆盖 |
| --- | --- | --- |
| Web/API/WS 默认入口 | 2.4 用户人工验收：会话、题库、学习、阅读、导入、删除、CLI/SDK/background 一致 PG 状态 | 缺 PG/schema/权限 fail closed；WS/auth/status/session 负例见 2.3/2.6 测试 |
| CLI / CLI-only / SDK | 2.1 wheel 安装、2.3 CLI/账号、2.4 用户人工 smoke、2.6 SDK/CLI 测试矩阵 | help/version 无连接；业务缺 token/config 拒绝；远程 CLI 不泄露本地 DB Secret |
| 真实模型与教学工具 | 2.5 用户人工验收，provider usage/失败/缺失落盘 | usage 不可得路径标记待核算；不以 mock 或 max_tokens 估算费用 |
| 会话/题库/导入/图书课程 | 1.11–1.15 与 2.6 API/tool/book/course 测试 | owner/FK/删除引用/外部载荷失败/无假空数据 |
| Learning / Reading | 1.16–1.19 与 2.6 API/WS/tool/runtime 测试 | CAS/租约/断线重放/跨 owner FK/无旧 catalog SQLite |
| Cron / Partners / Matrix | 1.20–1.26、2.6 cron/Matrix protocol/企业回归 | 原子领取、旧 worker 拒绝、PG store 故障停止、无 SQLiteMemoryStore/E2EE 降级 |
| MarginNote / Memory | 1.27–1.29、2.6 MarginNote/Memory 测试 | 设备撤销、cursor+tombstone 原子、删除/撤权对 snapshot 可见 |
| 离线导入/cutover | 1.30–1.40 与 2.6 migration/stage/verify/report 测试 | 活动源/坏 WAL/未知映射/坏引用/旧源重放/PG 新写后回退均拒绝 |
| 零 SQLite 运行门禁 | 1.41–1.43、`sqlite-reference-classification.md`、2.6 705 项矩阵 | 文件与 `:memory:` 运行访问拒绝；离线 fixture 不扩大业务白名单 |

## 5. 切换手册（需要单独授权后才能执行）

1. **授权与冻结**：取得真实数据 cutover 授权、停写窗口、目标 DSN/Secret、回退保留期、责任人和通知计划；确认发布制品版本/hash 与本报告一致或重新生成报告。
2. **源端停写**：停止旧 Web/CLI/SDK/cron/Partners/Matrix writer；记录进程退出、时间和 freeze ID。不得让导入器直接读活动 `.db` 或边写边分页导出 PocketBase。
3. **备份与快照**：
   - 目标 PG 做完整备份；
   - SQLite 通过 Backup API 生成独立快照和 manifest；
   - PocketBase 通过获授权只读 export 生成 manifest；
   - S3/外部资源按对应 runbook 固定版本或备份指针。
4. **目标维护态**：开启数据库持久维护门禁，确认所有业务入口拒绝写入，运行角色无 staging 权限。
5. **Schema apply/verify**：维护身份执行 `MigrationRunner.apply()`，受限运行 DSN 执行 `verify()`；记录 schema_history、catalog verify 和实际角色权限报告。
6. **离线 plan/import/verify/report**：对每个源执行 source-check、plan、分块 import、全引用 verify/report；未知版本、缺 owner 映射、坏引用、源变化或摘要不一致必须中止。
7. **Promotion**：只有 verify 全通过后，维护身份在单事务内从 `migration_stage` promotion 到正式表；失败必须完整回滚。
8. **最终 smoke**：使用全新 scratch 启动最终 PG-only 制品，覆盖默认 Web/API/WS、CLI/SDK、cron/background、Matrix/Partners/MarginNote/Memory、真实模型小流量合成 smoke；确认撤权/禁用/设备状态和未确认外部副作用清单。
9. **开放业务**：只有操作者确认 report、身份世代、渠道状态和 smoke 后，才释放维护态并开放业务。
10. **保留证据**：保存 manifest、report、schema verify、制品 hash、日志摘要、用量记录和操作者确认；不得保存 Secret 原文。

## 6. 回退手册

| 阶段 | 允许动作 | 明确禁止 |
| --- | --- | --- |
| promotion 前，目标无新业务写 | 停止候选制品；保留/丢弃未发布 staging；如旧部署和源未变，可恢复旧部署继续服务 | 把未验证 staging 局部复制进正式表；将旧 SQLite/PocketBase 作为新版 runtime backend |
| schema 已升级但尚未开放新业务 | 使用已验证兼容新 schema 的 PG 回退构建；或经批准恢复完整升级前 PG 备份与匹配旧制品 | 跳过 schema verify 启动旧构建；手改 `schema_history` 冒充兼容 |
| PG 已有新业务写入 | 只能使用兼容 PG 制品回退，或经批准执行 PG/S3/相关资源备份恢复并声明损失窗口 | 直接切回旧 SQLite/PocketBase、丢弃 PG 新数据、复活旧密码/token/设备/撤权状态 |
| 外部任务/渠道状态不确定 | 保持维护态并人工核对 operation/execution/channel 记录；必要时标记待核算/待补偿 | 重启后自动重发模型/渠道副作用，或把未知状态改成成功 |
| 恢复旧快照 | 先重新核验身份世代、禁用/撤权、设备信任、渠道密钥和 schedule 状态，再逐步开放 | 恢复后立即开放登录，导致撤权用户、旧设备或旧任务复活 |

任何回退都必须重新运行 schema verify、身份/撤权检查、入口 smoke，并将实际 RPO/RTO/损失窗口写入 report；未实测不得宣称 HA/RPO/RTO。

## 7. 规范收敛 / 替代顺序

当前仓库没有正式 `openspec/specs`；本 change 仍是 active change artifact。未来获得 sync/archive 授权时按以下顺序收敛：

1. 先确认 `replace-rollout-with-three-production-stages` 总纲中 A1/A2/A3/G/H 等未完成项仍保持未勾选，不因本 change 完成而隐式完成。
2. 将 `add-enterprise-pg-identity-session-slice` 的首切片成果作为历史基础保留：PG identity/session/schema 1 证据有效，但旧 local/no-PG 兼容预期由本 change 替代。
3. 再折叠本 change 的三个新能力：`postgres-only-runtime`、`postgres-business-stores`、`sqlite-to-postgres-cutover`。
4. 对冲突 requirement 采用“本 change PG-only 契约覆盖旧 local/SQLite/PocketBase runtime 例外”的语义，不把矛盾条款并存。
5. sync/archive 前后均运行 change-scoped strict 与 all strict validation；archive 后才可更新正式 spec 状态。
6. 未经用户授权不得执行 archive、commit、push、PR 或生产发布。
