# 维护、后台与离线入口契约（任务 6.16）

本文件只描述 DeepTutor 仓库内受支持入口；数据库超级用户手工 SQL、真实目标库清空/切流和外部 EduPlus2 仓库均不在本 change 授权范围内。

## 1. 受控迁移 / 维护入口

- Core schema 由 `deeptutor.persistence.postgres.migrations.runner.MigrationRunner` 应用和校验；Enterprise 扩展由 `deeptutor_enterprise.migrations.runner.MigrationRunner` 串联 core、EduPlus2 接收端、OMS、Management 四域迁移。
- 迁移 runner 的职责是结构漂移、schema history checksum、受控目录/事实表的最终形状校验；不得用数据库函数、触发器或枚举 CHECK 作为业务值域来源。
- 当前无在线产品写入口的业务目录表：
  - `eduplus2.provider_clients`：产品 Python 源无在线读写；仅作为历史/受控维护目录。Enterprise runner 在 `verify/apply` 中逐行校验非空 client/secret/issuer/base/redirect、`enabled` 布尔、正版本和 `active/rotating/revoked/disabled` 状态。去 CHECK 注入 `future-status` 的负例见 `test_provider_client_maintenance_values_are_verified`。
  - `management.approval_requests`：当前没有正式在线审批写入口；迁移 runner 的 approval snapshot 校验 application、operation、status、school 条件和 reviewer 独立性。未来 5.9 正式审批服务开放前不得把该表作为在线授权入口。
  - `management.action_catalog` 与 OMS `service_definitions` 为版本化目录事实；现有运行路径只读取并由程序校验，新增或退役目录项须走版本化迁移并经 runner/运行读取负例验证。
- 模板角色目录由管理迁移维护；学校/平台自定义角色的在线追加仅走 `publish_custom_role`，该路径独立进行 CAS、权限和 audit 校验。

## 2. 后台任务入口

- Cron 后台读取/执行只使用 PG cron repository/runtime；schedule kind、参数形状、execution status、last_status 和完成时间由程序校验，`tests/persistence/postgres/business/test_cron_repository.py`、`test_cron_runtime.py` 与 `tests/services/cron/test_cron_import_order.py` 覆盖。
- 执行器恢复、学习租约恢复、资源清理、会话对象清理和 Memory snapshot 均在读取候选旧事实后先调用各自应用层验证器；未知状态不得被 SQL WHERE 隐藏或被后台任务覆盖成合法值。相关覆盖已分散在 executor、learning runtime、object/session resource、session deletion 和 memory snapshot 测试。
- 后台任务不是数据库维护后门：它们只能通过产品 repository/service 方法写入，并继承同一值域校验和事务边界。

## 3. 离线导入与核验入口

- SQLite/PocketBase 文件只能作为离线源读取；DeepTutor 运行态禁止 SQLite。离线导入在解析源行、比较既有 PG 目标行、写入 PG 前均使用程序值域校验；未知源值或未知目标值均 fail closed。
- 覆盖入口包括 runtime projection、learning/reading、chat history、Matrix store、PocketBase import 及 `OfflineImportVerifier` 目标核验。
- 本轮 6.16 复核合跑：
  - `test_sqlite_runtime_projection_import.py`
  - `test_sqlite_learning_reading_import.py`
  - `test_sqlite_chat_history_import.py`
  - `test_sqlite_matrix_store_import.py`
  - `test_offline_import_verify_report.py`
  - 后台资源/会话/cron 相关测试
  结果为 `112 passed, 1 skipped`。

## 4. 验证边界

- 本文件完成的是入口契约和维护/后台/离线覆盖确认；不会物理删除旧 CHECK/触发器，删除仍归 7.1–7.7。
- 最终零目标对象、真实 API/CLI/SDK/HTTP/WS/Webhook 全入口、受限角色/RLS 与全套回归仍归 6.17 和 8.*。
