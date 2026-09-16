# 全量 PG-only 规划核验记录

日期：2026-09-13。用户已明确取消独立 local/SQLite 模式，默认 Web、CLI、SDK 必须使用 PG。本轮只编写 proposal/design/inventory/specs/tasks 并同步领域文档和总纲；**没有实施迁移代码、运行用户数据库导入或计费模型**。

## 独立读者检查

由独立无对话历史的读者检查默认入口范围、core/企业包/schema 复用、间接存储、导入/回退与规划状态。首轮发现的 6 项已逐项结合源码修订，复核没有剩余架构阻断：

1. PocketBase 退出增加停写只读 exporter、离线 importer 与混合来源映射/验证，不搁置历史。
2. 明确旁路新 PG 与 schema 1 原地升级的不同回退规则，补版本兼容矩阵。
3. 固定独立 migration_stage 权限隔离、分块 staging、全域单事务 promotion 与独立 cutover 门禁。
4. 固定源端停写/Backup API 独立快照、freeze/manifest/hash/sidecar 与只读导入协议，不把活动主文件复制当完整快照。
5. 补结构和 typed JSON 字段族引用图，parent DAG 拓扑分配、GENERATED ALWAYS 显式导入与 sequence 推进；未知机器引用阻断。
6. Matrix 精确 nio/libolm 版本与协议/线程模型实测成为其 schema/adapter/import 的硬前置；仍是待验证任务，不能声称已实现可行。

复核中的两项文字细化也已修订：规范层回退同时禁止旧 SQLite/PocketBase；只拒绝缺失必需 WAL/仍依赖 WAL 的快照，不拒绝正常无 WAL 的独立制品，并区分主库/WAL 权威内容与 SHM 瞬态读协调。

## 实际规划验证

```bash
openspec --version
openspec validate migrate-all-sqlite-state-to-postgresql --strict
openspec validate --all --strict
openspec instructions apply --change migrate-all-sqlite-state-to-postgresql --json
git diff --check
```

- OpenSpec `1.9.0`；新 change strict 通过，全量 **3 changes passed、0 failed**。
- apply：`ready`、**0/55**；这是任务可实施状态，不表示业务通过。
- 首切片保持 **34/34**；总纲保持 **0/90**，没有倒改完成证据或把新目标当已验收。
- 作用域内 Markdown 相对路径 **180 个，0 缺失**；新 tasks 编号连续/无重复、无已勾选项；新规划文件没有待填写内容或模板占位。
- 领域文档中允许独立 local/SQLite 的旧目标和“通用 PG 只在企业包”的约束已同步；旧首切片兼容要求保留历史说明及替代链接，不自动归档或写正式 specs。
- `git diff --check` 通过；保留工作区既有业务代码、企业文档迁移和用户其它修改，本轮未编辑业务实现。

未运行新的 pytest/build/模型/Matrix/业务 PG 验收：本轮是规划，相关实现与真实验证全部列入未勾选任务。后续真实旧库/目标库、停写窗口、模型预算、Matrix 环境与容量阈值须在相应操作前取得明确参数/授权，不能因规划 strict 通过跳过。
