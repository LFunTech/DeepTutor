# DeepTutor 首次部署数据库边界与回退 Runbook

更新时间：2026-09-28。适用于 `relocate-database-business-rules-to-application` 完成后的 DeepTutor 自有 PostgreSQL 目标库首次部署/重建验收。

## 边界

- 仅限 DeepTutor 自有 PostgreSQL 数据库、DeepTutor 自有 K8s/Secret/CI 配置；不修改 EduPlus2 或任何外部团队仓库、Keycloak、OpenFGA、数据库或运行资源。
- 目标库必须被明确标识为 DeepTutor 测试/预生产/生产中的哪一个实例与库名；未获得该环境的明确发布/清库授权前，不执行清空、重建、迁移 apply、Secret 切换或流量切换。
- 当前系统按首次部署处理：允许在获授权后清空 DeepTutor 目标库并从空库应用当前版本化迁移；本 change 不提供旧应用双写、历史业务行修复或旧数据库兼容运行。
- 运行时必须 PostgreSQL-only；缺 PG DSN、迁移未通过、owner resource root 未配置或 verify 失败时 fail closed，不回退 SQLite、本地隐藏 cache 或旧文件型业务状态。

## 一次性重建流程（需逐项授权）

1. 记录源/目标环境、库名、连接 Secret 名称、应用版本/commit、迁移版本和负责人。
2. 对原 DeepTutor 目标库做物理或逻辑备份，并只读核对备份可恢复；备份 Secret 不写入仓库。
3. 停止所有 DeepTutor writer/worker/后台任务，确认无运行中 turn、offline import、Webhook 入库或管理写操作。
4. 新建空 PostgreSQL 库或清空已授权目标库；不得对 EduPlus2 库执行任何 DDL/DML。
5. 使用本仓库迁移 runner 从空库 apply 到最新版本并立即 verify；重复 apply/verify 必须无待执行计划，最终 catalog 中用户函数、业务触发器、原生 ENUM 与业务枚举/条件 CHECK 为 0。
6. 更新 DeepTutor 运行 Secret 指向新库；启动应用后执行身份、HTTP/WS turn、session owner、Webhook 接收、OMS/Management 审计 smoke。
7. 观察窗口内仅允许 DeepTutor 测试账号/隔离合成数据写入；确认无 SQLite 文件创建、无 schema drift、无权限扩大。

## 回退

- 切流前失败：丢弃新库或保留用于诊断，恢复原 Secret，不启动新版本 writer。
- 切流后失败且未产生必须保留的新业务写入：停止 writer，恢复旧 Secret 与旧应用版本；新库保留只读诊断。
- 切流后已产生需保留的新写入：禁止手工跨库补写；先冻结 writer，导出事件/审计差异并提交新的受控迁移/修复方案，经授权后处理。
- 任一阶段发现外部系统契约缺失、迁移 verify 失败、权限校验异常或 SQLite 运行路径，必须中止并保持 fail closed。

## 本 change 不执行的事项

- 不实际清空 test-cn 或任何目标库。
- 不提交、推送、打 tag、触发发布或切换生产流量。
- 不修改 EduPlus2 代码、CI、权限系统或数据库。
