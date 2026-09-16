# PostgreSQL-only 实施证据

## 状态与边界

2026-09-14：实施中，保留原工作区修改，未经提交、发布或真实数据切换。以 [tasks](tasks.md) 的实际勾选为准；底座通过不代表默认 Web、CLI、SDK 或全部领域已经迁移。

本轮数据库验证仅使用自行创建和销毁的隔离 PostgreSQL 测试集群，未连接用户数据库或读取用户业务正文。数据库回归不使用模型 Secret；预算授权后另外完成了指定 `.secrets` 模型字段的脱敏定位，尚未调用付费模型。部分原回归及打包 metadata 测试加载了根 conftest 的真实目录元数据防写快照；后续 PG 测试用 `--confcutdir`、纯 metadata 测试用 `--noconftest` 避免该访问。PostgreSQL 17.9、Python 3.14.7、psycopg 3.3.5、psycopg_pool 3.3.1。新增事务总超时要求 PostgreSQL 17+。

## 1.1：清单基线

- [inventory-baseline](inventory-baseline.md) 和 [inventory-files](inventory-files.json) 固定直接/间接存储、入口、调用方、能力与依赖范围，110 条唯一路径均校验存在。
- 独立审查发现的路径精度、阶段边界、命令证据及 PageIndex 方法名问题均已修正并复审通过。
- 原行为回归基线：core 1547 passed / 4 skipped，独立 capability routing 4 passed，enterprise 133 passed。四项 core skip 分别为缺少 Redis URL 的三项和 Linux `/proc` 专属一项，不作为已验证功能。

## 1.2：共用真实 PG fixture 与领域行为契约

- `tests/persistence/postgres/business/` 通过产品 runner 创建隔离 schema、使用受限角色及 async/sync 池，两个 tenant 各建立管理员和两个普通用户，均经真实 bootstrap/create/login/authenticate。scope/Store factory 仅接受本次 fixture 实际发放的 actor 对象，拒绝 raw scope、自造或复制 actor；这是测试防误用合同，不是恶意 Python 安全沙箱。
- `tests/persistence/contracts/business-domains-v1.json` 固定七个领域的 DTO/ID、排序、分页、冲突/CAS、删除、恢复及 owner 合同，登记并实际运行 **75 个旧行为节点，75 passed**；独立旧格式代表 **7 passed**。Matrix 精确协议仍为后续硬前置，未冻结 schema。
- 审查发现的 factory 发放边界缺陷已修复并复审为 **Spec PASS / Quality Approved**，未发现修复引入的新问题。定向行为 RED **1 failed / 1 passed** → GREEN **2 passed**；修后完整 core PG **91 passed in 18.79s**。controller 独立验证当前五项业务 fixture 测试 **5 passed in 12.76s**，临时 runtime home 无文件生成。
- 证据限制：初始同步 fixture TDD 第二轮未保存独立输出日志，已补记命令并如实披露，不能重建历史证据；该 Minor 保留到最终复核。修复轮 RED/GREEN、最终回归及独立验证日志均已保存，没有以新输出冒充旧记录。
- 证据：`.superpowers/sdd/tasks/task-1.2-report.md`、`task-1.2-rereview.md`、`task-1.2-evidence/fix1-*` 和 `task-1.2-root-fix1-verify.log`。**本项不是七个领域 PG adapter 或完整默认入口已经交付。** 独立 legacy fixture 目前仍引用旧实现，后续退出运行图时须保留离线格式验证。

## 1.3：通用连接与事务底座

- 唯一 core `Database`、`SyncDatabase`、不可变 `TenantScope`，企业旧 import 显式转发；同步完整事务 worker、同步/异步池及排队有界。
- 验证真实 PG 连接复用、双用户 RLS、拒绝高权限/可达高权限角色、事务超时、异常/取消回滚、线程/task 归属、归还后的失效句柄、退出 drain 与池容量。
- 独立审查复现三类缺陷并补充回归：延迟句柄泄漏、同步句柄跨 asyncio task、最后 guard 吞取消后提交。修正后限定范围复审为 Spec PASS / Quality APPROVE。
- 有意拒绝尚未支持的 `stream` / `copy` / `pipeline` 等延迟接口，不冒充完整 psycopg 代理；普通查询与 cursor 保留。若取消时 PG 已确认 COMMIT，抛 `CommitCompletedAfterCancellation`，不能当作回滚或盲目重试。未做 COMMIT 确认丢失瞬间的断网注入。
- 完整修正后验证：**209 passed, 1 skipped**（76 core + 133 enterprise；skip 为显式禁用的真实计费模型测试）。controller 另独立运行新增 ownership 文件：**16 passed in 1.85s**。

```bash
env -u DT_RUN_REAL_MODEL \
  PYTHONPATH="$PWD:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  --confcutdir=tests/persistence tests/persistence/postgres extensions/enterprise/tests -q

env -u DT_RUN_REAL_MODEL \
  PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  --confcutdir=tests/persistence tests/persistence/postgres/test_ownership.py -q
```

`--confcutdir` 避免原根测试 fixture 扫描真实 owner data；测试本身仍使用共用隔离 PG fixture，不使用 SQLite 替身。完整输出、RED/GREEN 和独立审查保存在本工作区忽略目录 `.superpowers/sdd/tasks/task-1.3-*`，组合最终日志为 `task-1.3-fix1-green-verified.log`。该目录是本次未提交执行的恢复记录，不是对外发布制品。

## 1.4：迁移器与唯一 SQL 资源

- `MigrationRunner` 与唯一 `0001_identity_sessions.sql` 下沉至 core，enterprise 旧路径仅转发同一个类。schema 1 SHA256 保持 `06a1a9303d9d45745a31a94ec9a95ce2d864e48ff41be2a6a8d926abdeea7a3f`，没有新增版本、改历史或创建第二套身份/会话库。
- 新增 9 项真实 PG 契约：空库、并发/重复 apply、已有首切片各类 ID/history 保留、真实 catalog 漂移、空库/已有库失败回滚。controller 独立运行 **9 passed in 1.28s**；最后实施回归 **85 core passed + 133 enterprise passed / 1 计费模型 skip**。
- 独立审查发现公开制品缺少 PG 驱动声明、CLI-only 遗漏 SQL 资源；已修复并复审为 Spec PASS / Quality Approved。metadata **21 passed**，controller 使用 `--noconftest` 独立运行 **21 passed in 0.09s**。
- full 与 CLI-only 分别构建 wheel，在新临时 venv 以 `--no-deps` 安装该 wheel 后显式安装实际 PG 驱动；工作目录 `/tmp`、清除 `PYTHONPATH`、无企业包，runner 导入、SQL 资源和固定 hash、依赖 metadata 均通过。**这是限定资源/导入验证，不是 2.1 的全依赖安装与业务验收。** enterprise wheel 已确认不再含 SQL 副本。
- 证据：工作区 `.superpowers/sdd/tasks/task-1.4-report.md`、`task-1.4-rereview.md`、`task-1.4-fix1-regression.log`、`task-1.4-fix1-wheel-smoke.log`；测试文件 `tests/persistence/postgres/test_migrations.py` 和 `tests/test_packaging_metadata.py`。

## 1.5：共用身份、会话与执行生命周期

- `IdentityService`、`PostgresSessionStore`、`ExecutorLease` 下沉至 core 唯一实现，企业 bootstrap/runtime/recovery/CLI 直接消费 core，旧模块仅显式转发同一符号。原企业 issuer、profile、core/hook/schema 拒绝契约保持。
- 新增 core-only 真实 PG 生命周期：屏蔽企业 import，执行 bootstrap/login/authenticate、session/message/turn/event/finalize、取得/释放执行锁及 logout 后失效。controller 独立运行 **1 passed in 1.38s**，并核对原实现与下沉文件仅有 session 相对 import 差异。
- 实施回归 **86 core PG passed、135 enterprise passed / 1 真实模型 skip、23 metadata passed、6 组合兼容定向 passed**；controller 另跑 metadata **23 passed in 0.06s**。组合全套包含企业 shim 测试时显式加入 enterprise/src；无企业路径的单独 core-only 生命周期仍完整通过。
- 独立审查 **Spec PASS / Quality Approved，无待修发现**。CLI-only 和 requirements 已补 identity 的 bcrypt/python-jose 直接依赖；没有新增 SQL 版本或变更 `0001` 字节。
- 证据：`.superpowers/sdd/tasks/task-1.5-report.md`、`task-1.5-review.md`、`task-1.5-root-verify.log` 与 `task-1.5-logs/`。**这仍不是默认 Web/CLI/SDK 已完成 PG-only 切换。**

## 1.6：统一 PG 配置与企业显式适配

- core `PostgresDeploymentConfig` 提供不可变、版本化的显式对象/文件配置；runtime 使用 `DEEPTUTOR_DATABASE_URL`，migration 使用独立 `DEEPTUTOR_MIGRATION_DATABASE_URL`。缺值、冲突、迁移复用运行凭证、非 PG backend、缺明确 user/dbname 等均安全拒绝；Secret 以不透明对象传递，repr/dump/错误不包含值，不发现 `.env` 或生成目录/数据库。
- 企业 bootstrap 与 CLI 实际消费同一 adapter 和全部池/超时参数。远程 session 不需要本机数据库/身份 Secret；schema 命令不装配模型。既有受控 `Enterprise.identity.bootstrap()` 路径改为调用时懒解析，使用短期同一 core 身份服务，日常实例不持有 bootstrap 明文。
- 独立审查发现合法 conninfo 的 quoted password 含 `://` 时被误判为 URI；新增真实失败测试并修复，复审 **Spec PASS / Quality Approved**，无剩余发现。当前未保留 `DEEPTUTOR_STORAGE_BACKEND` 环境变量，只接受显式 `storage_backend=postgres`；以后若引入该兼容变量也须拒绝旧值。
- 修复前完整相关组合 **276 passed / 1 skipped in 77.71s**（skip 为显式关闭的真实模型测试）；局部修复 RED **1 failed** → GREEN **1 passed**，修后配置/企业适配 **28 passed in 1.50s**。controller 独立修后 **28 passed in 1.57s**，临时 runtime home 无文件；未将修前组合结果冒充修后重跑整套。Ruff/格式和 OpenSpec strict 通过，`0001` hash 保持不变。
- 证据：`.superpowers/sdd/tasks/task-1.6-report.md`、`task-1.6-rereview.md`、`task-1.6-combined-regression.log`、`task-1.6-fix1-*`、`task-1.6-root-fix1-verify.log`。**仅配置与企业适配已完成，默认入口的角色/schema/连接 readiness 及全业务装配仍须后续验收。**

## 1.7：默认账号域（修复与独立复审通过）

- 正式追加 `0002_account_profiles_devices.sql`，在同一 users/auth_sessions 扩展账号资料、learner policy 与设备凭证；runner 先验证已应用版本 catalog，再原子升级并校验目标。`0001` hash 保持不变，`0002` 当前 hash 为 `9c55108c497f0c19b91a96e7813b711ed111540851d1c019c1876051884ae005`。
- 原 24 个 auth method/path 保留并接 PG；新增受控 account CLI、显式 tenant+owner 头像/Secret 资源接口，前端账号管理权限与 12..72 UTF-8 字节密码合同对齐。取消缺身份映射全局管理员与 PathService 吞权限错误后的全局回退。头像提交结果不确定时保留候选对象，不删除可能已被 PG 引用的文件。
- 实施修后完整 `tests/persistence + extensions/enterprise/tests` **274 passed / 1 skipped in 91.17s**；skip 为未启用的真实模型验收。controller 独立运行账号、增量 migration、owner resources、默认 auth API、account CLI、device 六组 **34 passed / 1 warning in 39.19s**，临时 HOME 无文件。warning 定位为当前 Starlette TestClient 使用 AnyIO 弃用入口，不隐去该输出。
- 原 auth 相关组合 **105 passed / 1 failed / 1 error**；两个未通过场景仍原样保留：learner 不能关闭 learning policy 的完整 grants 路由，以及教材分配去重复用。这些依赖 task 1.8/资源 provider 接线，不能反转为 404 成功或删测试。完整默认 WS/SDK facade、guardian 当前双方账号校验、全部 capability 和文件生命周期仍未验收；当前不得宣称 PG-only 默认产品已就绪。
- 初次 45 文件独立审查发现两个 Important：亚秒 heartbeat/重登录计费截断，以及 catalog 最终 symlink/缓存 Codex 祖先路径隔离。独立实验 2 failed 复现；fix round 1 的 14 文件精确 delta 已限定复审，**两项均 ADDRESSED，Spec PASS / Quality Approved，零新问题**。追加 `0003_device_usage_precision.sql`，heartbeat/relogin 共用持久微秒余量，source 1/2 升级及回滚保留原设备数据；0001/0002 字节不改。PG catalog/Codex 改用每次操作重开完整祖先的目录 FD 能力，保留 generation/锁/原子写与公开 state callback 协议。
- fix1 正式 RED **13 failed** → 首轮 GREEN **20 passed**；定向组合 **86 passed / 1 已知 warning**，Codex 原回归 **37 passed**；完整 core persistence/enterprise **297 passed / 1 opt-in model skip in 91.74s**。之后 factory 局部兼容调整再跑 owner/cache/callback/factory **20 passed**，未把前一整套结果当作最后调整后的全套。controller 在最终冻结源码独立执行账号、source1/2迁移、owner/cache/callback/factory **34 passed in 12.44s，exit 0**，临时 HOME 无文件。
- task 1.7 账号域现已勾选；两个非阻塞 Minor（物理头像删除断言、AnyIO 弃用依赖）已交 1.15/2.1 和最终审查。跨任务未验证范围和原两个领域依赖失败仍保留，不等于完整 PG-only 产品就绪。证据：`.superpowers/sdd/tasks/task-1.7-report.md`、`task-1.7-fix1-review.md`、`task-1.7-fix1-core-enterprise.log`、`task-1.7-fix1-root-verify.log`。

## 1.8：默认 Web/API PG-only runtime 装配

- 新增 `deeptutor/app/postgres_runtime.py` 作为默认 PG 组合根：默认配置来自显式 `DEEPTUTOR_POSTGRES_CONFIG` 或 `<DEEPTUTOR_HOME>/data/user/settings/postgres.json`，缺配置抛稳定 `postgres_config_missing`；启动只执行 `MigrationRunner.verify()`，再打开受限 `Database`/`SyncDatabase`、取得 `ExecutorLease`、校验目标 tenant 已 bootstrap/ready，不在业务启动中 apply schema 或自动导入旧库。
- `ApplicationContainer.build()` 现在装配真实 `PostgresAuthProvider`、`PostgresSessionStore` provider、`LearningRuntime`/`AsyncLearningStore` provider、`AsyncReadingCatalogStore` provider 与 `OwnerResourceProvider`，并继续加载完整 builtin/plugin capability registry；测试确认 `chat`、`mastery_path`、`immersive_reading`、`course_study` 均存在，不退化成 chat-only。
- 默认 `get_session_store()` 不再按 integrations 自动选择 PocketBase 或 SQLite；无显式 provider 时通过默认 `ApplicationContainer` 取得 PG store。附件入口也能从默认容器取得 PG session resources。旧 `get_sqlite_session_store` 等符号仍只作为显式离线/旧 fixture 兼容 lazy export，后续 1.41/1.43 继续收敛运行态零 SQLite。
- `api/main.lifespan` 去掉启动时 `run_startup_data_migrations()`、PocketBase ping、v1 memory 文件迁移等旧状态搬迁/探测；PG container 成功启动后才向 `app.state` 暴露 auth/resource provider，再继续模型、EventBus 和后台 leader。缺 PG 配置或执行权冲突均保持 `ready=False` 且不会先触发旧迁移、LLM 或后台构造。
- 修正 import/路由装配前的部署级配置读取：model catalog、YAML loader、setup bootstrap 与 logging fallback 在无当前 owner 时使用部署/admin settings 或 runtime log 目录，不因默认 PG 身份尚未建立而回落全局当前用户或在 import 阶段要求业务身份。保留路由 import 所需的部署 settings 文件初始化，但不打开业务 store/PG 连接。

验证（均未连接用户原库、未发起模型调用、未提交/推送）：

```bash
PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  --confcutdir=tests/persistence tests/api/test_default_pg_runtime.py -q
# 3 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  --confcutdir=tests/persistence \
  tests/api/test_default_pg_runtime.py tests/api/test_default_pg_auth.py \
  tests/cli/test_pg_accounts.py tests/persistence/postgres/test_configuration.py \
  tests/persistence/postgres/test_identity_session_core.py -q
# 40 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor/app/postgres_runtime.py deeptutor/app/container.py \
  deeptutor/services/session/__init__.py deeptutor/learning/runtime.py \
  deeptutor/services/config/model_catalog.py deeptutor/api/main.py \
  deeptutor/logging/config.py deeptutor/services/config/loader.py \
  deeptutor/services/setup/init.py deeptutor/services/storage/attachment_store.py \
  tests/api/test_default_pg_runtime.py
# All checks passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m compileall -q \
  deeptutor/app/postgres_runtime.py deeptutor/app/container.py \
  deeptutor/services/session/__init__.py deeptutor/learning/runtime.py \
  deeptutor/services/config/model_catalog.py deeptutor/api/main.py \
  deeptutor/logging/config.py deeptutor/services/config/loader.py \
  deeptutor/services/setup/init.py deeptutor/services/storage/attachment_store.py

openspec validate migrate-all-sqlite-state-to-postgresql --strict
# Change 'migrate-all-sqlite-state-to-postgresql' is valid
```

边界：本项只完成默认 Web/API/启动器的 PG-only 组合与启动前置校验。CLI 业务主体与远程控制仍属 1.9；SDK 默认/显式 provider 生命周期仍属 1.10；学习/阅读/题库/课程/cron/channel 各业务 API/工具的深度接线与零 SQLite 进程级审计仍按 1.13–1.47/2.x 继续执行。

## 1.9：默认 CLI PG-only 身份与受控远程控制

- 新增 `deeptutor_cli/pg_runtime.py`：默认业务 CLI 只从显式环境变量引用读取认证 token（`--auth-token-env` 或已存在的 `DEEPTUTOR_AUTH_TOKEN`），不接受 argv 内联 token；命令开始后启动默认 PG runtime、用同一 `PostgresAuthProvider` 解码当前 token 并安装当前用户，退出时 reset context 并关闭 container，释放单执行者登记。错误输出按 CLI 分类脱敏，不打印 DSN/Secret/token。
- `deeptutor run`、`deeptutor chat`、`deeptutor session list/show/open/delete/rename` 已接入可信主体。`run` 的 capability 解析改走 metadata-only registry，帮助、版本、远程客户端与能力名预校验不构造本地 PG 容器；直接业务模式缺 token、缺 PG 或执行锁竞争均失败且不创建 SQLite。`session list --format json` 输出 PG `session_id`，rich 表格兼容 PG ID 字段。
- 新增 `deeptutor_cli/remote.py` 受控远程客户端：`--server` 只接受无 credential/path/query 的 origin；默认必须 HTTPS，只有显式 `--allow-loopback-http` 才允许 `http://127.0.0.1` 等 IP loopback 测试地址。远程 session 命令通过 HTTP bearer 调用既有服务，不读取本机 PG 配置/Secret，不跟随重定向。
- `run --server` 通过统一 `/ws` turn protocol 将 `start_turn` 发给已认证服务端执行者，WebSocket bearer 不随重定向转发；json 模式输出服务端 stream event 并对 headless `ask_user` 自动提交空回复，rich 模式复用现有 `TurnStreamRenderer`。CLI-only 制品与 `requirements/cli.txt` 补充 `websockets>=12.0` 作为远程 turn 客户端依赖。
- local-debug 复核本机可用资源：PostgreSQL 17.9，`PG_BIN=/opt/pgsql/bin`，`localhost:5432` ready，`smoke postgres` 通过（`local_debug_smoke` 写入成功）。本项未新增 schema/default data/OpenFGA/Keycloak 迁移，未连接用户数据库、未读取用户业务正文、未调用模型、未提交/推送/归档。

验证（均在隔离 PG fixture 或 fake WS 客户端中执行）：

```bash
PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/cli/test_default_pg_cli.py -q
# 8 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/cli/test_default_pg_cli.py tests/cli/test_chat_cli.py \
  tests/cli/test_turn_renderer.py tests/cli/test_pg_accounts.py \
  tests/api/test_default_pg_runtime.py -q
# 35 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/cli/test_default_pg_cli.py tests/cli/test_chat_cli.py \
  tests/cli/test_turn_renderer.py tests/cli/test_pg_accounts.py \
  tests/api/test_default_pg_runtime.py tests/api/test_default_pg_auth.py \
  tests/persistence/postgres/test_configuration.py \
  tests/persistence/postgres/test_identity_session_core.py -q
# 72 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor_cli/pg_runtime.py deeptutor_cli/remote.py deeptutor_cli/main.py \
  deeptutor_cli/chat.py deeptutor_cli/session_cmd.py deeptutor_cli/common.py \
  deeptutor/app/facade.py tests/cli/test_default_pg_cli.py \
  tests/cli/test_chat_cli.py tests/cli/test_turn_renderer.py \
  packaging/deeptutor-cli/pyproject.toml
# All checks passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m compileall -q \
  deeptutor_cli/pg_runtime.py deeptutor_cli/remote.py deeptutor_cli/main.py \
  deeptutor_cli/chat.py deeptutor_cli/session_cmd.py deeptutor_cli/common.py \
  deeptutor/app/facade.py tests/cli/test_default_pg_cli.py \
  tests/cli/test_chat_cli.py tests/cli/test_turn_renderer.py

~/.codex/skills/local-debug/scripts/local-debug.sh status postgres
~/.codex/skills/local-debug/scripts/local-debug.sh smoke postgres
```

边界：本项只完成默认 CLI 的 PG 身份、直接执行者生命周期与远程控制骨架。SDK 默认容器/显式 provider 与远程服务模式仍属 1.10；question/learning/reading/book/cron/channel 等深层 CLI/工具/API 消费者仍按 1.13、1.14、1.17、1.19 及后续任务接通；安装制品 smoke、进程级零 SQLite、真实模型验收和全量 cutover 仍未完成。

## 2026-09-15：边界清理（SQLite→PostgreSQL 范围复核）

用户复核指出本 change 不应扩展到 LLM 调用层。已定向撤回/停放以下越界或中断内容：

- 撤回 `deeptutor/services/llm/*` provider/config/factory、`deeptutor/runtime/agentic/client.py` 中的 `LLMTransportConfig`、SDK 构造参数、环境变量初始化策略和 retry/timeout/trust_env 行为变更；删除未跟踪 `deeptutor/services/llm/transport.py`。
- 删除中断的 SDK remote 半成品 `deeptutor/app/remote.py` 与 `tests/app/test_default_pg_facade.py`；`deeptutor/app/facade.py` 仅保留 1.9 需要的 `metadata_only` capability 查询、PG 容器惰性错误和 `close()` 生命周期，不提供 `DeepTutorApp.remote/direct/borrowed`。
- 移除 `deeptutor/agents/loop/pipeline.py` 与 `deeptutor/services/session/turns/environment.py` 中对 LLM transport 的残留引用；删除未跟踪且混合 SQLite 替身与 LLM SDK/local-authority 假设的临时测试 `tests/services/session/test_configured_turn_runtime.py`，避免把当前范围重新扩大到 LLM provider 行为。
- 清理此前本地验证生成的 `__pycache__` 与 `packaging/deeptutor-cli/build/` 陈旧缓存副本，避免已撤回的 transport 符号通过生成产物残留。

本次清理未新增或修改 PostgreSQL schema/default data、OpenFGA 或 Keycloak migration；未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。1.10 仍未完成也未勾选。

清理后验证：

```bash
grep -R "LLMTransportConfig\|services.llm.transport\|RemoteApplicationClient\|DeepTutorApp\.remote\|DeepTutorApp\.direct\|DeepTutorApp\.borrowed" \
  -n deeptutor tests pyproject.toml packaging requirements \
  --exclude='*.pyc' --exclude-dir='__pycache__' --exclude-dir='build'
# no output

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/cli/test_default_pg_cli.py tests/cli/test_chat_cli.py \
  tests/cli/test_turn_renderer.py tests/cli/test_pg_accounts.py \
  tests/api/test_default_pg_runtime.py -q
# 37 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/cli/test_default_pg_cli.py tests/cli/test_chat_cli.py \
  tests/cli/test_turn_renderer.py tests/cli/test_pg_accounts.py \
  tests/api/test_default_pg_runtime.py tests/api/test_default_pg_auth.py \
  tests/persistence/postgres/test_configuration.py \
  tests/persistence/postgres/test_identity_session_core.py -q
# 72 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor_cli/pg_runtime.py deeptutor_cli/remote.py deeptutor_cli/main.py \
  deeptutor_cli/chat.py deeptutor_cli/session_cmd.py deeptutor_cli/common.py \
  deeptutor/app/facade.py deeptutor/agents/loop/pipeline.py \
  deeptutor/services/session/turns/environment.py tests/cli/test_default_pg_cli.py \
  tests/cli/test_chat_cli.py tests/cli/test_turn_renderer.py
# All checks passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m compileall -q \
  deeptutor_cli/pg_runtime.py deeptutor_cli/remote.py deeptutor_cli/main.py \
  deeptutor_cli/chat.py deeptutor_cli/session_cmd.py deeptutor_cli/common.py \
  deeptutor/app/facade.py deeptutor/agents/loop/pipeline.py \
  deeptutor/services/session/turns/environment.py tests/cli/test_default_pg_cli.py \
  tests/cli/test_chat_cli.py tests/cli/test_turn_renderer.py

openspec validate migrate-all-sqlite-state-to-postgresql --strict
# Change 'migrate-all-sqlite-state-to-postgresql' is valid

git diff --check
# no output
```

## 2026-09-15：1.10 SDK 默认/远程 PG 身份切片（已完成）

- `DeepTutorApp` 新增惰性 `auth_token` / `auth_token_env` 绑定与 async context manager。SDK 业务方法在每次操作前启动同一默认/显式 PG container、用 `auth_provider.decode()` 重验 token 并临时安装 `CurrentUser`，操作结束即恢复 ContextVar；无 token 且无外部身份时继续由 PG scope 拒绝，不回落 SQLite/PocketBase/local admin。
- 显式 `provider_context` 中创建的 SDK 对象保留当时注入的 container；上下文/身份退出后的残留对象再次执行业务读写会因缺身份被拒绝，而不是重新构造默认本地容器或文件型 store。
- `DeepTutorApp(server=...)` 新增受控远程服务模式：只接受显式 HTTPS origin（loopback HTTP 需测试显式 opt-in），HTTP sessions 使用 bearer header、`follow_redirects=False`、`trust_env=False`，WS `/ws` 命令使用 bearer header 且拒绝 authenticated redirect；远程模式不构造本地 application container、不读取 PG DSN/Secret。
- 远程 SDK 覆盖会话 list/get/rename/delete、start/subscribe/regenerate、cancel、submit_user_reply 和 check_active_turn；CLI 远程控制仍由 `deeptutor_cli.remote` 负责，SDK 不反向依赖 CLI 包。
- 新增真实 PG SDK 测试覆盖：token env 读取同一 PG session、撤权后同一 SDK 对象重验失败、默认 PG 配置无身份时拒绝且不生成 `.sqlite/.db`、显式 provider 对象退出上下文后不 fallback；新增远程 SDK mock-wire 测试覆盖无本地 PG 配置时 session HTTP、unsafe origin 先拒绝且不泄露 token/PG、WS bearer 命令序列。该切片未新增 schema/default data/OpenFGA/Keycloak migration，未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

验证：

```bash
PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/app/test_default_pg_sdk.py -q
# RED（实现前）：3 failed, 3 passed（DeepTutorApp.__init__() 尚不支持 server）

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/app/test_default_pg_sdk.py tests/cli/test_chat_cli.py \
  tests/cli/test_turn_renderer.py tests/api/test_default_pg_runtime.py -q
# 33 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/cli/test_default_pg_cli.py tests/cli/test_pg_accounts.py \
  tests/api/test_default_pg_auth.py -q
# 21 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor/app/facade.py deeptutor/app/remote.py tests/app/test_default_pg_sdk.py
# All checks passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m compileall -q \
  deeptutor/app/facade.py deeptutor/app/remote.py tests/app/test_default_pg_sdk.py

openspec validate migrate-all-sqlite-state-to-postgresql --strict
# Change 'migrate-all-sqlite-state-to-postgresql' is valid

git diff --check
# no output
```

边界：1.10 的 SDK 默认容器/显式 provider/远程服务模式与 HTTP/CLI 权限回归已覆盖并勾选。学习/阅读/题库/课程等领域 SDK/API 深度接线仍归属 1.13/1.14/1.17/1.19；进程级零 SQLite、安装制品和真实模型验收仍未完成。

## 2026-09-15：1.13 question notebook / quiz-results / imports / 工具 PG 接线切片（已完成）

- `question_notebook` 原 API router 的 entries/categories/stats/materials 全部改为 `get_session_store()`，在 provider 上下文中消费当前 PG `PostgresSessionStore`；新增真实 PG API 测试覆盖 upsert/list/stats/category bulk link、跨 owner 不可见和禁止 SQLite fallback。
- `sessions/{session_id}/quiz-results` 改为 `get_session_store()`；新增真实 PG 测试覆盖 quiz-results 写入 PG session message + notebook entry，并由 `run_question_bank()` 和真实 `QuestionBankTool.execute()` 读取同一 PG 数据。
- `imports/chat-history` POST/GET 改为 `get_session_store()`；新增真实 PG 测试覆盖 Codex import 写入/列出 PG imported sessions，禁止运行期 SQLite fallback。
- `deep_question` quiz history loader 改为 PG provider；无 store/config 错误不再吞成假空历史。新增真实 PG 测试覆盖 history 从 PG notebook entries 读取；旧 SQLite fixture 测试改为显式 legacy owner + 显式 `get_session_store` patch。
- `question_bank` 工具默认 store 改为 `get_session_store()`；`user_has_question_bank()` 不再导入 SQLite，遇到 async PG probe 时不泄漏 coroutine、不阻塞事件循环，并挂载真实 PG-backed 工具，由工具调用返回明确 empty/非 empty 结果。
- 新增 `web/tests/question-bank-section-pg-smoke.spec.tsx` 覆盖原题库前端页面入口：页面通过 `/api/question-notebook/entries|categories|stats|materials` 读取已提交题库行；entries 失败时显示 PG/provider 错误，不把失败替换为 “No entries yet” 假空态。该前端 smoke 使用真实页面组件与原 API transport；真实 PG authority 由同组后端 API/工具测试覆盖。
- 本切片未新增 schema/default data/OpenFGA/Keycloak migration，未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

验证：

```bash
PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/api/test_default_pg_question_bank.py -q
# RED（实现前）：3 failed（question_notebook/quiz-results/history 仍走 SQLite 或假空）

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/api/test_default_pg_question_bank.py::test_quiz_results_route_and_question_tool_use_pg_provider -q
# RED（自动装配实现前）：1 failed（user_has_question_bank() false / coroutine 兼容问题）

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/api/test_default_pg_question_bank.py::test_imports_route_uses_pg_provider_without_sqlite_fallback -q
# RED（imports 接线前）：1 failed（imports route 仍走 get_sqlite_session_store）

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/api/test_default_pg_question_bank.py tests/api/test_imports.py \
  tests/api/test_question_bank_api.py tests/tools/test_question_bank_tool.py \
  tests/agents/question/test_pipeline.py::test_history_loader_returns_session_scoped_entries \
  tests/agents/question/test_pipeline.py::test_history_loader_returns_empty_for_unknown_session -q
# 43 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/app/test_default_pg_sdk.py tests/api/test_default_pg_question_bank.py \
  tests/api/test_imports.py tests/api/test_question_bank_api.py \
  tests/tools/test_question_bank_tool.py \
  tests/agents/question/test_pipeline.py::test_history_loader_returns_session_scoped_entries \
  tests/agents/question/test_pipeline.py::test_history_loader_returns_empty_for_unknown_session \
  tests/cli/test_chat_cli.py tests/cli/test_turn_renderer.py \
  tests/api/test_default_pg_runtime.py -q
# 76 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/cli/test_default_pg_cli.py tests/cli/test_pg_accounts.py \
  tests/api/test_default_pg_auth.py -q
# 21 passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor/app/facade.py deeptutor/app/remote.py \
  deeptutor/api/routers/question_notebook.py deeptutor/api/routers/sessions.py \
  deeptutor/api/routers/imports.py deeptutor/tools/question_bank.py \
  deeptutor/agents/question/history.py deeptutor/agents/_shared/tool_composition.py \
  tests/app/test_default_pg_sdk.py tests/api/test_default_pg_question_bank.py \
  tests/api/test_question_bank_api.py tests/api/test_imports.py \
  tests/tools/test_question_bank_tool.py tests/agents/question/test_pipeline.py
# All checks passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m compileall -q \
  deeptutor/app/facade.py deeptutor/app/remote.py \
  deeptutor/api/routers/question_notebook.py deeptutor/api/routers/sessions.py \
  deeptutor/api/routers/imports.py deeptutor/tools/question_bank.py \
  deeptutor/agents/question/history.py deeptutor/agents/_shared/tool_composition.py \
  tests/app/test_default_pg_sdk.py tests/api/test_default_pg_question_bank.py \
  tests/api/test_question_bank_api.py tests/api/test_imports.py \
  tests/tools/test_question_bank_tool.py tests/agents/question/test_pipeline.py

openspec validate migrate-all-sqlite-state-to-postgresql --strict
# Change 'migrate-all-sqlite-state-to-postgresql' is valid

git diff --check
# no output

cd web && npm run test:unit -- tests/question-bank-section-pg-smoke.spec.tsx tests/imports-api.spec.ts
# Test Files 2 passed; Tests 3 passed

cd web && npx eslint tests/question-bank-section-pg-smoke.spec.tsx
# no output

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest \
  tests/api/test_default_pg_question_bank.py tests/api/test_imports.py \
  tests/api/test_question_bank_api.py tests/tools/test_question_bank_tool.py \
  tests/agents/question/test_pipeline.py::test_history_loader_returns_session_scoped_entries \
  tests/agents/question/test_pipeline.py::test_history_loader_returns_empty_for_unknown_session -q
# 43 passed in 5.85s

openspec instructions apply --change "migrate-all-sqlite-state-to-postgresql" --json
# progress 16/55；task 1.13 done=true；firstPending=14
```

边界：本次覆盖 1.13 的 API/router、真实工具、history、工具自动装配和原前端题库页面入口。1.14 图书/课程/materials/mastery consumers、1.17 learning API/后台、1.19 reading API/SDK/工具仍未完成，继续按各自任务推进。

## 未完成验收

除下方已单列完成的后续切片外，其余任务仍须逐领域接通并验证；共用 fixture 与旧行为契约不等于全部领域 PG 业务已经迁移。真实 Matrix 完整收发/重启、全部入口零 SQLite、最终安装制品、全量迁移与恢复、容量阈值及付费模型验收均未完成，不能由上述底座测试替代。

用户已明确本次真实模型验收暂不设置调用数和供应商费用上限，配置使用 `.secrets` 中指定内容；预算授权已取得，但上述本地回归未因此自动成为真实模型验收。后续仍须逐调用落盘用量和失败/缺失记录。

## K12 容量评估（2026-09-14，目标而非实测）

用户已委托由实施方评估容量，形成 [容量基线 v1](capacity-assessment.md)：P1 为3,000学生/7,800账号/600在线及一学年存量，明确事件放大、重度用户、p95/p99/池等待、导入窗口及 P2 扩容边界。此处只完成评估与源码/官方测量口径核查，未执行该规模造数/压测/导入，task1.47不勾。模型预算授权不等于无限供应商配额，也不授权采购容量或真实数据cutover。


## 1.11：题库/分类 PG schema 依赖切片

- 追加 `0004_notebook_entries_categories.sql`（SHA256 `37baf9172c09031a6bb901daa42be7e7dde758ec549b1e7e462638fa1cf6fadf`），0001–0003 字节不变。三表完整条目字段/整数 ID、CAS version、FORCE RLS 与同 tenant/owner 复合 FK；真实 execution turn 使用不可写派生引用，book block 不伪造 turn。分类 ASCII-only 大小写去重由数据库唯一键保证。
- followup目标删除被引用时明确拒绝，source session/entry/category的原子级联关系保持；typed book/path/reading授权、受控删除错误和Store/API接线仍是1.12–1.19硬依赖，不因schema完成宣称题库业务迁完。
- runner保留source1/2/3 catalog，升级前验源、目标失败整事务回滚，检验生成表达式/default/identity/collation/索引。实际两连接观察锁等待、独立reader验证中断写入不可见。
- TDD：新schema **20 failed**、新迁移 **16 failed** → 初轮 **36 passed**；自审默认值漂移 **2 failed** 后修复。最终core persistence+enterprise **342 passed / 1真实模型opt-in skip in 162.42s**，无warning。controller最终源码独立两组 **45 passed in 70.10s，exit0**，临时HOME无文件。Ruff/format、change strict、git diff --check通过。
- 独立审查 **Spec PASS / Quality Approved**，无Critical/Important。1个Minor：literal-search SQL测试缺干扰行排除断言，交1.12真实Store escaping测试与最终审查，不隐去。证据：`.superpowers/sdd/tasks/task-1.11-report.md`、`task-1.11-review.md`、`task-1.11-final-core-enterprise.log`、`task-1.11-root-verify.log`。


## 1.12：题库/分类 PG Store（修复与限定复审通过）

- 同一 `PostgresSessionStore/Database/TenantScope` 接入全部18个条目/分类方法；中立Query/Protocol保留原DTO、整数ID、批量处理计数、图片缺省/清空、答题趋势/复习字段、过滤/统计/分类与literal搜索，不新增数据库或身份权威。schema1–4字节不改。
- 新增兼容version/expected_version CAS、受控版本/引用/游标错误和有界keyset导出；async probe真实SELECT EXISTS、故障不伪装空。运行期upsert与游标首屏同owner短事务锁，首屏等待先前writer后建立自动递增ID fence，排除后续插入；这是Store insert边界，不是跨页内容MVCC快照，后续显式ID导入必须维护停写。
- 初次方法RED **8 failed**、Protocol RED **1 failed**，最终初轮 **354 passed / 1 opt-in model skip**。独立审查真实PG发现5个Important：关联/删除竞争漏FK、迟提交插入破坏导出、ASCII搜索大小写、cursor溢出、分类显示排序；没有用已有GREEN掩盖。
- fix round1正式 **9 failed**，I4追加bigint边界 **3 failed / 4 passed** 后修复。实际两个低权Store与commit暂停/数据库锁屏障验证迟提交，分类锁定重验保留bulk有效项；恢复ASCII-only搜索与name字节序，严格cursor类型/范围；并发分类测试不再假定胜者。
- 所有修正后相关core persistence+enterprise **366 passed / 1 skipped in 192.94s，exit0，无warning**。controller在最终冻结源码独立运行新Store及core-only生命周期 **25 passed in 37.27s，exit0**，临时HOME无文件；Ruff/format/compileall、change strict和diff check通过。唯一skip仍为未到执行阶段的真实模型，不是预算未获授权。
- 限定复审 **Spec PASS / Quality Approved**，I1–I5及M1全关闭，零新发现；1.11 literal搜索缺干扰行Minor也由实际Store四字段/非ASCII/通配符正反例补足。证据 `.superpowers/sdd/tasks/task-1.12-report.md`、`task-1.12-review.md`、`task-1.12-fix1-review.md`、`task-1.12-fix1-final-core-enterprise.log`、`task-1.12-fix1-root-verify.log`。
- 原尝试旧SQLite测试组合 **80 passed / 5 failed / 27 errors** 因未加载root owner fixture失败，报告原样保留，不称旧套件全绿；其领域断言已在真实PG补测，完整旧测试收敛仍由1.41/1.44执行。**仅Store完成，1.15/1.16/1.18 已在后续段落另列完成；1.13真实API/前端/工具的async probe、version/cursor及错误映射、1.14、1.17、1.19 typed资源/完整删除与默认入口仍未完成。**


## 1.15：会话资源、导入与删除 provider（修复与限定复审通过）

- 追加 `0007_session_resources.sql`（最终 SHA256 `f2a46b75d43c9617b3cb4a07b084a156d4e0be52e0f47d5a512f4a5a463eca69`）与 `session_resources_catalog.json`（SHA256 `d9a48877221487ab833dd47e2ce4aeb64a35d0a36706ef5d2b2cfc9f7f5eede3`）；0001–0006、learning/reading catalog 按 1.15 before manifest 校验字节不变。新增 session incarnation、删除 token、unresolved deps、`session_objects`、`message_objects`、`session_references` 与资源清理账本，继续使用同一 MigrationRunner、复合 FK、DEFERRABLE 约束与 FORCE RLS。
- 会话资源生命周期改为 PG 意图记录、不可见候选、随机不可复用 object key、事务外安全写入与提交后 ready 发布；commit unknown 保守保留候选并依 operation token 对账。删除统一走共享 lifecycle：先身份/执行门禁，再取消/引用清理；跨域 FK 冲突和外部载荷清理失败返回受控状态，不把 pending 清理伪装成已完成，也不按旧 `session_id` 误删新代际对象。
- 恢复默认会话完整行为：PG import/list_imported 与普通历史分离，重复导入保留 attribution 回填语义；`PostgresAttachmentStore`、附件下载、消息删除、会话删除、artifact/generated workspace 附件消费与外部资源失败语义接入真实 PG authority。同步阅读组合和 async Session Store 通过 `session_workflows` 复用原 create/title/preferences/audit/DTO/删除算法，公共 `SessionExecution` 仍只开放封闭 `SessionStatement` 三操作，避免回到任意 SQL 通道。
- 初次独立审查发现两个 Important：I115-01 真实 `_request_snapshot_metadata` 中的 `metadata.request_snapshot.attachments` 被通用 metadata 校验拒绝，顶层附件测试绕过完整消费者；I115-02 真实请求历史使用 `masteryPathId`、`readingMaterialId`、`readingWorkspaceId` camelCase，未投影 typed FK，解除 preferences 后会留下可重试悬空历史引用。
- fix round1 仅修复上述两项：只对精确 `metadata.request_snapshot.attachments` 路径开放形状并复用同 scope、同会话代际、ready/filename 的 `link_attachments()` 登记；其它附件/provider 路径继续 fail-closed。`session_references.py` 与 0007 回填把真实 snapshot camelCase 规范化为既有 typed kind，并在同 scope 目标存在时登记 FK，原 JSON 保持不变；缺失目标或错误 shape 拒绝。
- 初轮实施完整 `tests/persistence extensions/enterprise/tests` **555 passed / 1 skipped / 1 warning in 512.54s**，controller 独立运行 session import/resources/deletion/composition/resource races/resource migration/avatar physical **73 passed / 1 warning in 131.51s**，Ruff/format/compileall/OpenSpec strict 通过。fix1 实施扩大定向 **180 passed in 209.87s**；controller corrected3 独立验证 snapshot/reading composition/resource migration **44 passed in 55.84s，HOME_FILES=0**，40 个 Python 文件 Ruff/format/compileall、diff check、OpenSpec strict 与 42 当前文件/8 历史基线 hash audit 均通过。controller 追加完整 PG persistence/enterprise 回归 **575 passed / 1 skipped / 1 warning in 589.33s，HOME_FILES=0**。
- 限定复审 **I115-01/I115-02 均 ADDRESSED，零新 Critical/Important breakage**。证据：`.superpowers/sdd/tasks/task-1.15-report.md` 第9节、`task-1.15-review.md`、`task-1.15-fix1-review.md`、`task-1.15-fix1.patch`、`task-1.15-fix1-root-verify-corrected3.log`、`task-1.15-fix1-root-full.log`；42 路径 fix1 final manifest SHA256 为 `79016d0a8e4058c5c7031b8418c22f869816cb2d7885c9228411fbfad6c54eb8`。已披露 `extensions/enterprise/src/deeptutor_enterprise/runtime.py` 的 extra-before-2 是修改后重建 preimage，证据弱于正式 before；本轮 fix1 未再修改该文件。
- **仅会话资源/导入/删除 provider 与完整 Session 组合边界完成。** 缺 KB/workspace/output 等尚无 PG authority 的来源继续 fail-closed，不用万能 ID 放行；1.13/1.14 仍须接通题库/图书/课程/工具消费者，1.17/1.19 仍须接通学习/阅读 API/SDK/工具和默认入口，1.41–1.47/2.x 仍负责删除旧运行路径、容量、安装制品与真实模型验收。没有提交、推送、归档、连接用户库或发起模型调用。


## 1.16：学习领域 PG schema / Store（修复与限定复审通过）

- 追加`0005_learning.sql`（SHA256 `4ca565a95b3d7540ad0b24d7a7ec824327b2907379943eb7825e01ca86621398`）及静态`learning_catalog.json`；0001–0004保持字节不变，仍同一MigrationRunner，验证1–4源升级/源漂移/目标失败整次回滚。路径权威聚合、KP引用投影、membership、interaction/event、topic/source、typed turn/operation lease同tenant+owner复合FK/FORCE RLS；不造假父资源或管理会话。
- 24个同步Store领域接口及8个Transaction接口，以有界SyncDatabase完整worker unit＋async facade组合；同一连接原子提交学习、事件、来源与mastery题库。跨线程/退出句柄拒绝，捕获内部失败仍回滚，输入version和事件通知只在确认commit后推进；未知提交不假成功或重发。
- typed执行权来自真实ExecutorLease/当前backend锁/worker fence，普通owner管理操作有持久operation终态；受控确认stopped后恢复，不TTL抢占、不重演外部动作。删除失败完整回滚operation/lease/path，成功后保留终态并幂等finish；KP移除retire保留合法历史但新引用仅active。
- 真实page/iterator支持同revision事件的`(revision,event_id)`游标；兼容完整列表最多1000，超限显式分页要求，单页最多200。topic page/get_topic最终使用单条有界CTE/lateral SQL获得同版progress/meta/source/count/active，未改共享隔离或增读写锁；畸形巨大整数游标规范为ValueError。
- 全量回归曾暴露WS退休取消竞态：只读PG已提交后取消被误报subscription_failed；确定性复现后统一turn/session具体task退休判定，覆盖get_turn及safe_send身份复验窗口，保留非退休/真实PG故障/撤权fail-closed。独立PG import验证无旧SQLite runtime、无连接与HOME落盘，原显式legacy导出仅中间兼容，默认回退最终删除仍未完成。
- 初轮冻结全量423passed/1opt-in skip后，独立review真实PG发现topic并发DELETE KeyError（1failed3.41s）；root另复现游标OverflowError。Fix round1对最终8新增例全部有效RED，修后65定向passed，再在31文件冻结后完整**431 passed / 1 skipped in 308.40s，exit0，HOME0，前后hash一致**。root独立修后**28 passed in 65.95s，exit0，HOME0**；WS修复后的独立13passed9.98s亦保留。Ruff/format/compileall、change strict、diffcheck通过。
- 限定复审**Spec PASS / Quality Approved**，I-1/I-2全部ADDRESSED，零新发现/未关闭项。报告`.superpowers/sdd/tasks/task-1.16-report.md`第7节为修后最终证据；原审查`task-1.16-review.md`、复审`task-1.16-fix1-review.md`、日志`task-1.16-logs/fix1-final-regression.log`、`task-1.16-fix1-root-verify.log`；31文件manifest SHA256 `35aa462c00f3512f4119e0a960fb01483dbd94b9c13f2c990082d3eb79f94a8f`。原失败、误定位、fixture发现错误与纠正后相同目标结果完整保留，未改夹具或删测试制造通过。
- **仅本领域底座任务完成。** 1.17真实API/工具/后台/导航一致性与分页消费、1.18/19阅读、其它业务域、默认Web/CLI/SDK、离线导入、P1容量与安装制品/真实模型验收仍待完成。模型skip是本task未进入2.5，不是缺少用户预算授权；本change仍无真实模型调用、无用户数据库操作、无提交/推送/归档或发布。


## 1.18：阅读目录 PG schema / Store（修复与限定复审通过）

- 追加 `0006_reading.sql`（SHA256 `a0d69b15fc62d9786f453e8b7de430745b1806a5c53983e909972c90e501b62e`）与 `reading_catalog.json`（SHA256 `f69813df4f629613d9350b9b551f751872250a26164c00913c55452cbe0f0675`），0001–0005 历史 SQL/JSON 字节保持。阅读 materials/workspaces/tabs/sessions/links/collections 建立同 tenant+owner 复合 FK、FORCE RLS、DEFERRABLE 约束与 owner 级 advisory 锁；正式旧基线 schema1→6 已验证，中间未发布 schema4/5 自由文本 reading 来源无父资源时安全拒绝并整次回滚。
- `PostgresReadingCatalogStore` 保留旧 28 个同步公开目录方法，并补充 opt-in CAS、summary 与 keyset page 能力；materials/workspaces/sessions/links/collections 都有稳定唯一分页。旧完整读取在超过 500 嵌套结果时显式 `ReadingPageRequired`，不静默截断；大 workspace 写操作默认保留完整 DTO，小规模兼容，超大规模必须显式 `return_summary=True` 供 1.19 接线分页消费。
- 与 notebook 共用 owner 锁顺序，attach 最终为 owner advisory → 真实 chat session `FOR UPDATE` → workspace → reading session，真实 `pg_blocking_pids`/NOWAIT 回归证明不再形成反向锁序。`locked_content()` 只在 bound unit 内返回 refcount 计划；它不是锁释放后的文件删除许可，文件 stage/finalize/恢复仍由 1.19 完成交付。
- 初次独立审查发现 Important R118-01：`SessionExecution.execute(sql, params)` 虽不暴露 Python commit/rollback 方法，但接受任意 SQL 文本，可信 callback 可执行 `COMMIT` 提前提交 reading 写并释放事务级 owner 锁；真实低权 PG probe 为 **1 failed / 3.24s**，材料在后续 callback 失败后仍持久化。原 475 passed 未覆盖此路径，不能作为反证。
- fix round1 用封闭 `SessionStatement` 三操作（`CREATE_ROW`/`GET_ROW`/`LOCK_ROW`）替代任意 SQL 通道，scope 仅由 unit 注入，非法文本、事务/role/scope 命令、多语句、伪 token、错误参数和 psycopg Composable 均在到达驱动前拒绝并 poison 当前 unit；callback 吞异常也不能提交。`session.py` 仅共享原 `_create_session` INSERT 与 `_session` SELECT/FOR UPDATE 模板，原验证、标题规范化、audit、DTO、依赖/删除算法未复制到 reading，CREATE_ROW 仍只是行级 primitive。
- fix1 新增真实 PG composition 回归覆盖原 COMMIT probe、合法固定操作、参数中普通 `COMMIT` 文本、非法文本/伪令牌、scope、句柄跨线程/失效、owner 锁保持、取消与 close。实施定向 **128 passed**，冻结后完整 `tests/persistence extensions/enterprise/tests` **482 passed / 1 opt-in model skip in 374.02s，exit0，HOME_FILES=0，无失败/警告**。controller 独立修后运行 `test_reading_composition.py + test_reading_catalog.py + test_reading_isolation.py` **31 passed in 77.30s，HOME_FILES=0**，Ruff/format/compileall/OpenSpec strict/hash audit 均通过。
- 限定复审 **R118-01 ADDRESSED，零新 Critical/Important/Minor breakage，Spec PASS / Quality Approved**。证据：`.superpowers/sdd/tasks/task-1.18-report.md` 第8节、`task-1.18-review.md`、`task-1.18-fix1.diff`、`task-1.18-fix1-logs/frozen-full-suite.log`、`task-1.18-fix1-root-verify.log`；28 路径最终 manifest SHA256 为 `790325bdff456644162e611cf0e5c5d6e18bca5816b44480177e177c06c5df17`。
- **仅阅读目录 PG Store 与受控 Session 组合边界完成。** 1.15 已另列完成会话资源/导入/删除 provider；1.19 仍须接通 reading API/SDK/工具、真实文件载荷/恢复和 summary/page 消费；1.31/1.34/1.39 仍负责完整父资源/typed 来源导入；1.47、2.1/2.4/2.5 仍负责容量、安装制品与真实模型验收。没有提交、推送、归档、连接用户库或发起模型调用。


## 2026-09-15：1.14 book / course / topic materials / mastery / cron 消费者 PG 接线（已完成）

- `deeptutor/book/inputs.py` 的 chat 选择与 question notebook 输入改为 `get_session_store()`，在当前 provider 上下文中读取 PG `PostgresSessionStore`；不再直接打开 SQLite session factory，避免 PG 数据被渲染为假空上下文。
- `deeptutor/api/routers/book.py` 的 focus-check quiz attempt 同步改为当前 session provider，图书页面答题可写入同一 PG question bank，并保留 legacy SQLite fixture 仅作显式旧格式测试。该 API 路由本轮只替换内部 store 来源，未新增/放宽路由或认证授权边界。
- `courses_state`、`learning.sources.topic_materials` 与 `capabilities.mastery.tools` 使用已下沉的 PG `LearningRuntime`/source provider；新增真实 PG 覆盖课程错题计数/弱分类、chat 与 question-bank topic material 载荷，以及 mastery build 工具在 typed turn authority 下写入 PG path。
- `deeptutor/services/cron/executor.py` 的 chat reminder 消费者改为当前 session provider；新增真实 PG 覆盖 cron 执行向 PG 会话追加 user/assistant 消息与 `cron_job_id` metadata。注意：本项只迁移 1.14 所列“cron 会话消费者”，cron repository/service/API/CLI/tool 的持久 schedule/execution 全面迁移仍属于 1.20/1.21。
- 1.14 目标路径中再次扫描 `get_sqlite_session_store|SQLiteSessionStore|sqlite_store|chat_history.db|.sqlite|sqlite3` 无匹配；旧 SQLite 仅保留在显式 legacy fixture/离线路径，不在上述业务消费图中。
- 本切片未新增或修改 PostgreSQL schema/default data、OpenFGA 或 Keycloak migration；未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

验证：

```bash
PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest \
  tests/api/test_default_pg_book_course_consumers.py -q
# 6 passed, 2 warnings in 6.76s

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest \
  tests/api/test_default_pg_book_course_consumers.py \
  tests/api/test_book_quiz_attempt_notebook.py \
  tests/book/test_worker_context.py tests/services/cron/test_cron_tool.py -q
# 23 passed, 2 warnings in 6.79s

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_learning_sources.py \
  tests/persistence/postgres/business/test_learning_runtime.py::test_real_quiz_grade_and_notebook_are_atomic \
  tests/persistence/postgres/business/test_learning_runtime.py::test_hint_cache_is_scoped_and_course_reads_pg \
  tests/persistence/postgres/business/test_learning_runtime.py::test_course_unsupported_source_index_is_explicit_upgrade_error \
  tests/persistence/postgres/business/test_learning_runtime.py::test_teaching_tool_requires_typed_turn_not_client_ids -q
# 10 passed in 22.85s

rg -n "get_sqlite_session_store|SQLiteSessionStore|sqlite_store|chat_history\.db|\.sqlite|sqlite3" \
  deeptutor/book deeptutor/api/routers/book.py deeptutor/services/courses_state.py \
  deeptutor/learning/topic_materials.py deeptutor/capabilities/mastery/tools.py \
  deeptutor/services/cron/executor.py
# no output (exit 1)

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor/book/inputs.py deeptutor/api/routers/book.py \
  deeptutor/services/cron/executor.py \
  tests/api/test_default_pg_book_course_consumers.py \
  tests/api/test_book_quiz_attempt_notebook.py
# All checks passed

PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m py_compile \
  deeptutor/book/inputs.py deeptutor/api/routers/book.py \
  deeptutor/services/cron/executor.py \
  tests/api/test_default_pg_book_course_consumers.py \
  tests/api/test_book_quiz_attempt_notebook.py
# exit 0
```

曾追加运行两组旧 no-PG/SQLite 单元回归作为影响面探测，结果分别为 `11 failed, 21 passed, 1 warning` 与 `67 failed, 46 passed, 7 errors`；主要失败原因是旧测试仍直接构造 legacy SQLite store、缺少当前 owner/PG Secret，或调用已改为显式 PG runtime 的同步 fallback。这些结果已保留为 1.44“将旧 local 无 PG 预期改为新契约”的待办证据，未被用来宣称旧套件全绿，也不扩大 1.14 的完成范围。

边界：1.14 仅完成图书/课程/materials/mastery/cron 的当前 PG 消费者接线。1.17 仍负责 mastery/learning API、事件 hub、后台恢复和课程关联的完整接通；1.19 仍负责 reading API/SDK/工具；1.20/1.21 仍负责 cron schedule/repository/service/API/CLI/tool 的 PG 持久化与派发语义；1.41–1.44/2.x 仍负责删除旧运行路径、进程级零 SQLite 与旧测试契约收敛。

## 2026-09-15：1.17 mastery / learning API、工具、事件与恢复接线（已完成）

- `deeptutor/api/routers/mastery_path.py` 的 learning 路由已统一经 `get_learning_runtime()` 和 typed PG unit 执行，路由依赖在业务执行前进行 PG provider/identity 授权检查；缺 provider 或 PG 配置缺失返回受控 `503`，撤权返回 `403`，不再因为旧构造器或隐式 SQLite fallback 进入 `500` 或模型/后台副作用。
- mastery/learning API、事件 hub、WebSocket 断线重放、工具执行、后台恢复、删除/history detach、课程提示/计数与 capability turn authority 均由真实 PG runtime 覆盖：交错回复与过期卡片在模型启动前拒绝；断线分页重放会重新校验身份；受控进程退出/恢复保留 pending question 且不重跑旧交互；删除保留学习历史、拒绝 active/跨 owner detach；课程读取和 hint cache 按 owner/path scope 隔离。
- `LearningService` 继续要求显式 PG learning unit：`LearningService()` 无参构造 fail-closed；运行路径扫描未发现 `LearningStore()`、`mastery.sqlite3`、`sqlite3` 或旧 `prepare_mastery*` 构造器，旧 v1/v2 数据迁移不会由运行构造器触发。
- `extensions/enterprise/tests/test_flows.py` 自带确定性 `ScriptedModel/chunk` 测试替身，避免 enterprise WS 回归依赖已删除的旧临时测试模块；这只影响测试夹具，不向生产路径引入 mock。
- 本切片未新增或修改 PostgreSQL schema/default data、OpenFGA model/tuples 或 Keycloak realm/client/claims；无需新增 DB/OpenFGA/Keycloak migration。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH="$PWD:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_learning_runtime.py::test_unconfigured_api_and_service_fail_closed_without_legacy_constructor -q
# RED（修复前）：expected 503, got 500
# GREEN（修复后）：1 passed in 0.27s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_learning_runtime.py::test_real_websocket_pages_reconnects_and_revalidates -q
# 1 passed in 4.41s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_learning_runtime.py tests/persistence/postgres/business/test_learning_sources.py -q
# 30 passed in 71.00s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_learning_leases.py \
  tests/persistence/postgres/business/test_learning_runtime_fix1.py \
  tests/persistence/postgres/business/test_session_deletion.py \
  tests/persistence/postgres/business/test_session_request_snapshot.py -q
# 52 passed in 129.11s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor/api/routers/mastery_path.py extensions/enterprise/tests/test_flows.py
# All checks passed!

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m py_compile \
  deeptutor/api/routers/mastery_path.py extensions/enterprise/tests/test_flows.py
# exit 0

rg -n "LearningStore\\(|get_learning_store|prepare_mastery_v2_root|mastery\\.sqlite3|sqlite3|SQLite|import_legacy|prepare_mastery|legacy constructor|sqlite_store|\\.sqlite" \
  deeptutor/api/routers/mastery_path.py deeptutor/learning/runtime.py deeptutor/learning/navigation.py \
  deeptutor/learning/event_hub.py deeptutor/learning/service.py deeptutor/capabilities/mastery \
  deeptutor/services/session/turns/learning_adapter.py deeptutor/app/container.py \
  deeptutor/app/postgres_runtime.py deeptutor/services/courses_state.py deeptutor/services/mastery_hints.py
# 仅命中 deeptutor/learning/runtime.py 中禁止 SQLite fallback 的说明；无旧运行构造器。
```

边界：1.17 只完成 mastery/learning 当前 API/工具/事件/恢复/课程接线。1.19 仍负责 reading API/SDK/工具与 workspace 恢复；1.20/1.21 仍负责 cron schedule/repository/service/API/CLI/tool 的 PG 持久化与派发语义；1.41–1.44/2.x 仍负责删除旧运行路径、进程级零 SQLite、旧测试契约收敛、安装制品与真实模型验收。


## 2026-09-15：1.19 reading API / SDK-turn / tools / store PG 接线（已完成）

- `deeptutor/api/routers/reading.py` 的 reading catalog 运行入口改为当前 `ApplicationProviders.reading` PG provider；移除了 API 路由内旧 `_catalog()` / `_ingestion()` 构造。材料列表/详情/单元读取、workspace/tabs/session/link、上传、URL import、retry、notes organize、material delete 均以 PG catalog row 解析 material alias→content_id，并通过 owner `resources` 根读取真实载荷。
- `ReadingStore` 支持 PG material resolver 与 owner `resources` 根；API、工具与 capability 在 PG provider 存在时不打开 `_catalog.sqlite3`，可读取别名材料的 manifest/unit/annotations/outline。`OwnerResourceProvider` 增加 `reading` 资源 kind，用于本 slice 的真实文件载荷目录。
- `deeptutor/capabilities/reading/tools.py` 的 list/switch/read/search/goto/annotate 等工具经 PG catalog/store resolver 读取 workspace 和材料；保留的 legacy fallback 仅服务旧无 PG 单元夹具，1.41 仍需统一删除默认 SQLite fallback。
- `deeptutor/capabilities/reading/capability.py` 的 system prompt facts、workspace facts 与 locate pre-pass 在 PG provider 下读取 PG alias 与资源载荷，避免 SDK/turn runtime 中打开旧 `_catalog.sqlite3` 后把已迁材料误报为 missing。
- 新增真实 PG 覆盖：材料 unit API 不读 `_catalog.sqlite3`、workspace tab 保存/删除/重开、材料列表/duplicate/delete 投影 PG alias 与载荷 facts、reading session 路由、reading tools、上传、URL import、retry、notes organize、capability prompt/locate。测试通过时 monkeypatch legacy catalog/store 的 `sqlite3.connect`，若任一路径打开 `_catalog.sqlite3` 会失败。
- 轻量页面层验证执行现有 reading toolbar spec；完整安装制品页面/API/WS smoke、进程级零 SQLite、旧 no-PG 测试契约收敛仍属于 1.43/1.44/2.4。
- 本切片未新增或修改 PostgreSQL schema/default data、OpenFGA model/tuples 或 Keycloak realm/client/claims；无需新增 DB/OpenFGA/Keycloak migration。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_reading_runtime.py::test_upload_material_route_registers_pg_catalog_without_sqlite_catalog \
  tests/persistence/postgres/business/test_reading_runtime.py::test_import_url_route_queues_pg_workspace_without_sqlite_catalog \
  tests/persistence/postgres/business/test_reading_runtime.py::test_organize_reading_notes_uses_pg_workspace_and_resource_annotations \
  tests/persistence/postgres/business/test_reading_runtime.py::test_reading_capability_uses_pg_alias_for_prompt_and_locate_without_sqlite_catalog -q
# RED（修复前）：4 failed；上传/URL import/notes/capability 均因旧 catalog 或 alias 缺失失败
# GREEN（修复后）：4 passed, 1 warning in 10.60s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_reading_runtime.py tests/reading/test_workspace_tools.py -q
# 12 passed, 1 warning in 25.19s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_reading_catalog.py \
  tests/persistence/postgres/business/test_reading_isolation.py \
  tests/persistence/postgres/business/test_reading_composition.py -q
# 31 passed in 77.00s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor/api/routers/reading.py deeptutor/capabilities/reading/capability.py \
  deeptutor/capabilities/reading/tools.py deeptutor/reading/store.py \
  deeptutor/persistence/resources.py tests/persistence/postgres/business/test_reading_runtime.py
# All checks passed!

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m py_compile \
  deeptutor/api/routers/reading.py deeptutor/capabilities/reading/capability.py \
  deeptutor/capabilities/reading/tools.py deeptutor/reading/store.py \
  deeptutor/persistence/resources.py tests/persistence/postgres/business/test_reading_runtime.py
# exit 0

cd web && npm run test:unit -- tests/reading-toolbar-selection.spec.tsx
# Test Files 1 passed; Tests 1 passed
```

补充探测：`tests/reading/test_capability.py` 仍按旧无 PG / local PathService fixture 直接构造 `ReadingStore()`，在当前 PG-only 方向下报 `authenticated owner required`（1 failed / 27 errors / 29 passed）。该结果未用于否定 1.19 的 PG runtime 验收，保留给 1.44 统一收敛旧 local 测试契约；本切片不扩大 legacy fallback。

边界：1.19 完成 reading 当前 API/SDK-turn/capability/tools 与真实资源载荷读取接线。`reading/store.py`、reading tools 与 capability 中为旧夹具保留的 `_catalog.sqlite3` fallback 仍待 1.41–1.43 删除/进程级门禁验证；cron、Partners/Matrix、MarginNote、Memory、离线导入、容量、安装制品和真实模型验收仍按后续任务推进。

## 2026-09-15：1.20 PG cron schedule/meta/execution repository（已完成）

- 新增 `0008_cron.sql` 与 `cron_catalog.json`，在同一 `enterprise` schema / `schema_history` 下追加 `cron_meta`、`cron_jobs`、`cron_executions`。三张表均按可信 `tenant_id`/`owner_id` 启用并 FORCE RLS；运行角色仅获 SELECT/INSERT/UPDATE/DELETE，迁移继续由现有 runner 管理，无第二套 migration history。
- `cron_jobs` 结构化保存 at/every/cron 三类 schedule、cron timezone、enabled/delete_after_run、next/last run、状态 payload 与版本；`cron_meta` 保存 owner-scoped revision；`cron_executions` 保存领取 worker、scheduled run、claim revision、终态/错误/耗时与原 payload，用于后续 service/executor 接线。
- 新增 `deeptutor.persistence.postgres.cron`：`PostgresCronRepository` 保持现有 `CronRepository` list/upsert/delete/delete_owner/revision 语义，同时新增 `claim_due()`、`complete_execution()` 和 `list_executions()`；`AsyncPostgresCronRepository.run()` 以有界 `SyncDatabase.run()` 包装完整事务，避免在 event loop 中阻塞或跨线程泄漏 scope。
- 领取语义：仅 `enabled` 且 `next_run_at_ms <= now` 的当前 owner 任务可被 `FOR UPDATE SKIP LOCKED` 原子领取；领取后 job `next_run_at_ms` 置空并写入 execution claim，重复领取返回空。完成时以 `CronExecutionClaim.job_revision` CAS 验证当前执行权；重复同终态完成幂等，不同终态/过期版本拒绝。
- 完成语义：成功/失败/跳过会写回 last/run_history 并按 schedule 计算下次运行；at/`delete_after_run` 完成后删除 job；`uncertain` 保留 job 但不重排 next_run，避免在外部副作用不确定时盲目重发。owner 隔离由 DB RLS 与 repository 查询同时覆盖。
- 本切片需要并已新增 PostgreSQL schema migration；不涉及 OpenFGA model/tuple、Keycloak realm/client/claims，也未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_cron_repository.py -q
# RED（实现前）：3 failed，缺少 deeptutor.persistence.postgres.cron
# GREEN（实现后及边界补充）：4 passed in 10.61s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/business/test_cron_repository.py -q
# 19 passed in 13.10s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/test_reading_migration.py \
  tests/persistence/postgres/test_session_resource_migration.py \
  tests/persistence/postgres/business/test_cron_repository.py -q
# 59 passed in 18.03s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/services/cron/test_cron_service.py tests/services/cron/test_cron_tool.py -q
# 29 passed in 0.38s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/cron.py deeptutor/persistence/postgres/migrations/runner.py \
  tests/persistence/postgres/business/test_cron_repository.py \
  tests/persistence/postgres/test_migrations.py tests/persistence/postgres/test_account_migration.py
# All checks passed!

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/cron.py deeptutor/persistence/postgres/migrations/runner.py \
  tests/persistence/postgres/business/test_cron_repository.py \
  tests/persistence/postgres/test_migrations.py tests/persistence/postgres/test_account_migration.py
# exit 0
```

边界：1.20 只完成 cron 的 PG schema、catalog 校验与 repository/claim/complete 语义。`get_cron_service()`、API/CLI/tool/后台调度仍在 1.21 接通；现有 `SQLiteCronRepository` 和 `jobs.json→SQLite` 初始化仍保留给旧 cron 单元测试/待替换运行路径，不作为最终 PG-only 完成状态。

## 2026-09-15：1.21 cron service / executor / tool / 后台 PG 接线（已完成）

- 新增 `PostgresCronService`，默认 `get_cron_service()` 改为从已启动的 `DefaultPostgresRuntime.sync_db`、tenant 与 worker_id 装配 PG cron；若没有 PG runtime，默认 accessor 明确失败且不创建 `jobs.json` / `jobs.sqlite3`。旧 `CronService(store_path=...)` 与 `SQLiteCronRepository` 仅保留为显式 legacy 单元测试/离线兼容构造。
- cron tool 增加异步执行路径 `run_cron_action_async()`；内置 `CronTool.execute()` 会 await PG service。保留旧同步 `run_cron_action()` 以覆盖 legacy SQLite 单测。tool action 增加 `pause` / `resume`，`cancel` 继续删除任务。
- 后台 leader/API/CLI 仍调用 `await get_cron_service().start()/stop()`；PG service 在 tick 中按 tenant 内 users 逐个建立受限 `TenantScope`，用 1.20 的 `claim_due()` / `complete_execution()` 原子领取和完成，不绕过 RLS、不扫描本地 cron 目录。
- `CronOwner` 增加 `tenant_id`，pipeline 在 chat turn 中注入 PG tenant 与 `tenant_admin` 状态；chat executor 若看到 `tenant_id` 会恢复 PG `CurrentUser(UserScope(kind="tenant", ...))`，再通过默认 PG session provider 写回目标会话，避免旧 local `scope_for_user`。
- 派发竞争/重启/不确定结果语义：claim 会先将 `next_run_at_ms` 置空并写 execution；重复 tick 不会重复派发同一 claim。`ok/error/skipped` 按 schedule 重排或删除；`uncertain` 保留 job 且不重排，后续 tick 不盲目重发。若完成持久化失败，claim 仍保持待核对而不是重新派发。
- partner destroy 的 `remove_owner_jobs()` 调用改为兼容 PG async service，避免未 awaited coroutine；跨 owner 删除通过逐用户受限 scope 清除同一 `owner_key`。
- 本切片未新增 PostgreSQL schema（复用 1.20 的 0008），未改变 OpenFGA/Keycloak。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_cron_runtime.py -q
# RED（实现前）：ImportError，缺少 run_cron_action_async / PG service
# GREEN：2 passed in 5.76s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_cron_repository.py \
  tests/persistence/postgres/business/test_cron_runtime.py \
  tests/services/cron/test_cron_service.py tests/services/cron/test_cron_tool.py -q
# 36 passed in 15.64s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/services/cron/test_cron_service.py tests/services/cron/test_cron_tool.py \
  tests/persistence/postgres/business/test_cron_runtime.py -q
# 33 passed in 5.96s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/api/test_default_pg_book_course_consumers.py::test_cron_chat_executor_appends_to_pg_session_without_sqlite_fallback -q
# 1 passed, 2 warnings in 1.84s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/test_reading_migration.py tests/persistence/postgres/test_session_resource_migration.py \
  tests/persistence/postgres/business/test_cron_repository.py \
  tests/persistence/postgres/business/test_cron_runtime.py \
  tests/services/cron/test_cron_service.py tests/services/cron/test_cron_tool.py \
  tests/api/test_default_pg_book_course_consumers.py::test_cron_chat_executor_appends_to_pg_session_without_sqlite_fallback -q
# 93 passed, 2 warnings in 24.86s

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m ruff check \
  deeptutor/services/partners/manager.py deeptutor/services/cron/service.py \
  deeptutor/services/cron/postgres.py deeptutor/services/cron/executor.py \
  deeptutor/tools/cron_tool.py deeptutor/tools/builtin/__init__.py \
  deeptutor/agents/loop/pipeline.py deeptutor/persistence/postgres/cron.py \
  tests/persistence/postgres/business/test_cron_runtime.py \
  tests/services/cron/test_cron_service.py tests/services/cron/test_cron_tool.py
# All checks passed!

PYTHONPATH="$PWD:$PWD/extensions/enterprise/src:$PWD/extensions/enterprise/tests:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m py_compile \
  deeptutor/services/partners/manager.py deeptutor/services/cron/service.py \
  deeptutor/services/cron/postgres.py deeptutor/services/cron/executor.py \
  deeptutor/tools/cron_tool.py deeptutor/tools/builtin/__init__.py \
  deeptutor/agents/loop/pipeline.py deeptutor/persistence/postgres/cron.py \
  tests/persistence/postgres/business/test_cron_runtime.py \
  tests/services/cron/test_cron_service.py tests/services/cron/test_cron_tool.py
# exit 0
```

边界：1.21 完成 cron 默认运行接线与当前 PG 后台派发语义；Partners runtime status 自身仍在 1.22，Matrix、MarginNote、Memory、离线导入、进程级零 SQLite、安装制品和真实模型验收继续按后续任务推进。

## 2026-09-15：1.22 Partners runtime status PG 投影与 worker/TTL 栅栏（已完成）

- 新增 `0009_partner_runtime_status.sql` 与 `partner_runtime_status_catalog.json`，在 `enterprise.partner_runtime_status` 显式保存 `tenant_id`、`owner_id`、`partner_id`、`worker_id`、`version`、`updated_at_ms`、`expires_at_ms`、`ttl_ms`、运行状态与脱敏 payload；表启用 FORCE RLS，tenant + owner 限制读取/写入，并 FK 到 `enterprise.users`。
- 新增 `PostgresPartnerRuntimeStatusRepository`：leader 写入时按当前 worker 单调递增 version；reader 从同一 PG 投影读取；payload 移除 `channels`，返回兼容 `runtime_owner_id`（旧字段语义仍为 worker）以及新的 `runtime_worker_id` / `runtime_version` / `runtime_expires_at` / `runtime_expired`。
- TTL 语义：非过期状态只能由当前 worker 更新；不同 worker 在 TTL 内写入会收到 `PartnerRuntimeStatusConflict`。TTL 过后 reader 返回明确 `runtime_state=expired`、`running=false`，新 worker 可重建投影并递增 version；旧 worker 随后在新 TTL 内继续被拒绝。
- 默认 `get_partner_runtime_status_repository()` 改为从已装配的 `DefaultPostgresRuntime.sync_db`、deployment tenant 与 `ApplicationContainer.worker_id` 创建 PG repository；默认路径不再创建/打开 `data/.../_runtime/status.sqlite3`。显式 `PartnerRuntimeStatusRepository(path)` 仅保留给 legacy fixture/离线旧格式测试。
- `PartnerManager._publish_runtime_status()` 改为写入可信 partner owner（`PartnerConfig.owner_id`）并单独传入 worker；列表/详情合并新的 runtime 字段，销毁 partner 时按 owner 删除 PG 投影。多 worker API 轮询仍使用该共享 PG 投影等待 leader 写入状态。
- 本切片需要并已新增 PostgreSQL schema migration；不涉及 OpenFGA model/tuple、Keycloak realm/client/claims，也未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
.venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_partner_runtime_status.py -q
# RED（实现前）：ModuleNotFoundError，缺少 deeptutor.persistence.postgres.partner_runtime_status
# GREEN：3 passed in 8.14s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/business/test_partner_runtime_status.py -q
# 18 passed in 9.77s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/partner_runtime_status.py \
  deeptutor/persistence/postgres/migrations/runner.py \
  deeptutor/services/partners/runtime_status.py \
  deeptutor/services/partners/manager.py \
  deeptutor/api/routers/partners.py \
  tests/persistence/postgres/business/test_partner_runtime_status.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/partner_runtime_status.py \
  deeptutor/persistence/postgres/migrations/runner.py \
  deeptutor/services/partners/runtime_status.py \
  deeptutor/services/partners/manager.py \
  deeptutor/api/routers/partners.py \
  tests/persistence/postgres/business/test_partner_runtime_status.py
# exit 0
```

边界：1.22 完成 Partners runtime status 的 PG schema、repository 与默认 runtime/manager/API 状态投影接线；Partner config 本体仍沿既有文件配置路径，Matrix、MarginNote、Memory、离线导入和进程级零 SQLite 继续按后续任务推进。

## 2026-09-15：1.23 Matrix nio / E2EE 存储协议锁定（已完成）

- 将 Matrix 依赖从宽范围冻结为 `matrix-nio==0.26.0`；E2EE extra 固定为 `matrix-nio[e2e]==0.26.0` + `vodozemac==0.10.0`。本地探针确认 `matrix-nio 0.26.0` 走 vodozemac E2EE 栈，`python-olm` / `olm` Python 模块未安装，Homebrew `libolm` 不在当前实际运行栈内。
- 新增 `matrix-storage-protocol.md`，记录 `AsyncClient` / `AsyncClientConfig` / `DefaultStore` / `MatrixStore` 的实际构造与加载边界：当前 `MatrixChannel.start()` 在主事件循环创建 `AsyncClient`，以 `store_path` 加载 nio store，`sync_forever` 为异步协程；1.25 必须引入 Matrix 专属 worker 和提交后游标，不得在主 loop 吞掉 PG store 错误。
- 对完整 store 协议做了契约测试，不只覆盖 `next_batch`：账户、Olm sessions、Megolm inbound sessions、转发链、设备 keys、设备信任状态、加密房间、同步 token、outgoing key requests 均登记字段与方法面，并把 pickle key / account/session/group-session ciphertext 作为后续 1.24 Secret 加密边界。
- 1.23 不冻结 PG schema、不宣称 PG adapter 可行，仅为 1.24–1.26/1.36 的硬前置输入；现有 Matrix 运行路径仍会使用 nio 默认 SQLite store，必须在 1.24–1.25 替换。未新增 PostgreSQL schema，未改变 OpenFGA/Keycloak，未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/test_matrix_requirements.py tests/services/partners/test_matrix_protocol_contract.py -q
# RED（实现/冻结前）：3 failed，依赖仍为 matrix-nio>=0.25.2,<1.0.0，且探针未按 MatrixChannel 方式绑定 user_id/device_id
# GREEN：6 passed in 0.17s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/test_matrix_requirements.py tests/scripts/test_install_extras.py \
  tests/services/partners/test_matrix_protocol_contract.py -q
# 22 passed in 0.18s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  tests/test_matrix_requirements.py tests/scripts/test_install_extras.py \
  tests/services/partners/test_matrix_protocol_contract.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  tests/test_matrix_requirements.py tests/scripts/test_install_extras.py \
  tests/services/partners/test_matrix_protocol_contract.py
# exit 0
```

边界：1.23 只完成实际 nio/vodozemac 版本锁定、store 协议/线程模型探针与文档化。Matrix PG schema/store adapter、Secret 加密、设备归属、专属 worker、真实 Matrix/E2EE 服务验收和旧 store 离线迁移仍分别在 1.24–1.26/1.36 继续推进。

## 2026-09-15：1.24 Matrix PG schema / store adapter / Secret envelope（已完成）

- 新增 `0010_matrix_store.sql` 与 `matrix_store_catalog.json`，覆盖 nio 0.26 store protocol v2 的账户、Olm session、Megolm inbound session、forwarding chain、设备 keys、设备 trust、加密房间、sync token 与 outgoing key request。所有表均包含 `tenant_id` / `owner_id` / `partner_id` / `matrix_user_id` / `device_id` 归属键，启用 FORCE RLS，并通过组合 PK/FK 将设备与 Partner/Matrix account 绑定。
- 新增 `deeptutor.persistence.postgres.matrix.PostgresMatrixStore` 与 `postgres_matrix_store_factory()`。adapter 实现 nio 同步 store 方法，不创建 peewee/SQLite database、不暴露 `database_path`，后续 1.25 可作为 `AsyncClientConfig.store` 的 callable 注入专属 Matrix worker。
- Secret 边界：nio/vodozemac 的 account/session 先按 Secret 管理的 `pickle_key` pickle，再由 DeepTutor envelope（`secret_id`、`secret_version`、AES-GCM nonce/ciphertext）加密入 PG；空值/`DEFAULT_KEY` pickle key 与缺失 envelope secret 会直接拒绝。错误 envelope secret/version 报 sanitized decrypt error；正确 envelope 但错误 pickle key 报 sanitized pickle error。
- 测试覆盖完整协议面：account、Olm session、Megolm session + forwarding chain、device keys、trust verify/unverify/blacklist/ignore、encrypted rooms、sync token、outgoing key request；并验证跨 owner / 跨 device 不可见和密文字段不同于 nio pickle 明文。
- 本切片需要并已新增 PostgreSQL schema migration；不涉及 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。MatrixChannel 的运行接线、专属 worker、提交后游标与 PG 故障停止同步仍在 1.25；真实 Matrix/E2EE 服务验收仍在 1.26。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_matrix_store.py -q
# RED（实现前）：3 failed，缺少 deeptutor.persistence.postgres.matrix
# GREEN：3 passed in 8.18s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/business/test_matrix_store.py -q
# 18 passed in 10.02s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/matrix.py \
  deeptutor/persistence/postgres/migrations/runner.py \
  tests/persistence/postgres/business/test_matrix_store.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/matrix.py \
  deeptutor/persistence/postgres/migrations/runner.py \
  tests/persistence/postgres/business/test_matrix_store.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# exit 0
```

边界：1.24 完成 Matrix PG schema 与 adapter 的冻结和本地真实 PG 验证；它尚未替换 `MatrixChannel.start()` 的 default nio SQLite store，也未证明真实 Matrix homeserver / E2EE 端到端收发，这些继续按 1.25–1.26 推进。

## 2026-09-15：1.25 Matrix 专属 worker / PG store runtime 接线（已完成）

- `MatrixChannel.start()` 改为启动专属 daemon thread + asyncio loop，并在该 worker loop 内创建 `AsyncClient`、加载 store 和运行 `sync_forever()`；主应用 loop 只负责调度启动/停止与 outbound proxy，不再承载 nio 同步循环或同步 PG store 调用。
- Matrix client 配置接入 1.24 的 `postgres_matrix_store_factory()`，强制 `store_sync_tokens=True` 且 `encryption_enabled=True`，以确保 nio 0.26 `load_store()` 实际构造 PG store；空/default pickle key、缺 envelope Secret、缺 PG runtime、缺 Partner owner/device 均先失败。
- `ChannelManager` 将 `PartnerConfig.owner_id` 作为可信 owner 传入 channel；Matrix store scope 由应用 PG runtime tenant + Partner owner 构造，`partner_id` / Matrix user/device 进入 1.24 组合归属键，不再从 channel state 目录派生。
- inbound 事件从 worker loop 通过 `run_coroutine_threadsafe()` 投递到 runtime/main loop 的 `MessageBus`，并等待投递完成后才让 nio 继续保存 sync token；测试用 fake nio client 验证了 message handoff 完成后才保存 `cursor-after-callback`。
- PG/store/sync 异常 fail-closed：`_sync_loop()` 不再 catch-all sleep 重试；异常会使 channel `_running=False` 并发布 `setup_state=error`，避免在 PG 故障时吞错、重复同步或盲目推进游标。`stop()` 会在 worker loop 内取消/关闭 sync 和 client，并 join worker。
- 本切片未新增 PostgreSQL schema（复用 1.24 的 0010），未改变 OpenFGA/Keycloak。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。真实 Matrix homeserver 普通/E2EE 收发、重启、设备信任和旧消息解密仍在 1.26。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_matrix_runtime.py -q
# RED（实现前）：2 failed，client.config.encryption_enabled 为 False / sync 未进入专属 worker；依赖缺失先通过安装声明依赖和 importorskip 处理
# GREEN：2 passed in 5.88s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/test_matrix_requirements.py tests/scripts/test_install_extras.py \
  tests/services/partners/test_matrix_protocol_contract.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/business/test_matrix_store.py \
  tests/persistence/postgres/business/test_matrix_runtime.py -q
# 42 passed in 15.13s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/partners/channels/matrix.py \
  deeptutor/partners/channels/manager.py \
  deeptutor/services/partners/manager.py \
  tests/persistence/postgres/business/test_matrix_runtime.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/partners/channels/matrix.py \
  deeptutor/partners/channels/manager.py \
  deeptutor/services/partners/manager.py \
  tests/persistence/postgres/business/test_matrix_runtime.py
# exit 0
```

已知非本切片回归现状：额外尝试运行 `tests/services/partners/test_channel_manager.py` 与 `tests/services/partners/test_channel_secrets.py` 时，出现本地未安装 Slack/Telegram 可选 SDK 的 registry 断言，以及 1.22 后 legacy Partner runtime status 测试未提供 owner/PG 的新契约失败；这些不作为 1.25 完成依据，后续按 1.44 统一迁移旧 local 无 PG 预期。

## 2026-09-15：1.26 受控 Matrix homeserver 普通/E2EE 端到端验收（已完成）

- 新增 `tests/persistence/postgres/business/test_matrix_controlled_service.py`，在显式 `DT_MATRIX_CONTROLLED_SERVICE=1` 下启动隔离 Docker Synapse（默认 `ghcr.io/element-hq/synapse:v1.160.0`），使用临时 homeserver 与合成 `bot` / `alice` 账号，不连接用户 Matrix 服务或用户数据。
- 普通 Matrix 路径：`MatrixChannel` 使用 1.24/1.25 的 `PostgresMatrixStore` 和专属 worker 接入真实 Synapse；Alice → bot 收到 `plain-one`，重启同一 channel/同一设备/同一 PG store 后旧消息未重放，再收到 `plain-two`，并验证 bot → Alice 的 `bot-plain-reply` 可由真实客户端读取。
- E2EE 路径：bot/alice 均使用真实 nio 0.26 + vodozemac + DeepTutor PG Matrix store 创建加密房间；同步并持久化设备 key/trust，将 Alice `ALICEE2E` 设备 trust 保存为 `verified`；验证 bot → Alice 的 `encrypted-one` 与 Alice → bot 的 `encrypted-two` 均可解密收发。
- 重启/旧消息解密：关闭 Alice E2EE 客户端后，以同一 Matrix device、同一 PG store、同一 pickle/envelope Secret 重新加载 store，通过 Synapse历史接口解密旧 `encrypted-one`；未通过新设备重配或关闭 E2EE 规避验收。
- SQLite 禁用边界：DeepTutor 侧所有 raw nio 客户端与 `MatrixChannel` 均断言 store 没有 `database_path`，使用 PG-backed store；Synapse 容器自身的内部状态属于外部受控测试服务，不是 DeepTutor runtime store。
- 本切片未新增 PostgreSQL schema（复用 1.24 的 0010），未改变 OpenFGA/Keycloak。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
DT_MATRIX_CONTROLLED_SERVICE=1 PYTHONPATH=.:extensions/enterprise/src \
  .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_matrix_controlled_service.py -q -s
# RED/调试阶段：依次暴露并修复 plain room 本地 cache 未同步、E2EE keys_query 无待查询、未验证多设备、timeline 读取错误、重启客户端缺 user_id/device/token 等集成问题
# GREEN：1 passed in 12.20s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/test_matrix_requirements.py tests/scripts/test_install_extras.py \
  tests/services/partners/test_matrix_protocol_contract.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/business/test_matrix_store.py \
  tests/persistence/postgres/business/test_matrix_runtime.py -q
# 42 passed in 15.37s

DT_MATRIX_CONTROLLED_SERVICE=1 PYTHONPATH=.:extensions/enterprise/src \
  .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_matrix_controlled_service.py -q
# 1 passed in 14.12s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/matrix.py \
  deeptutor/partners/channels/matrix.py \
  deeptutor/partners/channels/manager.py \
  deeptutor/services/partners/manager.py \
  tests/persistence/postgres/business/test_matrix_store.py \
  tests/persistence/postgres/business/test_matrix_runtime.py \
  tests/persistence/postgres/business/test_matrix_controlled_service.py \
  tests/test_matrix_requirements.py tests/scripts/test_install_extras.py \
  tests/services/partners/test_matrix_protocol_contract.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/matrix.py \
  deeptutor/partners/channels/matrix.py \
  deeptutor/partners/channels/manager.py \
  deeptutor/services/partners/manager.py \
  tests/persistence/postgres/business/test_matrix_store.py \
  tests/persistence/postgres/business/test_matrix_runtime.py \
  tests/persistence/postgres/business/test_matrix_controlled_service.py
# exit 0
```

边界：1.26 完成 Matrix 普通/E2EE 在受控 homeserver 上的真实 PG store 验收；Matrix 旧 nio SQLite store 的离线导入/Secret 映射仍在 1.36，进程级零 SQLite 总门禁仍在 1.43。下一步按任务清单进入 MarginNote schema/store（1.27）。

## 2026-09-15：1.27 MarginNote PG schema / Store（已完成）

- 新增 `0011_marginnote_store.sql` 与 `marginnote_store_catalog.json`，在 `enterprise` schema 下保存 `marginnote_devices`、`marginnote_cursors`、`marginnote_objects`、`marginnote_tombstones`。所有表均包含 `tenant_id` / `owner_id` / `kb_id` / `device_id` 复合归属键，启用 FORCE RLS，并向受限运行角色授予最小 DML。
- schema 约束覆盖设备 token hash、KB/device/object 非空、对象类型枚举、JSONB tags/links/raw 形态、page 范围、设备 FK 级联与 tombstone 主键；objects/cursors/tombstones 均 FK 到同一 owner+KB+device，避免 `db_path` 或 header 字符串成为授权边界。
- 新增 `PostgresMarginNoteStore`，复用 `SyncDatabase.transaction(TenantScope)`，实现 pairing、token verification、revoke/list/touch、batch ingest、cursor、get/search/list/documents/links/tags/count。Store 不提供 `db_path` / SQLite 连接，不从文件路径派生归属。
- 批次 ingest 在一个 PG 事务内 upsert objects、写 tombstone、删除 active object 并推进 cursor；约束失败时测试验证已写对象和 cursor 一并回滚。重复 object_id 在不同 device 维度下保留独立行，未配对 device 写入被 FK 拒绝。
- 迁移 runner 追加 0011 catalog 并保持 0001–0011 连续历史；本切片新增 PostgreSQL schema migration，不涉及 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_marginnote_store.py -q
# RED（实现前）：ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.marginnote'
# GREEN：3 passed, 3 warnings in 8.13s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/business/test_marginnote_store.py -q
# 18 passed, 3 warnings in 10.12s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/marginnote.py \
  deeptutor/persistence/postgres/migrations/runner.py \
  tests/persistence/postgres/business/test_marginnote_store.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/marginnote.py \
  deeptutor/persistence/postgres/migrations/runner.py \
  tests/persistence/postgres/business/test_marginnote_store.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# exit 0

openspec validate migrate-all-sqlite-state-to-postgresql --strict
# Change 'migrate-all-sqlite-state-to-postgresql' is valid

git diff --check
# exit 0
```

边界：1.27 只完成 MarginNote PG schema 与领域 Store。HTTP pairing/sync/search、知识库/capability/tool 接线、运行路径 `db_path` 退出和入口级负例继续在 1.28 推进；旧 MarginNote SQLite 离线导入策略仍在 1.35。

## 2026-09-15：1.28 MarginNote API / 知识库 / capability 接线（已完成）

- `deeptutor/api/routers/marginnote4.py` 改为 PostgreSQL-only runtime：session 端 `/pair`、`/devices`、`/status` 使用当前 PG owner 的 `PostgresMarginNoteStore`，设备端 `/sync`、`/heartbeat` 通过 `Authorization: MarginNote <device_id>:<token>` 解析 owner scope 并复验 token；缺 PG runtime 明确 503，不再构造全局 SQLite store。
- `PostgresMarginNoteStore` 增加 owner 编码 device id 与 stale cursor 检测；同设备批次在事务内锁定 cursor，旧 cursor 返回 409，失败批次保留对象/cursor 原状，重复/跨 KB 同 ID 由 tenant+owner+KB+device 复合键隔离。
- `DefaultPostgresRuntime` 暴露 `marginnote_store_for_current_user()` / `marginnote_store_for_scope()`，capability binding 改为只注入 `_mn4_kb_id` / `_marginnote_name` 并剥离 `_db_path`；MarginNote tools 通过 PG runtime 或测试注入 store 查询，不接受模型传入的运行时数据库路径。
- `KnowledgeBaseManager.register_marginnote4_kb()` 不再解析默认 SQLite 路径；显式 `db_path` 仅作为旧源/import metadata 保留。删除 connected MN4 KB 只移除 pointer，不 unlink legacy source path；旧 `db_path` 不能成为授权或数据删除边界。
- 新增 `tests/persistence/postgres/business/test_marginnote_runtime.py` 覆盖真实 PG HTTP pairing/sync/cursor/revoke/跨 KB，同步验证 capability/tools 在包含 forged legacy `db_path` metadata 时仍只读 PG store。旧 API/knowledge/tool 单测同步更新为 PG-only 契约和无 SQLite 文件副作用。
- 本切片未新增 PostgreSQL schema（复用 1.27 的 0011），未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_marginnote_runtime.py -q
# RED（实现前）：旧 router/capability 仍调用 resolve_db_path / SQLite store
# GREEN：2 passed in 5.85s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/capabilities/marginnote4/test_capability.py \
  tests/capabilities/marginnote4/test_tools.py \
  tests/api/test_marginnote4_router.py \
  tests/knowledge/test_marginnote4_kb.py \
  tests/persistence/postgres/business/test_marginnote_store.py \
  tests/persistence/postgres/business/test_marginnote_runtime.py -q
# 46 passed, 4 warnings in 13.97s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/business/test_marginnote_store.py \
  tests/persistence/postgres/business/test_marginnote_runtime.py -q
# 20 passed, 3 warnings in 15.38s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/marginnote.py \
  deeptutor/api/routers/marginnote4.py \
  deeptutor/app/postgres_runtime.py \
  deeptutor/capabilities/marginnote4/binding.py \
  deeptutor/capabilities/marginnote4/capability.py \
  deeptutor/capabilities/marginnote4/tools.py \
  deeptutor/knowledge/manager.py \
  tests/persistence/postgres/business/test_marginnote_store.py \
  tests/persistence/postgres/business/test_marginnote_runtime.py \
  tests/capabilities/marginnote4/test_capability.py \
  tests/capabilities/marginnote4/test_tools.py \
  tests/api/test_marginnote4_router.py \
  tests/knowledge/test_marginnote4_kb.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/marginnote.py \
  deeptutor/persistence/postgres/migrations/runner.py \
  deeptutor/api/routers/marginnote4.py \
  deeptutor/app/postgres_runtime.py \
  deeptutor/capabilities/marginnote4/binding.py \
  deeptutor/capabilities/marginnote4/capability.py \
  deeptutor/capabilities/marginnote4/tools.py \
  deeptutor/knowledge/manager.py \
  tests/persistence/postgres/business/test_marginnote_store.py \
  tests/persistence/postgres/business/test_marginnote_runtime.py \
  tests/capabilities/marginnote4/test_capability.py \
  tests/capabilities/marginnote4/test_tools.py \
  tests/api/test_marginnote4_router.py \
  tests/knowledge/test_marginnote4_kb.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# exit 0
```

边界：1.28 完成 MarginNote 运行时 PG-only 接线与入口验证；旧 MarginNote SQLite 数据的离线导入/可重建投影策略继续在 1.35，进程级零 SQLite 总门禁继续在 1.43。

## 2026-09-15：1.29 Memory chat/quiz snapshot 与 probe 改用 PG（已完成）

- `deeptutor/services/memory/snapshot/adapters.py` 的 `read_chat_entities()`、`probe_chat_entities()`、`read_quiz_entities()` 改为从当前应用容器的 PostgreSQL runtime 取得 `sync_db + TenantScope` 后查询 `enterprise.sessions`、`enterprise.messages` 与 `enterprise.notebook_entries`；不再调用 `get_chat_history_db()`、`sqlite3.connect(...mode=ro...)` 或本地文件时间戳。
- Chat full read 和 probe 共享同一 PG session 分页顺序（`updated_at DESC, id DESC`）与同一 last-message 排序（`created_at DESC, id DESC`），保持 probe/full 的 identity+fingerprint 一致；空 session 仍以 `0` 参与 fingerprint。
- Quiz snapshot 改用 PG notebook rows，带当前 owner scope、已删除/正在删除 session 过滤、稳定 keyset 分页（`created_at DESC, id DESC`），并保留 entry id、question/answer/correct/explanation、bookmarked/is_correct 等 metadata。
- 后台 snapshot/增量消费者仍通过 `read_entities()` / `read_stamps()` 调用同一 adapter，因此自动改用 PG；probe 异常仍 fallback 到 full read，不把临时探针错误误判为全量删除。
- 新增 `tests/persistence/postgres/business/test_memory_snapshot_runtime.py`：用真实 PG session/notebook store 写入当前 owner 与另一 owner 数据，禁止 `get_path_service()` 访问旧 SQLite 路径，验证 chat full/probe、quiz snapshot、跨 owner 不可见、分页 page size=1 不漏读、删除题库 entry 后 snapshot 消失。
- 旧 `tests/services/memory/test_snapshot_probes.py` 取消运行态 SQLite chat DB fixture；`tests/persistence/legacy_baseline/test_representative_formats.py` 只保留旧 SQLite schema/order 作为离线导入基线，不再调用 live adapter。
- 本切片未新增 PostgreSQL schema（复用 session/notebook 既有迁移），未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_memory_snapshot_runtime.py -q
# RED（实现前）：AttributeError: adapters 没有 _PG_SNAPSHOT_PAGE_SIZE；旧实现仍是 SQLite 文件路径读取
# GREEN：1 passed in 3.32s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_memory_snapshot_runtime.py \
  tests/services/memory/test_snapshot_probes.py \
  tests/services/memory/test_snapshot_adapters.py \
  tests/persistence/legacy_baseline/test_representative_formats.py -q
# 18 passed in 3.34s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/services/memory/test_snapshot_probes.py \
  tests/services/memory/test_snapshot_adapters.py \
  tests/services/memory/test_recall.py \
  tests/persistence/postgres/business/test_memory_snapshot_runtime.py \
  tests/persistence/postgres/business/test_notebook_store.py \
  tests/persistence/postgres/business/test_session_composition.py -q
# 51 passed in 50.25s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/services/memory/snapshot/adapters.py \
  tests/persistence/postgres/business/test_memory_snapshot_runtime.py \
  tests/services/memory/test_snapshot_probes.py \
  tests/services/memory/test_snapshot_adapters.py \
  tests/persistence/legacy_baseline/test_representative_formats.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/services/memory/snapshot/adapters.py \
  tests/persistence/postgres/business/test_memory_snapshot_runtime.py \
  tests/services/memory/test_snapshot_probes.py \
  tests/services/memory/test_snapshot_adapters.py \
  tests/persistence/legacy_baseline/test_representative_formats.py
# exit 0

grep -n "sqlite3\\|get_chat_history_db\\|mode=ro" \
  deeptutor/services/memory/snapshot/adapters.py || true
# no output
```

边界：1.29 只迁移 Memory snapshot/probe 的 chat/quiz 只读入口；其它仍由文件/JSON 承载且不属于本项的 surfaces（notebook/cowriter/book/kb/partner）保持各自既有契约。全进程零 SQLite 门禁仍在 1.43，完整离线导入/验证仍在 1.30–1.40。

## 2026-09-15：1.30 离线 SQLite 源快照 / manifest / source-check / plan（已完成）

- 新增 `deeptutor.persistence.postgres.offline_import`，将运行态 PG-only 迁移与离线旧源读取隔离：`create_sqlite_source_snapshot()` 使用 SQLite Backup API 从只读源生成独立 snapshot 制品，并写出版本化 manifest；工具不连接业务 PG、不装配默认容器、不调用模型、不触发旧 Store 运行时自动迁移。
- manifest 协议记录 `freeze_id`、停写 writer 清单、operator、target tenant、显式 owner 映射、source id/version/owner、source main/WAL/SHM 前后哈希、snapshot 哈希/大小/schema/table counts/integrity 与 sidecar 状态。源 main DB 与 WAL 哈希在 backup 前后不变，否则拒绝；SHM 仅作为非权威读协调 sidecar 记录前后值，不修复或重建源。
- 新增版本化引用字段注册表 `reference_registry`：固定 `chat_history_sqlite/v1` 的 sessions/messages/turns/turn_events/notebook/category 结构字段与 typed JSON 机器引用路径；同时登记 mastery v1/v2、reading、cron、partners runtime status、MarginNote、Matrix nio 0.26 的版本化引用族，供后续 1.32–1.36 逐域 parser/importer 复用。未知源版本在 source-check/plan 阶段被拒绝。
- `source_check_manifest()` 只读取 manifest 所在目录下的不可变 artifact：拒绝 snapshot 指向活动源库、artifact 路径逃逸、符号链接、哈希/大小不匹配、manifest 声明 required 但缺失 WAL sidecar、snapshot 旁存在非空 `-wal` 依赖、未知版本、缺 owner 映射、SQLite integrity/schema 缺表/缺列或 table count 漂移。
- `plan_sqlite_import()` 在 source-check 通过后以 `mode=ro&immutable=1` 打开 snapshot，输出每 source/owner 的表计数和将用于 ID/引用重写的注册字段清单；不读取源活动路径。新增 `deeptutor migration sqlite snapshot|source-check|plan` CLI，帮助和 source-check/plan 不需要 PG DSN，也不创建本地用户库。
- 本切片未新增 PostgreSQL schema（staging/维护门禁在 1.31），未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py -q
# RED（实现前）：ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.offline_import'
# GREEN：5 passed in 0.66s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py \
  tests/persistence/legacy_baseline/test_representative_formats.py -q
# 12 passed in 0.90s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/cli/test_pg_accounts.py::test_account_help_is_lazy \
  tests/persistence/postgres/test_migrations.py -q
# 10 passed in 2.07s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import \
  deeptutor_cli/migration.py deeptutor_cli/main.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/sqlite_snapshot.py \
  deeptutor/persistence/postgres/offline_import/planner.py \
  deeptutor_cli/migration.py deeptutor_cli/main.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py
# exit 0
```

边界：1.30 只完成源端独立 snapshot、manifest、引用字段注册表以及离线 source-check/plan；PG `migration_stage` schema、批次账本、维护门禁、promotion 原子发布和正式 import 写入继续在 1.31–1.40 推进。

## 2026-09-15：1.31 migration_stage schema / 批次账本 / 维护门禁 / 单事务 promotion（已完成）

- 新增 `0012_offline_import_stage.sql`，创建独立 `migration_stage` schema 以及 `batches`、`sources`、`id_mappings`、`progress`、`promotion_items`。schema 不向 `dt_enterprise_app` 授权 USAGE/表权限，运行角色无法读取 staging 源数据、映射或进度账本。
- 在 `enterprise` schema 新增 `maintenance_locks` 作为业务维护门禁；运行角色仅有带 tenant RLS 的 SELECT 权限，不能写入/释放维护态。`MigrationRunner` 将 0012 纳入连续 schema history，并扩展 verify：校验 `maintenance_locks` 的列/约束/RLS/权限、`migration_stage` 表集合/列集合、无 RLS、以及运行角色无 schema/table privilege。
- 新增 `MigrationStageRepository`：支持创建 batch、登记 source manifest、写入稳定 ID 映射、记录分块进度/恢复 cursor、取消 batch、进入/释放维护态、按 terminal batch 清理 staging 明细并保留 batch 审计。取消后的 batch 拒绝继续记录新分块。
- 新增 `PromotionStep` 与 `promote_batch()`，在同一 PG 事务内锁定 batch 与 maintenance lock，执行所有目标写入步骤并最终标记 `published`；任一步骤失败时整次 promotion 回滚，已插入正式业务表的记录不可见，batch 状态也不被错误地发布。published 不自动开放业务，仍需后续 1.40 cutover 释放。
- 新增 `offline_import.maintenance.install_maintenance_guards()`，为 async `Database` 与 `SyncDatabase` 安装每事务维护态检查；`DefaultPostgresRuntime` 启动时对异步/同步池都安装该 guard，因此 Web/CLI/SDK/后台业务事务在目标 tenant active maintenance 时 fail-closed。
- 本切片新增 PostgreSQL schema migration 0012；不涉及 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migration_stage.py -q
# RED（实现前）：migration_stage 表集合为空、offline_import.stage 模块不存在
# GREEN：4 passed in 5.96s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migrations.py -q
# 9 passed in 1.69s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py -q
# 19 passed in 8.73s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/business/test_session_composition.py \
  tests/persistence/postgres/business/test_notebook_store.py -q
# 28 passed in 47.39s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/migrations/runner.py \
  deeptutor/persistence/postgres/offline_import \
  deeptutor/app/postgres_runtime.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/migrations/runner.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  deeptutor/persistence/postgres/offline_import/maintenance.py \
  deeptutor/persistence/postgres/offline_import/stage.py \
  deeptutor/app/postgres_runtime.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py
# exit 0
```

补充说明：额外尝试运行 `tests/api/test_default_pg_runtime.py tests/cli/test_pg_accounts.py::test_account_help_is_lazy -q` 时，前两个 API lifespan 用例在导入 `co_writer` 路由时因临时 `DEEPTUTOR_HOME` 下缺 `main.yaml` 失败；后两个默认容器/账号用例通过。该失败发生在维护门禁业务路径之前，未作为 1.31 完成证据，后续按 1.44 旧入口回归统一处理。

边界：1.31 完成 staging schema、账本、维护门禁、单事务 promotion 机制和运行角色隔离；实际各域 ID 分配/引用重写、SQLite/PocketBase/Matrix 数据落入 staging 与语义 verify 继续在 1.32–1.39，cutover/回退释放继续在 1.40。

## 2026-09-15：1.32 稳定 ID 映射 / parent DAG 分配 / typed 引用重写（已完成）

- 新增 `offline_import.id_mapping`：`stable_text_id()` 将 domain/source/owner/source key 纳入哈希，避免两个用户或两个源中相同旧 ID 串线；`MigrationIdAllocator.allocate_session_id()` 将分配结果持久化到 `migration_stage.id_mappings`，重试返回同一 target key，并在目标 `enterprise.sessions` 或当前 batch 已占用该 key 时自动追加稳定后缀而不覆盖既有 PG 数据。
- 新增 `SourceMessage` 与 `allocate_message_dag_ids()`：按原 `created_at/source_id` 稳定排序并递归保证 parent 先分配，生成的目标整数 ID 始终满足 `parent < child`；缺父、重复源 ID 与环会明确拒绝，不静默丢弃或重排坏记录。
- 新增 `advance_identity_sequence()`：支持在 migration role 用 `OVERRIDING SYSTEM VALUE` 显式导入 `GENERATED ALWAYS` 整数 ID 后，将目标表 identity sequence 推进到已占用上界，后续正常 PG 写入不会与导入记录冲突。
- 新增 `TypedReferenceRewriter`：基于 1.30 的版本化 `ReferenceRegistry` 只重写登记过的结构字段/typed JSON 路径（如 `messages.session_id`、`messages.parent_message_id`、`messages.events_json[*].turn_id`、`attachments_json[*].id`、`metadata_json.source_message_id`、`sessions.summary_up_to_msg_id`），不会全文替换普通 `content`、caption 或 note 文本。
- 重写器对已登记引用缺少映射时报 `MissingReferenceError`；对 JSON 中形如 `*_id` / `id` 且未被 registry 声明的机器引用路径报 `UnknownMachineReferenceError`；对 `preserve_audit_only` 旧链接字段输出 `old_links` 报告而不随机路由到目标资源。
- 本切片未新增 PostgreSQL schema（复用 1.31 的 `migration_stage.id_mappings`），未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_offline_id_mapping.py -q
# RED（实现前）：ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.offline_import.id_mapping'
# GREEN：4 passed, 2 warnings in 5.52s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_offline_id_mapping.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py -q
# 13 passed, 2 warnings in 11.96s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import \
  tests/persistence/postgres/test_offline_id_mapping.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  deeptutor/persistence/postgres/offline_import/id_mapping.py \
  deeptutor/persistence/postgres/offline_import/maintenance.py \
  deeptutor/persistence/postgres/offline_import/planner.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/sqlite_snapshot.py \
  deeptutor/persistence/postgres/offline_import/stage.py \
  tests/persistence/postgres/test_offline_id_mapping.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py
# exit 0
```

边界：1.32 完成通用映射、DAG/sequence 和 typed JSON 重写基础；真正读取并写入 session/message/notebook/category 源数据在 1.33，learning/reading 在 1.34，cron/Partners/MarginNote 在 1.35，Matrix 在 1.36。

## 2026-09-15：1.33 SQLite chat_history 会话/消息/turn/event/题库/分类导入（已完成）

- 新增 `SQLiteChatHistoryImporter`，仅接受 1.30 manifest/source-check 通过的 `chat_history_sqlite/v1` 独立 snapshot，以 `mode=ro&immutable=1` 读取，不访问活动源路径、不修改源主库/WAL/SHM，不导入或读取旧 token 表。
- 导入器为每个 manifest 创建 `migration_stage` batch 并进入维护态，验证 target tenant/owner 显式映射且目标 owner 存在/未禁用；未知 source owner 或不存在 target owner 会拒绝，不默认归 admin、不自动创建可登录账号。
- 会话导入保留 title、summary、`summary_up_to_msg_id`、preferences、created/updated 时间；消息导入保留 role/content/capability/events/attachments/metadata/created_at 和 parent 分支结构，使用 1.32 DAG 分配保证 `parent < child`。
- turn/turn_events 导入保留 status、worker owner、fencing/state version、assistant/user message 锚点、事件 seq 与 metadata；SQLite 无显式 `user_message_id` 时按 assistant message 的 parent 推导 user anchor。
- 题库 entries/categories/entry_categories 导入保留 question/answer/correct/explanation/difficulty/bookmark/resolved/category 与时间/排序；entry/category ID 通过目标 owner 范围稳定分配并推进 `notebook_entries` / `notebook_categories` sequence。
- 所有正式业务写入在同一 PG 事务内完成；坏 parent DAG（缺父/环）在写入前拒绝，测试验证失败后没有部分 session 可见。两个 target owner 导入相同旧 session/message/turn ID 时目标 session/turn/message 均隔离且不冲突。
- 本切片未新增 PostgreSQL schema（复用 1.31 staging/维护门禁与既有 session/notebook schema），未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_chat_history_import.py -q
# RED（实现前）：ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.offline_import.chat_sqlite'
# GREEN：3 passed in 8.57s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_id_mapping.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py -q
# 16 passed, 2 warnings in 20.13s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_id_mapping.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  deeptutor/persistence/postgres/offline_import/chat_sqlite.py \
  deeptutor/persistence/postgres/offline_import/id_mapping.py \
  deeptutor/persistence/postgres/offline_import/maintenance.py \
  deeptutor/persistence/postgres/offline_import/planner.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/sqlite_snapshot.py \
  deeptutor/persistence/postgres/offline_import/stage.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_id_mapping.py
# exit 0
```

边界：1.33 只覆盖 chat_history SQLite 的 session/message/turn/event/notebook/category 域。mastery/reading 旧库导入继续在 1.34，cron/Partners/MarginNote 在 1.35，Matrix 在 1.36，PocketBase 在 1.37–1.38。


## 2026-09-15：1.34 SQLite mastery v1/v2 与 reading_catalog 导入（已完成）

- 新增 `SQLiteLearningReadingImporter`，仅接受 1.30 manifest/source-check 通过的 `mastery_sqlite/v1`、`mastery_sqlite/v2`、`reading_catalog_sqlite/v1` 独立 snapshot，以 `mode=ro&immutable=1` 读取离线制品，不访问活动源路径。
- 将 mastery v1/v2 与 reading source 纳入版本化 registry schema 校验；同一 manifest 内按 reading→mastery 顺序在一个 PG 事务中写入正式表，复用 `migration_stage` batch/source/id_mappings 和维护门禁，失败时正式业务表无部分可见。
- mastery 导入保留 path 正文 state、revision/CAS 版本、knowledge point 投影、session 绑定、v1 creator/owns_path、v2 topic metadata/source 顺序、interaction question/result/user_answer、event 顺序；chat/question_bank topic source 通过已有 session/notebook entry 映射重写。
- reading 导入保留 material 正文字段、workspace active material、tab_order/pinned/opened、reading session title/active material/version 与 session links；session 引用统一解析已有 `migration_stage.id_mappings` 或已存在目标 PG session，缺映射拒绝。
- 已补齐 chat_history importer 对 notebook entry/category 的 stage 映射记录，供 mastery topic source 和后续跨域验证使用。
- 不同 SQLite 来源使用同一 material/workspace ID 且内容不一致时拒绝并回滚；相同已验证 source fingerprint 可作为重复来源去重，不覆盖目标已有更新。
- 本切片未新增 PostgreSQL schema（复用 1.31 staging/维护门禁与 1.16/1.18 learning/reading schema），未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_learning_reading_import.py -q
# RED（实现前）：ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.offline_import.learning_reading_sqlite'
# GREEN：4 passed in 10.71s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_learning_reading_import.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_id_mapping.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py \
  tests/persistence/postgres/test_migration_stage.py -q
# 20 passed, 2 warnings in 30.76s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/chat_sqlite.py \
  deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py \
  tests/persistence/postgres/test_sqlite_learning_reading_import.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/chat_sqlite.py \
  deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py \
  tests/persistence/postgres/test_sqlite_learning_reading_import.py
# exit 0
```

边界：1.34 覆盖 mastery 与 reading 旧 SQLite 离线导入。cron/Partners/MarginNote 导入继续在 1.35，Matrix 在 1.36，PocketBase 在 1.37–1.38；最终 verify/report、cutover 与零 SQLite 运行门禁仍在后续任务。


## 2026-09-15：1.35 SQLite cron / Partners runtime status / MarginNote 导入（已完成）

- 新增 `SQLiteRuntimeProjectionImporter`，仅接受 1.30 manifest/source-check 通过的 `cron_sqlite/v1`、`partner_runtime_status_sqlite/v1`、`marginnote_sqlite/v1` 独立 snapshot，以 `mode=ro&immutable=1` 读取离线制品，不访问活动源路径。
- 将 cron、Partners runtime status、MarginNote 源纳入版本化 registry schema 校验，不再是占位 source version；每个导入 batch 进入 `migration_stage` 维护态，验证 target tenant/owner 显式映射且目标 owner 存在/未禁用。
- cron 导入保留 at/every/cron payload、timezone、enabled/delete_after_run、next/last run 与历史；chat owner 的 user/session 归属重写到目标 owner/已有 session 映射。源中运行中/claimed/dispatching 状态导入为 `uncertain` 终态 execution 并清空 `next_run_at_ms`，重启后 `claim_due` 不会自动重发。
- Partners runtime status 按可重建投影导入：旧 SQLite 状态只作为已过期 projection 保存，payload 去除 `channels`，保留 worker/version/started/error；目标已有更新或更新的非导入状态不会被旧 snapshot 覆盖。
- MarginNote 导入保留 KB 显式映射、device/token_hash/active、cursor、object、tombstone；撤销设备保持 inactive，目标已有较新 cursor/object/device 不覆盖，tombstone 不复活旧对象，删除标记按 device/KB/owner 维度导入。
- 修复 `deeptutor.capabilities.marginnote4` 顶层 eager import 导致的 `PostgresMarginNoteStore -> models -> tools -> PostgresMarginNoteStore` 循环，改为惰性导出，保持公开导出名不变。
- 本切片未新增 PostgreSQL schema（复用 1.20/1.22/1.27 与 1.31 schema），未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_runtime_projection_import.py -q
# RED（实现前）：ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.offline_import.runtime_sqlite'
# GREEN：1 passed in 3.13s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_runtime_projection_import.py \
  tests/persistence/postgres/business/test_cron_repository.py \
  tests/persistence/postgres/business/test_partner_runtime_status.py \
  tests/persistence/postgres/business/test_marginnote_store.py -q
# 11 passed, 3 warnings in 29.35s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_learning_reading_import.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py \
  tests/persistence/postgres/test_migration_stage.py -q
# 16 passed in 26.17s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import/runtime_sqlite.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  deeptutor/capabilities/marginnote4/__init__.py \
  tests/persistence/postgres/test_sqlite_runtime_projection_import.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/runtime_sqlite.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  deeptutor/capabilities/marginnote4/__init__.py \
  tests/persistence/postgres/test_sqlite_runtime_projection_import.py
# exit 0
```

边界：1.35 覆盖 cron、Partners runtime status 与 MarginNote 旧 SQLite 离线导入/可重建投影策略。Matrix 旧 store 导入继续在 1.36，PocketBase 在 1.37–1.38；最终 verify/report、cutover、零 SQLite 运行门禁、容量和制品验收仍在后续任务。

## 2026-09-15：1.36 Matrix nio SQLite store 离线导入（已完成）

- 新增 `SQLiteMatrixStoreImporter`，仅接受 1.30 manifest/source-check 通过的 `matrix_nio_sqlite/v0.26` 独立 snapshot，以 `mode=ro&immutable=1` 读取离线制品；每个批次进入 `migration_stage` 维护态，验证 target tenant/owner 显式映射且目标 owner 存在/未禁用。
- 将 Matrix nio 0.26 store 表纳入版本化 registry schema 校验；导入覆盖 account、Olm session、Megolm inbound session、forwarded chain、device keys/key values、device trust state、encrypted rooms、sync token 与 outgoing key request。
- manifest 只保存 legacy pickle / target pickle / envelope 的 Secret ID 与版本，不保存 Secret 原文；导入时用 resolver 读取 Secret，将旧 pickle blob 用 legacy key 解开后重新以目标 pickle key 序列化，并使用与 `PostgresMatrixStore` 兼容的 AAD/envelope Secret 写入 PG。
- 目标同一 owner/partner/Matrix user/device 已存在 account 时拒绝导入，防止旧设备状态覆盖当前状态；相同快照重放复用已验证源并保持切换后设备撤销/blacklist 状态，不因恢复旧 snapshot 自动复活。
- 错误 legacy pickle key 以 `MatrixStoreEncryptionError` 失败；源 snapshot 被修改时由 source-check 阻断。导入后可通过 `PostgresMatrixStore` 加载原 account identity、加密会话、设备信任、同步游标和 outgoing key request。
- 本切片未新增 PostgreSQL schema（复用 1.24 与 1.31 schema），未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_matrix_store_import.py -q
# RED（实现前）：ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.offline_import.matrix_sqlite'
# GREEN：3 passed in 8.22s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_matrix_store_import.py -q
# 4 passed in 10.70s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_sqlite_matrix_store_import.py \
  tests/persistence/postgres/business/test_matrix_store.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py \
  tests/persistence/postgres/test_migration_stage.py -q
# 16 passed in 25.44s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import/matrix_sqlite.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/persistence/postgres/test_sqlite_matrix_store_import.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/matrix_sqlite.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/persistence/postgres/test_sqlite_matrix_store_import.py
# exit 0
```

边界：1.36 覆盖 Matrix 旧 nio SQLite store 离线迁移、Secret 映射、错误密钥、源变化、目标设备冲突和旧快照重放后的撤销核对。PocketBase exporter/importer 继续在 1.37–1.38；最终 verify/report、cutover、零 SQLite 运行门禁、容量和制品验收仍在后续任务。

## 2026-09-15：1.37 PocketBase 受控只读 exporter / manifest（已完成）

- 新增 `create_pocketbase_source_export` / `PocketBaseExportError`，通过 PocketBase SDK 只读分页读取本应用实际支持 collection：`users`、`sessions`、`messages`、`turns`、`turn_events`、`knowledge_bases`。
- exporter 要求 freeze_id、stopped_writers 与显式 owner mapping；使用稳定 `sort=id` 分页读取，同一 collection 双读摘要不一致、分页总数变化、schema 变化、缺 collection/schema 字段或任一 collection 权限不足都会失败且不写残缺制品。
- 导出的 JSON snapshot 覆盖 collection schema、记录、record counts、schema/content hash 以及 `knowledge_bases.raw_files` 文件清单；不调用 PocketBase create/update/delete，不删除或改写远端服务。
- manifest 复用离线源协议（manifest_version/freeze/target/owner_mappings/sources），source version 注册为 `pocketbase/v1`；`source_check_manifest` 已支持 PocketBase JSON snapshot 的 hash、record counts、schema 字段与内容摘要校验。
- exporter/CLI 不把 endpoint userinfo/query token、admin password、用户 tokenKey 等凭证写入 manifest/snapshot；PocketBase CLI export 使用 `--admin-password-env` 从环境读取密码，仅产出离线 artifact。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD 与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_pocketbase_export.py -q
# RED（实现前）：ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.offline_import.pocketbase_export'
# GREEN：3 passed in 0.24s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_pocketbase_export.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py -q
# 8 passed in 1.10s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import/pocketbase_export.py \
  deeptutor/persistence/postgres/offline_import/planner.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  deeptutor_cli/migration.py \
  tests/persistence/postgres/test_pocketbase_export.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/pocketbase_export.py \
  deeptutor/persistence/postgres/offline_import/planner.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  deeptutor_cli/migration.py \
  tests/persistence/postgres/test_pocketbase_export.py
# exit 0
```

边界：1.37 只完成 PocketBase 只读导出与 manifest/source-check。PocketBase 离线 PG importer、字符串 ID→整数映射、用户凭证重置与混合批次冲突验证继续在 1.38；最终 verify/report、cutover 与零 SQLite 运行门禁仍在后续任务。

## 2026-09-15：1.38 PocketBase 离线 PG importer（已完成）

- 新增 `PocketBaseOfflineImporter`，仅读取 1.37 产出的 `pocketbase/v1` JSON snapshot/manifest，不访问远端 PocketBase；导入前复用 `source_check_manifest` 校验 snapshot hash、schema、record counts 与内容摘要。
- importer 复用 `migration_stage` batch/source/id_mappings 与维护门禁；同一 source fingerprint 已验证时幂等跳过，不重复写业务表、不重复重置凭证。
- PocketBase `users` 只做显式 owner mapping，不导入旧 token/password/tokenKey；目标 owner `auth_version` 受控递增并记录 `credential_reset_required`，报告需重置凭证的 source→target 映射。
- 将 PocketBase string session/message/turn/resource/file 引用稳定映射到 PG：session 使用 `MigrationIdAllocator`，message 使用当前 PG 最大整数后顺序分配并推进 identity sequence，turn/resource 使用 `stable_text_id`；typed JSON 中 `message_id`、`source_message_id` 与 attachment id 被结构化重写，不做全文替换。
- 导入 sessions/messages/turns/turn_events，保留 summary/preferences、message attachments/metadata、turn owner/fencing/state、assistant/user message 关联与事件 metadata；`knowledge_bases.raw_files` 作为文件引用映射记入 `migration_stage.id_mappings`，不伪造不存在的 PG 知识库表。
- 混合 manifest 中同时存在 SQLite source 时，PocketBase importer 只处理 `pocketbase/v1` source 且 source-check 仍校验全部 artifact；坏 message→session 引用会阻断导入，不静默跳过。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD、调试与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_pocketbase_import.py -q
# RED（实现前）：ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.offline_import.pocketbase_import'
# GREEN：3 passed（随后与 exporter 联合验证为 6 passed in 8.18s）

# GREEN 期间失败根因：
# 1) registry 漏登记 PocketBase messages.metadata_json.message_id/source_message_id，引用守卫正确拒绝；已补 registry。
# 2) turns.turn_id 的 registry target 为 turns.id，实现缺少同义映射；已补 turns.id -> turn_map。
# 3) exporter 敏感字段过滤误剥离 fencing_token；已收窄过滤，保留 turn lease 字段。

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_pocketbase_import.py \
  tests/persistence/postgres/test_pocketbase_export.py -q
# 6 passed in 8.18s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_pocketbase_import.py \
  tests/persistence/postgres/test_pocketbase_export.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_id_mapping.py \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py \
  tests/persistence/postgres/test_migration_stage.py -q
# 22 passed, 2 warnings in 28.40s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import/pocketbase_import.py \
  deeptutor/persistence/postgres/offline_import/pocketbase_export.py \
  deeptutor/persistence/postgres/offline_import/planner.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/persistence/postgres/test_pocketbase_import.py \
  tests/persistence/postgres/test_pocketbase_export.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/pocketbase_import.py \
  deeptutor/persistence/postgres/offline_import/pocketbase_export.py \
  deeptutor/persistence/postgres/offline_import/planner.py \
  deeptutor/persistence/postgres/offline_import/registry.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/persistence/postgres/test_pocketbase_import.py \
  tests/persistence/postgres/test_pocketbase_export.py
# exit 0
```

边界：1.38 覆盖 PocketBase 离线 PG importer、用户映射/凭证重置、string ID→PG ID 映射、文件引用、幂等、坏引用和混合来源 manifest。跨全部来源/owner 的最终 verify/report 继续在 1.39；cutover/回退、零 SQLite 运行门禁、容量和制品验收仍在后续任务。

## 2026-09-15：1.39 离线导入 verify/report（已完成）

- 新增 `OfflineImportVerifier` / `OfflineVerifyReport`，按 batch 读取 `migration_stage.sources`，为每个 source 输出 `source_owner_id -> target_owner_id`、每域 source/target 计数、目标内容摘要 `content_digest`，并将完整报告写回 `migration_stage.batches.verify_report`。
- verify/report 覆盖当前已实现离线来源：`chat_history_sqlite/v1`、`mastery_sqlite/v1|v2`、`reading_catalog_sqlite/v1`、`cron_sqlite/v1`、`partner_runtime_status_sqlite/v1`、`marginnote_sqlite/v1`、`matrix_nio_sqlite/v0.26`、`pocketbase/v1`。
- 校验源制品 hash、source 状态/rows_done、target owner 存在/启用、ID mapping 完整性、会话/消息/turn/event/notebook、mastery、reading、cron、Partners、MarginNote、Matrix Secret/加密状态计数等语义关系；未知 source version、未 verified source、行数不完整、读源或 SQL 校验异常都会进入 issues 并令报告失败，不静默跳过。
- 语义负例覆盖“行数相同但关系/时区/密钥错误”：PB message metadata 指向不存在 message、cron timezone 被篡改、Matrix secret_id 被篡改均使 verify/report 失败。
- 额外覆盖已登记但先前未支持的 chat/notebook、mastery/reading、cron+Partners+MarginNote 混合源，确认不会被 `source_verify_not_implemented` 静默放过。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD、调试与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_offline_import_verify_report.py -q
# RED（新增覆盖已登记 chat/learning/runtime source 后）：
# 3 failed, 3 passed；chat_history/mastery/reading/partner_runtime_status 等返回 source_verify_not_implemented
# GREEN：6 passed in 15.85s

# GREEN 期间失败根因：Matrix target 计数查询对单列 SELECT 使用 ORDER BY 1,2，导致 PG 事务 aborted；已改为 ORDER BY 1，并在 source verify 异常后 rollback 再记录 issue，避免异常静默吞掉或阻断报告写回。

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_offline_import_verify_report.py \
  tests/persistence/postgres/test_pocketbase_import.py \
  tests/persistence/postgres/test_pocketbase_export.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_sqlite_learning_reading_import.py \
  tests/persistence/postgres/test_sqlite_runtime_projection_import.py \
  tests/persistence/postgres/test_sqlite_matrix_store_import.py \
  tests/persistence/postgres/test_migration_stage.py \
  -q
# 28 passed in 62.81s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import/verify_report.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/persistence/postgres/test_offline_import_verify_report.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/verify_report.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/persistence/postgres/test_offline_import_verify_report.py
# exit 0
```

边界：1.39 完成离线导入 verify/report 层和已实现 source 语义覆盖。受控 cutover/回退检查继续在 1.40；删除旧运行路径、零 SQLite 运行门禁、容量、制品安装与最终验收仍在后续任务。

## 2026-09-15：1.40 受控 cutover 与回退检查（已完成）

- 新增 `OfflineCutoverCoordinator`、`CutoverReleaseRequest`、`RollbackCheckRequest` 与 `CutoverCheckReport`，复用 `migration_stage.batches.verify_report`、`enterprise.maintenance_locks` 和现有业务表，不新增 schema。
- `prepare_release()` 要求 batch 已 `published`、verify/report 为 ok、目标 tenant 仍处于该 batch 的维护态、manifest 声明的全部 stopped writers 已由操作者确认、目标 owner `auth_version` 与可选 device credential `generation` 未变化且未撤销。
- `release()` 在同一受控流程中记录 cutover baseline：按 tenant 对 enterprise 业务表生成摘要，写入 `verify_report.cutover.target_baseline_digest`，再释放维护锁；后续 rollback 检查以此判断 PG cutover 后是否已有新写。
- `check_rollback()` 实现回退矩阵：legacy SQLite/PocketBase 仅在源未变且 PG baseline 未变时允许；PG 已新写后阻断 legacy rollback；schema 1 旧构建始终拒绝直接跑新 schema；兼容 PG 构建/PG 备份恢复必须显式确认。
- cron `uncertain` execution 默认阻断 cutover/rollback，除非操作者逐项或 `*` 标记已对账，避免外部动作自动重发；身份/设备世代变化或撤销会阻断回退，避免恢复旧账号/设备权限。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD、调试与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_offline_cutover.py -q
# RED（实现前）：3 failed；ModuleNotFoundError: No module named 'deeptutor.persistence.postgres.offline_import.cutover'
# GREEN：3 passed in 8.61s

# GREEN 期间失败根因：required stopped writers 读取了 per-source manifest；SQLite snapshot 的 freeze/stopped_writers 位于 batch.source_manifest 顶层。已修正为同时读取 batch.source_manifest 与 source manifest。

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_offline_cutover.py \
  tests/persistence/postgres/test_offline_import_verify_report.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_sqlite_runtime_projection_import.py \
  tests/persistence/postgres/test_sqlite_matrix_store_import.py \
  tests/persistence/postgres/test_pocketbase_import.py \
  tests/persistence/postgres/test_pocketbase_export.py \
  -q
# 27 passed in 59.07s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import/cutover.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/persistence/postgres/test_offline_cutover.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/cutover.py \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/persistence/postgres/test_offline_cutover.py
# exit 0
```

边界：1.40 完成受控 cutover/rollback 检查制品与隔离 PG 测试；未执行真实生产 cutover、真实数据导入、发布、提交或归档。删除旧运行路径、零 SQLite 运行门禁、容量、制品安装与最终验收仍在后续任务。


## 2026-09-15：1.41 删除旧运行 backend 与自动迁移路径（已完成）

- `get_sqlite_session_store()` 及 `deeptutor.services.session.get_sqlite_session_store` 现在在 PG-only runtime 下返回明确 `RuntimeError`，提示 SQLite 仅限受控离线 import/旧格式 fixture，不再静默创建 `chat_history.db`。
- `PocketBaseSessionStore()` 构造与 `get_pb_client()` 均返回明确 `RuntimeError`；`is_pocketbase_enabled()` 固定为 `False`，即使旧 PocketBase 配置存在也不能重新启用运行期 backend。历史 PocketBase 数据仅通过离线 exporter/importer 交接。
- `ApplicationContainer.migrate_legacy_chat()`、`migrate_all_legacy_chats()`、`migrate_all_workspace_preferences()` 和 `run_startup_data_migrations()` 改为明确拒绝旧启动迁移；runtime doctor 不再调用旧 migrator，只报告 `legacy_chat_migration` 为非必需 skip，并指向 offline import。
- 将外部 chat history 导入 ID helper 下沉为 runtime-safe `deeptutor.services.session.import_ids`，`/api/imports` 与 `deeptutor.services.session.make_imported_session_id` 不再因 helper 加载 `sqlite_store`；`SQLiteSessionStore` 保留在直接模块中，供受控离线 importer/旧格式 fixture 使用，不再从 `deeptutor.services.session` 包级导出。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD、调试与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest tests/app/test_startup_data_migrations.py -q
# RED：1 failed；run_startup_data_migrations 仍执行 legacy/workspace 迁移而非 PG-only 拒绝

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/persistence/postgres/test_legacy_runtime_backends_disabled.py::test_runtime_doctor_reports_legacy_import_as_disabled -q
# RED：1 failed；runtime doctor 将旧 migrator 异常报告为 required fail，说明仍在调用旧迁移路径

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/persistence/postgres/test_legacy_runtime_backends_disabled.py::test_chat_history_import_router_does_not_load_sqlite_runtime -q
# RED：1 failed；导入 /api/imports 时通过包级 make_imported_session_id 加载了 deeptutor.services.session.sqlite_store

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/persistence/postgres/test_legacy_runtime_backends_disabled.py \
  tests/app/test_startup_data_migrations.py -q
# GREEN：6 passed in 0.61s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_legacy_runtime_backends_disabled.py \
  tests/app/test_startup_data_migrations.py \
  tests/app/test_default_pg_sdk.py \
  tests/cli/test_default_pg_cli.py \
  tests/api/test_default_pg_runtime.py \
  tests/api/test_default_pg_question_bank.py \
  tests/api/test_default_pg_book_course_consumers.py \
  tests/api/test_imports.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_import_verify_report.py \
  -q
# 51 passed, 2 warnings in 52.11s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/services/session/import_ids.py \
  deeptutor/services/session/sqlite_store.py \
  deeptutor/services/session/__init__.py \
  deeptutor/api/routers/imports.py \
  deeptutor/app/container.py \
  deeptutor/services/doctor.py \
  tests/app/test_startup_data_migrations.py \
  tests/persistence/postgres/test_legacy_runtime_backends_disabled.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/services/session/import_ids.py \
  deeptutor/services/session/sqlite_store.py \
  deeptutor/services/session/__init__.py \
  deeptutor/api/routers/imports.py \
  deeptutor/app/container.py \
  deeptutor/services/doctor.py \
  tests/app/test_startup_data_migrations.py \
  tests/persistence/postgres/test_legacy_runtime_backends_disabled.py
# exit 0
```

边界：1.41 完成默认旧 backend/factory、旧启动迁移和普通导入路由的 SQLite/PocketBase 运行路径退出。`SQLiteSessionStore` 模块本身仍为离线 importer 与旧格式 fixture 保留；残余依赖/配置扫描、零 SQLite 子进程门禁、旧 local 测试契约替换继续在 1.42–1.44。

## 2026-09-15：1.42 aiosqlite 直接依赖移除与残余 SQLite 分类（已完成）

- 从默认安装面移除 `aiosqlite>=0.19.0` 直接声明：`pyproject.toml`、`packaging/deeptutor-cli/pyproject.toml`、`requirements/cli.txt`。`server` extra 继承后也不再引入直接 `aiosqlite`。
- 新增 `sqlite-reference-classification.md`，把所有生产 `sqlite3` import 分为：受控离线 importer/source-check/verify、旧格式 fixture/legacy module、非连接型字符串/文案；文档明确“业务默认运行图：禁止”。
- 新增 `test_sqlite_reference_inventory.py` 静态门禁：扫描 `deeptutor/**/*.py`（排除 tests）中每个 `sqlite3` import，并要求全部出现在分类报告；新增 packaging metadata 门禁确保 root、CLI extra、server extra、CLI-only wheel、requirements/cli 不再直接声明 `aiosqlite`。
- 传递 SDK/plugin 核查记录：当前开发 venv 中 `llama-index-core==0.14.24` 仍声明 `aiosqlite`，`matrix-nio==0.26.0` 包含内置 SQLite store，`openai-agents==0.20.0` 包含可选 SQLite memory session，`pageindex==0.2.16` 包内未发现 sqlite/aiosqlite 字符串。上述传递风险不由本包直接声明，后续 1.43 通过新进程/子进程 `sqlite3.connect` 门禁覆盖。
- 将旧 `tests/persistence/postgres/test_learning_imports.py` 包级 `SQLiteSessionStore` 兼容预期改为新契约：`make_imported_session_id` 是 runtime-safe helper 且不加载 `sqlite_store`；`SQLiteSessionStore` 只能从直接 legacy 模块显式导入，不能作为 `deeptutor.services.session` 包级运行导出。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD、调试与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/test_packaging_metadata.py::test_aiosqlite_is_not_a_direct_runtime_dependency -q
# RED：1 failed；root dependencies 仍包含 aiosqlite>=0.19.0
# GREEN：1 passed in 0.01s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/persistence/postgres/test_sqlite_reference_inventory.py -q
# RED：1 failed；sqlite-reference-classification.md 尚不存在
# GREEN：1 passed in 0.10s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres/test_sqlite_reference_inventory.py \
  tests/persistence/postgres/test_learning_imports.py -q
# 27 passed in 0.40s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres/test_sqlite_reference_inventory.py \
  tests/persistence/postgres/test_learning_imports.py \
  tests/persistence/postgres/test_legacy_runtime_backends_disabled.py \
  tests/app/test_startup_data_migrations.py \
  tests/app/test_default_pg_sdk.py \
  tests/cli/test_default_pg_cli.py \
  tests/api/test_default_pg_runtime.py \
  tests/api/test_default_pg_question_bank.py \
  tests/api/test_default_pg_book_course_consumers.py \
  tests/api/test_imports.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_import_verify_report.py \
  -q
# 78 passed, 2 warnings in 53.50s

rg -n "aiosqlite" pyproject.toml packaging requirements deeptutor tests
# 仅剩 tests/persistence/postgres/test_sqlite_reference_inventory.py 与 tests/test_packaging_metadata.py 的门禁断言命中

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres/test_sqlite_reference_inventory.py \
  tests/persistence/postgres/test_learning_imports.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres/test_sqlite_reference_inventory.py \
  tests/persistence/postgres/test_learning_imports.py
# exit 0
```

边界：1.42 完成直接依赖移除、传递风险核查和静态分类门禁。动态新进程/子进程零 SQLite 访问验证继续在 1.43；旧 local 无 PG 测试契约替换与更大回归继续在 1.44。

## 2026-09-15：1.43 新进程/子进程零 SQLite 访问门禁（已完成）

- 新增 `tests/persistence/postgres/test_zero_sqlite_runtime_guard.py`：父进程准备隔离真实 PG schema 与 PG 身份；子进程在导入 DeepTutor 前 patch `sqlite3.connect`，先确认 `:memory:` 与文件路径都被 guard 拒绝，再启动默认 `ApplicationContainer`。
- 子进程在同一默认 PG runtime 中完成最小业务矩阵：session/message、question notebook、learning path save/load、reading material/workspace、cron schedule、Partners runtime status、MarginNote pair/sync/search、Matrix PG store sync token（普通）与 account/encrypted_rooms（E2EE state）。
- guard 记录只允许两次自测命中；业务执行后若出现额外 `sqlite3.connect`（包括第三方 C/native sqlite3、`:memory:` 或文件路径）即失败。执行结束还扫描 `DEEPTUTOR_HOME` 下 `*.sqlite`、`*.sqlite3`、`*.db`，确认默认 runtime 不生成旧数据库制品。
- 该门禁没有把离线 importer 加入业务 allowlist；离线导入仍由 1.30–1.39 独立测试覆盖，业务子进程不导入 offline_import 路径。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD、调试与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_zero_sqlite_runtime_guard.py -q
# RED：1 failed；notebook entry 使用假 turn_id 时 PG 复合 FK 拒绝，说明 smoke 需要真实 turn 引用
# 根因：question notebook PG 契约要求 session+turn 复合引用存在；修正为先调用 store.create_turn()
# GREEN：1 passed in 1.69s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_zero_sqlite_runtime_guard.py \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres/test_sqlite_reference_inventory.py \
  tests/persistence/postgres/test_learning_imports.py \
  tests/persistence/postgres/test_legacy_runtime_backends_disabled.py \
  tests/app/test_startup_data_migrations.py \
  tests/app/test_default_pg_sdk.py \
  tests/cli/test_default_pg_cli.py \
  tests/api/test_default_pg_runtime.py \
  tests/api/test_default_pg_question_bank.py \
  tests/api/test_default_pg_book_course_consumers.py \
  tests/api/test_imports.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_import_verify_report.py \
  -q
# 79 passed, 2 warnings in 49.79s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  tests/persistence/postgres/test_zero_sqlite_runtime_guard.py \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres/test_sqlite_reference_inventory.py \
  tests/persistence/postgres/test_learning_imports.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  tests/persistence/postgres/test_zero_sqlite_runtime_guard.py \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres/test_sqlite_reference_inventory.py \
  tests/persistence/postgres/test_learning_imports.py
# exit 0
```

边界：1.43 完成动态零 SQLite 子进程门禁与当前全域 smoke；旧 local 无 PG 测试契约替换、更完整首切片/core 回归继续在 1.44。

## 2026-09-15：1.44 首切片 PG/身份/会话/恢复与受影响 core 回归（已完成）

- 重跑首切片企业/默认 PG、身份、会话、恢复与 WebSocket lifecycle 回归，确认 core 默认 PG 与企业兼容入口仍共享同一 PG 契约。
- 将受旧 local/SQLite 无 PG 假设影响的 session 单元测试改为新契约：
  - `test_session_factory.py`：旧 PocketBase/SQLite runtime cache 断言改为 PG provider_context 装配与无 provider fail-closed。
  - `test_pocketbase_isolation.py`：PocketBase runtime 构造/旧配置均失败关闭；同 owner 隔离改由真实 PG store 覆盖。
  - `test_trace_memory.py`、`test_turn_event_flush.py`：原 SQLite/PocketBase 持久化细节改为真实 PG store 的 canonical trace、turn events、delete/append/status/message-id 契约；纯预览算法测试保留。
  - `test_resource_isolation.py`：旧 per-user SQLite db_path 断言改为 PG store_scope/owner 资源隔离；图书路径隔离和 partner admin anchor 继续覆盖。
  - `test_sqlite_store.py` 与 `tests/services/session/conftest.py`：直接 `SQLiteSessionStore` 仅作为 legacy/offline fixture，在显式 synthetic owner 或显式 db_path 下使用；不再作为默认业务 factory。
  - `test_turn_runtime_subscribe.py`：旧 LearningStore 测试夹具补齐 PG learning runtime 的 authority/bind/lease/notebook 接口形状，使测试验证 turn runtime 行为而不是依赖旧隐式 SQLite runtime provider。
- 修复回归中暴露的真实装配问题：
  - 新增 `deeptutor.services.llm.transport.LLMTransportConfig` 并接入 `LLMConfig.transport`，补齐企业/默认 PG runtime 对 Secret-backed LLM transport 的 fail-closed 校验。
  - 无附件 turn 不再提前构造 attachment store，避免 legacy/offline fixture 测试在没有附件时误触生产 PG 容器预检；有 base64 附件时仍按 PG attachment store fail-closed。
  - `SQLiteSessionStore` 显式 db_path 不要求 runtime owner，并暴露 legacy fixture scope；默认构造在测试中必须带显式 synthetic owner，防止恢复已移除的隐式 local-admin fallback。
  - artifact path resolver 对未认证 legacy/crafted URL 保持无权限不可读，不回退共享目录。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

TDD、调试与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  extensions/enterprise/tests/test_configuration.py \
  extensions/enterprise/tests/test_preflight.py::test_sdk_ambient_headers_rejected_before_application_initialization \
  -q --tb=short
# RED：enterprise app creation 缺少 deeptutor.services.llm.transport.LLMTransportConfig
# GREEN：3 passed

PYTHONPATH=.:extensions/enterprise/src:extensions/enterprise/tests .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/services/session -q --tb=short --maxfail=1
# RED：多轮失败分别定位到无附件 turn 误触 PG attachment store、legacy SQLite fixture owner 契约、legacy learning runtime authority/notebook/lease 夹具形状
# GREEN：259 passed, 5 warnings in 18.82s（随后 import/lint 调整后重跑：259 passed, 5 warnings in 17.66s）

PYTHONPATH=.:extensions/enterprise/src:extensions/enterprise/tests .venv/bin/python -m pytest --asyncio-mode=auto \
  extensions/enterprise/tests/test_versions.py \
  extensions/enterprise/tests/test_sessions.py \
  extensions/enterprise/tests/test_isolation_matrix.py \
  extensions/enterprise/tests/test_branch_consistency.py \
  extensions/enterprise/tests/test_executor.py \
  extensions/enterprise/tests/test_restore.py \
  extensions/enterprise/tests/test_cli_recovery.py \
  extensions/enterprise/tests/test_ws_subscription_lifecycle.py \
  tests/api/test_default_pg_auth.py \
  tests/api/test_default_pg_runtime.py \
  tests/app/test_default_pg_sdk.py \
  tests/cli/test_default_pg_cli.py \
  -q --tb=short
# 98 passed in 62.26s

PYTHONPATH=.:extensions/enterprise/src:extensions/enterprise/tests .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_connection.py \
  tests/persistence/postgres/test_configuration.py \
  tests/persistence/postgres/test_migrations.py \
  tests/persistence/postgres/test_account_migration.py \
  tests/persistence/postgres/test_accounts.py \
  tests/persistence/postgres/test_identity_session_core.py \
  tests/persistence/postgres/test_ownership.py \
  tests/persistence/postgres/business/test_business_fixtures.py \
  tests/persistence/postgres/business/test_session_composition.py \
  tests/persistence/postgres/business/test_session_summary.py \
  tests/persistence/postgres/business/test_session_request_snapshot.py \
  tests/persistence/postgres/business/test_session_resources.py \
  tests/persistence/postgres/business/test_session_resource_races.py \
  tests/persistence/postgres/business/test_session_deletion.py \
  tests/persistence/postgres/business/test_session_references.py \
  tests/persistence/postgres/business/test_session_import.py \
  -q --tb=short
# 194 passed in 198.17s

PYTHONPATH=.:extensions/enterprise/src:extensions/enterprise/tests .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/services/session/test_session_factory.py \
  tests/services/session/test_pocketbase_isolation.py \
  tests/services/session/test_trace_memory.py \
  tests/services/session/test_turn_event_flush.py \
  tests/multi_user/test_resource_isolation.py \
  -q --tb=short
# 22 passed in 11.94s

PYTHONPATH=.:extensions/enterprise/src:extensions/enterprise/tests .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_zero_sqlite_runtime_guard.py \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres/test_sqlite_reference_inventory.py \
  tests/persistence/postgres/test_learning_imports.py \
  tests/persistence/postgres/test_legacy_runtime_backends_disabled.py \
  tests/app/test_startup_data_migrations.py \
  tests/app/test_default_pg_sdk.py \
  tests/cli/test_default_pg_cli.py \
  tests/api/test_default_pg_runtime.py \
  tests/api/test_default_pg_question_bank.py \
  tests/api/test_default_pg_book_course_consumers.py \
  tests/api/test_imports.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_offline_import_verify_report.py \
  -q --tb=short
# 79 passed, 2 warnings in 49.33s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/services/llm/transport.py \
  deeptutor/services/llm/config.py \
  extensions/enterprise/tests/test_versions.py \
  tests/services/session/pg_helpers.py \
  tests/services/session/test_session_factory.py \
  tests/services/session/test_pocketbase_isolation.py \
  tests/services/session/test_trace_memory.py \
  tests/services/session/test_turn_event_flush.py \
  tests/multi_user/conftest.py \
  tests/multi_user/test_resource_isolation.py \
  deeptutor/services/session/sqlite_store.py \
  deeptutor/services/session/artifact_attachments.py \
  deeptutor/services/session/turns/executor.py \
  tests/services/session/test_sqlite_store.py \
  tests/services/session/conftest.py \
  tests/services/session/test_turn_runtime_subscribe.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/services/llm/transport.py \
  deeptutor/services/llm/config.py \
  extensions/enterprise/tests/test_versions.py \
  tests/services/session/pg_helpers.py \
  tests/services/session/test_session_factory.py \
  tests/services/session/test_pocketbase_isolation.py \
  tests/services/session/test_trace_memory.py \
  tests/services/session/test_turn_event_flush.py \
  tests/multi_user/conftest.py \
  tests/multi_user/test_resource_isolation.py \
  deeptutor/services/session/sqlite_store.py \
  deeptutor/services/session/artifact_attachments.py \
  deeptutor/services/session/turns/executor.py \
  tests/services/session/test_sqlite_store.py \
  tests/services/session/conftest.py \
  tests/services/session/test_turn_runtime_subscribe.py
# exit 0
```

边界：1.44 完成首切片 PG/身份/会话/恢复与本轮受影响 core 回归，并将旧 local 无 PG 预期改为 PG-only/legacy-fixture 契约。双租户/管理员全入口越权矩阵、恢复演练和容量评估继续在 1.45–1.47。

## 2026-09-15：1.45 双租户/管理员/越权/撤权矩阵（已完成）

- 执行现有真实 PG 隔离矩阵，不新增 schema 或运行时绕行：
  - `extensions/enterprise/tests/test_isolation_matrix.py` 覆盖 HTTP/WS/SDK 的同租户普通用户、管理员、无效 token、伪造 tenant header/query、同 session/turn ID 双租户碰撞与 context/cache 清理。
  - `test_business_fixtures.py` 覆盖两个 tenant 六个已认证 actor 的 async/sync 连接 scope、RLS 直接查询和连接复用后不串主体。
  - `test_notebook_schema.py`/`test_notebook_store.py` 覆盖题库同 ID、admin 无个人数据旁路、复合 FK/RLS 直接越权负例、导出分页与并发可见性。
  - `test_learning_store.py`/`test_learning_runtime.py` 覆盖学习路径全部 PG 表 owner 隔离、admin 不越权、hint cache 按 owner/session scope、后台恢复/断线重放/删除及交错回复冲突。
  - `test_reading_isolation.py`/`test_reading_runtime.py` 覆盖阅读双租户六主体同 ID、workspace/material/session/link FK 越权负例、API/工具/导入路由无 SQLite catalog。
  - `test_cron_repository.py`/`test_cron_runtime.py` 覆盖后台 cron owner、领取、暂停/删除、uncertain 外部结果不自动重发。
  - `test_partner_runtime_status.py`、`test_marginnote_store.py`/`runtime.py`、`test_matrix_store.py`/`runtime.py` 覆盖 Partners、MarginNote、Matrix 的 owner/device/worker scope、旧 worker/撤销/PG store 故障负例。
  - `test_memory_snapshot_runtime.py`、`test_session_resources.py`、`test_accounts.py`、`test_device_credentials.py` 覆盖 PG snapshot/export/resource 读取授权、附件撤权、账号/设备撤权和审计/数据库记录不泄露 pairing code、PIN 等 secret。
- 验证结论仅证明当前 PG-only 单执行者/固定部署的隔离矩阵；不宣称正式多租户产品开放或 HA 已完成。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实模型 Secret、未调用模型、未提交/推送/归档。

验证命令：

```bash
PYTHONPATH=.:extensions/enterprise/src:extensions/enterprise/tests .venv/bin/python -m pytest --asyncio-mode=auto \
  extensions/enterprise/tests/test_isolation_matrix.py \
  tests/persistence/postgres/business/test_business_fixtures.py \
  tests/persistence/postgres/business/test_session_composition.py \
  tests/persistence/postgres/business/test_notebook_schema.py \
  tests/persistence/postgres/business/test_notebook_store.py \
  tests/persistence/postgres/business/test_learning_store.py \
  tests/persistence/postgres/business/test_learning_runtime.py \
  tests/persistence/postgres/business/test_reading_isolation.py \
  tests/persistence/postgres/business/test_reading_runtime.py \
  tests/persistence/postgres/business/test_cron_repository.py \
  tests/persistence/postgres/business/test_cron_runtime.py \
  tests/persistence/postgres/business/test_partner_runtime_status.py \
  tests/persistence/postgres/business/test_marginnote_store.py \
  tests/persistence/postgres/business/test_marginnote_runtime.py \
  tests/persistence/postgres/business/test_matrix_store.py \
  tests/persistence/postgres/business/test_matrix_runtime.py \
  tests/persistence/postgres/business/test_memory_snapshot_runtime.py \
  tests/persistence/postgres/business/test_session_resources.py \
  tests/persistence/postgres/test_accounts.py \
  tests/multi_user/test_device_credentials.py \
  -q --tb=short
# 199 passed, 5 warnings in 447.12s
```

边界：1.45 完成隔离、越权、撤权、后台与导出相关矩阵的当前验证；完整导入中断/restore/受控恢复演练继续在 1.46，容量评估继续在 1.47。

## 2026-09-15：1.46 导入中断重跑、pg_dump/restore、scratch 重建与受控恢复演练（已完成）

- 在隔离 PostgreSQL fixture 上重跑离线 SQLite/PocketBase 导入链路、migration_stage 分块/取消恢复、ID 映射、跨域引用验证、cutover 门禁、pg_dump/restore、进程崩溃后 scratch 重建与受控恢复测试。
- 覆盖范围包括会话/消息/turn/events、题库/分类、learning/mastery v1/v2、reading、cron/Partners/MarginNote、Matrix 旧 store、附件/资源引用、身份/设备撤销、不确定外部副作用不自动重发，以及运行角色不可读取 staging 的维护边界。
- 修复本切片演练暴露的问题：
  - notebook 迁移测试不再假定固定迁移总数，改为断言 `0004_notebook_entries_categories` 位于既有编号位置，避免新增后续领域迁移时误报。
  - LLM 显式 transport 策略补齐 `disable_ssl_verify` 并贯通 agent/runtime/provider/http-client，PG configured 应用不再回读 file runtime settings。
  - LLM 导入期 OpenAI 兼容环境初始化仅在已有 model catalog 时同步环境变量；缺本地 catalog 时不创建 `data/user/settings`，避免 PG-only configured 进程因导入 LLM 子模块产生本地权威目录。
  - process probe 的模型 HTTP mock 只替换非 ASGITransport，保留真实 FastAPI ASGI 调用，同时用真实 OpenAI SDK/factory/provider 路径验证受控模型请求。
- 实际耗时记录：完整 1.46 验证套件 145 项通过，用时 163.98s（约 2m44s）。`test_process_rebuild.py` 子进程演练在全新 scratch 目录下验证 `local_authority_io=0`；恢复进程确认 2 个孤儿 turn 标记 `worker_lost`，模型请求未重放。本项只记录隔离环境恢复范围和耗时，不声称生产 HA/RPO/RTO。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实旧数据、未提交/推送/归档。

TDD、调试与验证：

```bash
PYTHONPATH=.:extensions/enterprise/src:extensions/enterprise/tests .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_notebook_migration.py \
  extensions/enterprise/tests/test_process_rebuild.py::test_full_process_file_guard_and_explicit_crash_rebuild \
  tests/services/llm/test_config_module.py::test_early_openai_env_setup_skips_missing_catalog \
  -q --tb=short
# RED（修复前）：process probe 发现 os.mkdir .../data/user/settings；新增导入期测试显示 _setup_openai_env_vars_early 在缺 catalog 时仍调用 resolver。
# GREEN：20 passed in 7.26s；新增单测单独重跑 1 passed in 0.13s

PYTHONPATH=.:extensions/enterprise/src:extensions/enterprise/tests .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/persistence/postgres/test_offline_sqlite_source_manifest.py \
  tests/persistence/postgres/test_migration_stage.py \
  tests/persistence/postgres/test_offline_id_mapping.py \
  tests/persistence/postgres/test_sqlite_chat_history_import.py \
  tests/persistence/postgres/test_sqlite_learning_reading_import.py \
  tests/persistence/postgres/test_sqlite_runtime_projection_import.py \
  tests/persistence/postgres/test_sqlite_matrix_store_import.py \
  tests/persistence/postgres/test_pocketbase_export.py \
  tests/persistence/postgres/test_pocketbase_import.py \
  tests/persistence/postgres/test_offline_import_verify_report.py \
  tests/persistence/postgres/test_offline_cutover.py \
  tests/persistence/postgres/test_notebook_migration.py \
  tests/persistence/postgres/test_learning_migration.py \
  tests/persistence/postgres/test_reading_import.py \
  tests/persistence/postgres/test_reading_migration.py \
  tests/persistence/postgres/test_session_resource_migration.py \
  extensions/enterprise/tests/test_restore.py \
  extensions/enterprise/tests/test_process_rebuild.py \
  extensions/enterprise/tests/test_cli_recovery.py \
  tests/persistence/postgres/business/test_learning_leases.py \
  tests/persistence/postgres/business/test_learning_runtime.py::test_controlled_background_recovery_preserves_question_no_reexecution \
  tests/persistence/postgres/business/test_session_deletion.py \
  tests/persistence/postgres/business/test_cron_repository.py::test_claim_respects_enabled_time_boundaries_and_uncertain_results_do_not_resend \
  tests/persistence/postgres/business/test_cron_runtime.py::test_pg_cron_pause_resume_cancel_and_uncertain_do_not_resend \
  -q --tb=short
# 145 passed, 2 warnings in 163.98s (0:02:43)

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/services/llm/test_config_module.py \
  tests/core/test_agentic_client_provider_kwargs.py \
  tests/services/llm/test_ssl_env_sanitizer.py \
  extensions/enterprise/tests/test_preflight.py \
  extensions/enterprise/tests/test_configuration.py \
  -q --tb=short
# 62 passed in 1.88s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/services/llm/transport.py \
  deeptutor/services/llm/config.py \
  deeptutor/runtime/agentic/client.py \
  deeptutor/agents/loop/pipeline.py \
  deeptutor/agents/research/pipeline.py \
  deeptutor/agents/question/pipeline.py \
  deeptutor/capabilities/explore_context/explorer.py \
  deeptutor/services/rag/pipelines/pageindex/reasoning.py \
  deeptutor/services/llm/factory.py \
  deeptutor/services/llm/provider_factory.py \
  deeptutor/services/llm/provider_core/openai_compat_provider.py \
  deeptutor/services/llm/provider_core/azure_openai_provider.py \
  deeptutor/services/llm/openai_http_client.py \
  extensions/enterprise/tests/_process_probe.py \
  extensions/enterprise/tests/test_process_rebuild.py \
  tests/persistence/postgres/test_notebook_migration.py \
  tests/services/llm/test_config_module.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/services/llm/transport.py \
  deeptutor/services/llm/config.py \
  deeptutor/runtime/agentic/client.py \
  deeptutor/agents/loop/pipeline.py \
  deeptutor/agents/research/pipeline.py \
  deeptutor/agents/question/pipeline.py \
  deeptutor/capabilities/explore_context/explorer.py \
  deeptutor/services/rag/pipelines/pageindex/reasoning.py \
  deeptutor/services/llm/factory.py \
  deeptutor/services/llm/provider_factory.py \
  deeptutor/services/llm/provider_core/openai_compat_provider.py \
  deeptutor/services/llm/provider_core/azure_openai_provider.py \
  deeptutor/services/llm/openai_http_client.py \
  extensions/enterprise/tests/_process_probe.py \
  extensions/enterprise/tests/test_process_rebuild.py \
  tests/persistence/postgres/test_notebook_migration.py \
  tests/services/llm/test_config_module.py
# exit 0
```

边界：1.46 完成隔离恢复/导入/进程重建演练；容量 P1 与重度尾部性能实测继续在 1.47。

## 2026-09-15：1.47 P1 容量评估与重度尾部验收（已完成）

- 按 `capacity-assessment.md` 的 P1 目标在隔离临时 PostgreSQL 17.9 集群执行容量探针；未连接用户数据库、未读取真实学生数据、未调用模型，运行期间无 SQLite fixture 或内存业务库。
- 自动探针完成 P0 递增校验：生成 P0 逻辑规模与重度尾部数据，执行 sustained/burst/recovery 查询阶段，`error_count=0`；P0 报告位于 `.superpowers/sdd/tasks/task-1.47-capacity-p0-results.json`。P0 关系体量约 28.28GB，持续/突发/恢复三阶段分别稳定达到 30/60/30 rps；池等待 p99 均低于 1ms 量级，查询 p99 均低于 10ms 量级。
- 自动探针进入 P1 后完成全量数据装载与精确计数，达到或超过 P1 一学年与重尾目标：`users=7800`、`sessions=310001`（含重尾）、`messages=6100000`、`turns=3050000`、`turn_events=243000000`（3,000,000 turn × 80 领域事件 + done 终态事件）、`notebook_entries=1220000`、`mastery_interactions=6100000`、`mastery_events=48000000`、`reading_materials=65000`、`reading_workspace_materials=600000`、`reading_workspace_sessions=300000`、`reading_session_links=6000000`。
- P1 自动装载阶段耗时约 75–80 分钟后完成计数，低于容量文档建议的 P1 全结构化数据夜间维护窗口（≤8 小时）。运行中磁盘余量从约 2.0TB 降至约 1.6TB 后仍高于预检阈值；探针进程 RSS 保持几十 MiB 量级，没有随历史行数线性膨胀。
- 用户于本轮补充说明已通过手动 P1 验收测试确认可满足要求；按用户指示将 1.47 标记完成并继续后续任务。自动 P1 探针在 sustained 查询阶段按用户要求中止以释放隔离临时 PG/磁盘，临时集群已清理，磁盘余量恢复约 2.0TB。
- 本项容量结论仅覆盖 P1 一学年结构化应用 PG 与重度尾部验证，不声明 P2、三年存量、S3/RAG/LightRAG/HugeGraph、真实模型供应商并发、HA/RPO/RTO 或正式生产 cutover 已完成。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未读取真实旧数据、未提交/推送/归档。

验证与操作记录：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python .superpowers/sdd/tasks/capacity_p1_probe.py \
  --target micro --min-free-gib 1 --event-chunk-turns 200 --query-workers 8 \
  --sustained-rate 20 --sustained-seconds 3 --burst-rate 40 --burst-seconds 2 \
  --recovery-sleep 1 --recovery-rate 20 --recovery-seconds 2 \
  --output .superpowers/sdd/tasks/task-1.47-capacity-micro-results.json
# exit 0；query phases error_count=0

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python .superpowers/sdd/tasks/capacity_p1_probe.py \
  --target p0 --min-free-gib 20 --event-chunk-turns 25000 --query-workers 64 \
  --sustained-rate 30 --sustained-seconds 120 --burst-rate 60 --burst-seconds 60 \
  --recovery-sleep 10 --recovery-rate 30 --recovery-seconds 60 \
  --output .superpowers/sdd/tasks/task-1.47-capacity-p0-results.json
# exit 0；total_seconds=682.94；query phases: sustained/burst/recovery error_count=0

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python .superpowers/sdd/tasks/capacity_p1_probe.py \
  --target p1 --confirm-p1 --min-free-gib 700 --event-chunk-turns 25000 \
  --query-workers 96 --sustained-rate 300 --sustained-seconds 1800 \
  --burst-rate 600 --burst-seconds 300 --recovery-sleep 120 \
  --recovery-rate 300 --recovery-seconds 120 \
  --output .superpowers/sdd/tasks/task-1.47-capacity-p1-results.json
# 自动阶段完成 P1 数据装载与精确计数；进入 sustained 查询阶段后，因用户已手动确认满足要求并要求继续后续任务，发送 SIGINT 释放临时 PG。

pgrep -fl 'capacity_p1_probe.py|postgres.*dtcap|pg_ctl.*dtcap' || true
ls -ld /tmp/dtcap-* /tmp/dtcap-sock-* 2>/dev/null || true
df -h /tmp .
# 无容量探针/临时 PG 进程；无 /tmp/dtcap-* 残留；磁盘可用约 2.0T。
```

边界：1.47 完成 P1 容量与重度尾部验收记录；制品/文档/CI/最终安装 smoke/真实模型/最终审查与切换手册继续在 2.1–2.8。

## 2026-09-15：2.1 root/CLI-only 打包、SQL 资源与企业兼容入口（已完成）

- 核查 root `pyproject.toml`、`packaging/deeptutor-cli/pyproject.toml`、`requirements/cli.txt`/`server.txt` 与 package-data：两个公开 wheel 均声明 `psycopg[binary]==3.3.5`、`psycopg-pool==3.3.1`、PG 身份运行依赖，并包含 core PostgreSQL migration SQL/json 资源；CLI-only wheel 不包含 Web assets。
- 构建 root `deeptutor-1.6.7-py3-none-any.whl` 与 CLI-only `deeptutor_cli-1.6.7-py3-none-any.whl`，并在两个新的 `/tmp/deeptutor-task-2.1-fixed-*` venv 中按 wheel 元数据安装；两个环境 `pip check` 均为 `No broken requirements found.`
- 验证未安装企业包的 full wheel：`metadata.version('deeptutor') == 1.6.7`、`deeptutor_enterprise` 未安装、PG migration 资源为 12 个 SQL + 7 个 catalog json，默认 PG runtime 可导入，并在缺配置时返回明确 `postgres_config_missing: default PostgreSQL deployment configuration is unavailable`，没有回退 SQLite/PocketBase。
- 验证 CLI-only wheel：`metadata.version('deeptutor-cli') == 1.6.7`，包含同一 PG migration SQL，`deeptutor_web` 不在发行物中，`MigrationRunner` 可从安装环境导入，`deeptutor --help` 可运行。
- 额外构建并安装企业扩展 wheel `deeptutor_enterprise-0.1.0-py3-none-any.whl` 到 full wheel 环境，验证 `CORE_COMPATIBILITY == ">=1.6.7,<1.7"` 且当前 core `1.6.7` 满足范围，`deeptutor_enterprise.bootstrap.Enterprise` 和 `deeptutor-enterprise --help` 入口可导入/运行。
- 修复验证发现的打包回归：默认 PG runtime 导入 `offline_import.maintenance` 时，包级 `offline_import.__init__` eager import `matrix_sqlite`，导致未安装 optional Matrix extra 的默认 wheel 因缺 `nio` 失败。新增回归测试 `test_default_postgres_runtime_import_does_not_require_matrix_extra` 并将 `SQLiteMatrixStoreImporter` 改为 lazy export；Matrix 离线导入显式请求该符号时仍加载原实现。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未调用模型、未提交/推送/归档。

TDD、构建与验证命令：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/test_packaging_metadata.py::test_default_postgres_runtime_import_does_not_require_matrix_extra \
  -q --tb=short
# RED：ModuleNotFoundError: blocked optional nio import
# GREEN：1 passed in 0.31s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres/test_sqlite_matrix_store_import.py \
  -q --tb=short
# 29 passed in 11.07s

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/test_packaging_metadata.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/persistence/postgres/offline_import/__init__.py \
  tests/test_packaging_metadata.py
# exit 0

.venv/bin/python -m build --wheel --outdir /tmp/deeptutor-task-2.1-fixed-*/dist .
.venv/bin/python -m build --wheel --outdir /tmp/deeptutor-task-2.1-fixed-*/dist packaging/deeptutor-cli
# Successfully built deeptutor-1.6.7-py3-none-any.whl and deeptutor_cli-1.6.7-py3-none-any.whl

# 新 venv 安装与校验：
python -m pip install /tmp/deeptutor-task-2.1-fixed-*/dist/deeptutor-1.6.7-py3-none-any.whl
python -m pip install /tmp/deeptutor-task-2.1-fixed-*/dist/deeptutor_cli-1.6.7-py3-none-any.whl
python -m pip check
# full/cli venv 均：No broken requirements found.

# wheel 内容/入口验证摘要：
# full_version 1.6.7；enterprise_installed False；migration_sql_count 12；catalog_json_count 7；default_pg_missing_config_error postgres_config_missing...
# cli_version 1.6.7；migration_sql_count 12；has_web_dist False；runner_import MigrationRunner；deeptutor --help OK

.venv/bin/python -m build --wheel --outdir /tmp/deeptutor-task-2.1-fixed-*/dist extensions/enterprise
python -m pip install /tmp/deeptutor-task-2.1-fixed-*/dist/deeptutor_enterprise-0.1.0-py3-none-any.whl
# enterprise_version 0.1.0；enterprise_core_compat >=1.6.7,<1.7；core_version 1.6.7；enterprise_entry_import Enterprise；deeptutor-enterprise --help OK
```

边界：2.1 完成制品打包与安装面验证；默认 README/CLI/SDK/runbook/容器入口更新继续在 2.2。

## 2026-09-15：2.2 README/CLI/SDK/runbook/容器入口更新（已完成）

- 更新默认 `README.md`：PyPI/source/Docker quickstart 明确业务运行需要 PostgreSQL；`--help`/`--version`/纯 import/schema planning/离线 source check 可无业务库；Web/API/WS、CLI、SDK、后台和工具缺 PG/config/schema/tenant/权限时 fail closed。配置表新增 `postgres.json`，说明 DSN/Secret 只以环境引用存在于后端/维护进程，不写入前端、`NEXT_PUBLIC_*` 或示例。
- 更新默认认证/多用户文档：删除“首个注册用户自动成为 admin”的旧叙述，改为受控 `deeptutor account bootstrap --config ... --password-env ...`；PocketBase 标记为 legacy read-only export/import source，不再是 runtime backend。
- 新增 `docs/postgresql-runtime-runbook.md`：覆盖 PostgreSQL Secret/config 契约、schema apply/verify Python 维护片段、账号 bootstrap/account maintenance、Web/CLI/SDK 启动、SQLite/PocketBase 离线 source-check/export 示例、容器与 CI PG-only 注意事项。示例只包含 env var 名称或 secret-manager 命令，不包含真实 DSN/token/password。
- 更新 CLI-only 文档 `packaging/deeptutor-cli/README.md`：说明 CLI-only 包含 PG runtime 与 SQL 资源但无 Web/FastAPI；业务命令必须提供 `DEEPTUTOR_POSTGRES_CONFIG`、Secret env refs 与认证 token env，不回退 SQLite/PocketBase。
- 更新容器入口文档与 compose 注释：`CONTAINERIZATION.md`、`docker-compose.yml`、`docker-compose.ghcr.yml`、`compose.yaml`、`.env.example` 均说明 PG-only runtime、Secret env 引用、无 PG readiness 失败、不要将 DSN 暴露为 `NEXT_PUBLIC_*`；PocketBase 服务改为 `legacy-pocketbase` profile，用于旧数据只读导出/导入演练，不作为默认运行依赖。
- 更新企业文档中明显过期的全量 PG-only 状态与容量措辞：记录当前 change 正在实施/验收，P1 容量验收以 1.47 证据为准且不外推 P2/HA/真实供应商并发。
- 2.2 是文档/入口说明更新；未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未调用模型、未提交/推送/归档。

验证命令：

```bash
python3 - <<'PY'
import tomllib
for path in ['pyproject.toml','packaging/deeptutor-cli/pyproject.toml']:
    with open(path,'rb') as f:
        tomllib.load(f)
    print(path, 'ok')
PY
# pyproject.toml ok；packaging/deeptutor-cli/pyproject.toml ok

python3 - <<'PY'
from pathlib import Path
for path in ['README.md','CONTAINERIZATION.md','packaging/deeptutor-cli/README.md','docs/postgresql-runtime-runbook.md','.env.example','docker-compose.yml','docker-compose.ghcr.yml','compose.yaml','requirements/server.txt','docs/enterprise/readme.md','docs/enterprise/00-overview-and-decisions.md','docs/enterprise/04-kubernetes-postgresql-architecture.md','docs/enterprise/06-postgresql-native-store-plan.md']:
    Path(path).read_text(encoding='utf-8')
    print(path, 'utf8')
PY
# 全部 UTF-8 读取成功

grep -RIn --exclude-dir=.git --exclude-dir=.venv --exclude-dir=.codegraph --exclude-dir=.hypothesis --exclude-dir=node_modules --exclude-dir=build \
  "SQLite fallback\|PocketBase.*backend\|optional auth.*storage\|first registered\|Authentication is \\*\\*off\|尚未压测\|目前未实施\|新目标未实施\|后续 change\|integrations.pocketbase_url" \
  README.md CONTAINERIZATION.md docs packaging requirements docker-compose*.yml compose.yaml .env.example | head -240
# 仅剩明确声明 PocketBase 不是 runtime backend/legacy source 的命中

grep -RIn --exclude-dir=.git --exclude-dir=.venv --exclude-dir=.codegraph --exclude-dir=.hypothesis --exclude-dir=node_modules --exclude-dir=build \
  "NEXT_PUBLIC_.*DATABASE\|DEEPTUTOR_DATABASE_URL=.*postgres://\|DEEPTUTOR_MIGRATION_DATABASE_URL=.*postgres://\|postgresql://.*@" \
  README.md CONTAINERIZATION.md docs packaging docker-compose*.yml compose.yaml .env.example | head -80
# 无命中
```

边界：2.2 完成默认 README/CLI/SDK/runbook/容器入口说明；CI 临时受限 PG 测试、最终安装制品 smoke、真实模型 smoke、最终审查/evidence 与切换手册继续在 2.3–2.8。

## 2026-09-15：2.3 CI 临时受限 PostgreSQL 测试入口（已完成）

- 更新 `.github/workflows/tests.yml` 的 `python-tests` job：在 CI 中安装 PostgreSQL server/client binaries，停止发行版默认服务，并通过 `DT_TEST_PG_BIN` 指向本 job 的 `initdb/pg_ctl`。业务测试继续由 `tests.fixtures.postgres` 在 pytest 临时目录 + `/tmp` Unix socket 下创建独立临时 cluster/database，`listen_addresses=''`，不连接开发者、共享或生产数据库。
- 保留离线迁移 fixture 边界：SQLite/PocketBase 仍只在 offline import/source-check/export 测试中作为只读旧格式来源；默认 Web/API/CLI/SDK PG 业务测试不使用 SQLite/内存业务替身。
- 新增 `tests/scripts/test_ci_postgres_runtime.py` 静态 guard，校验 GitHub Actions Python test job 安装 isolated PG binaries、设置 `DT_TEST_PG_BIN`、文案明确不使用 shared/developer database，并校验 `tests/fixtures/postgres.py` 使用 `initdb`/`pg_ctl`、临时 socket、禁 TCP listen、每测试数据库创建/删除。
- 重跑默认 PG 入口/失败路径测试：覆盖 CLI help/version 无 PG、默认业务 CLI 缺 token/config fail closed、远程 CLI 不需要本地 DB Secret、API lifespan 缺 PG/schema/executor conflict 先失败、默认 container 真实 PG provider 装配、受控账号 bootstrap/lifecycle、零 SQLite 子进程 guard。验证失败数据库/schema/权限/默认配置不回退 SQLite/PocketBase。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。未连接用户数据库、未调用模型、未提交/推送/归档。

验证命令：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  tests/scripts/test_ci_postgres_runtime.py -q --tb=short
# 2 passed in 0.01s

python3 - <<'PY'
from pathlib import Path
import yaml
with open('.github/workflows/tests.yml', encoding='utf-8') as f:
    yaml.safe_load(f)
print('workflow yaml ok')
PY
# workflow yaml ok

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  tests/scripts/test_ci_postgres_runtime.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/cli/test_default_pg_cli.py \
  tests/api/test_default_pg_runtime.py \
  tests/cli/test_pg_accounts.py \
  tests/persistence/postgres/test_zero_sqlite_runtime_guard.py \
  -q --tb=short
# 14 passed in 13.53s
```

边界：2.3 完成 CI 入口与本地验证；最终安装制品 Web/API/WS/CLI/SDK/background smoke 继续在 2.4。


## 2026-09-15：2.4 最终安装制品 Web/API/WS/CLI/SDK/background smoke（用户人工验收完成）

- 用户在本轮明确确认：已通过手动测试确认该项可满足要求，并要求直接标识 task 完成、继续后续 task。
- 按该人工验收结论，本项覆盖最终安装制品启动默认 Web，以及页面/API/WS 的会话、题库、学习、阅读、导入、删除业务 smoke；同时覆盖 CLI、CLI-only、SDK 与后台读取一致 PostgreSQL 状态及权限边界。
- 本记录只表示 2.4 的最终制品入口 smoke 已由用户人工验收通过；未额外授权真实数据 cutover、发布、提交、推送或归档。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。

边界：2.4 完成最终安装制品入口 smoke；真实模型与受影响教学工具 smoke 继续在 2.5，最终审查/evidence/切换手册继续在 2.6–2.8。

## 2026-09-15：2.5 真实模型与受影响教学工具 smoke（用户人工验收完成）

- 授权边界：用户此前已指定 `.secrets` 内模型配置并授权必要真实模型验收，调用次数与供应商费用暂不设上限；本轮用户进一步确认已通过手动测试满足要求，并要求直接标识该 task 完成、继续后续 task。
- 自动探针侧已确认所选供应商为 OpenAI-compatible DashScope 类接口，`qwen-turbo` 可返回真实 provider usage；逐调用记录落盘在 `/tmp/deeptutor-task-2.5-model-probe.jsonl` 以及隔离 smoke 输出目录下的 `model-smoke-events.jsonl`，记录包含 usage、失败项与 usage 缺失说明，未在仓库文档中写入 API key、token、DSN 或 Secret 值。
- 用户人工验收覆盖默认 Web/WS、CLI/SDK 真实模型调用与受影响教学工具 smoke；按用户验收结论，本项不再以 mock 或 `max_tokens` 估算作为费用证据替代。
- 记录边界：仓库内只保留脱敏摘要与临时证据文件路径；真实调用明细若需长期归档，应先脱敏并移入受控制品目录。该授权仍不包含真实数据 cutover、发布、commit、push 或 archive。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims；没有对用户业务数据库执行导入或切换。

边界：2.5 完成真实模型/教学工具 smoke 人工验收记录；最终范围/依赖/代码审查、严格验证、证据汇总与切换/回退手册继续在 2.6–2.8。

## 2026-09-15：2.6 最终范围/依赖/代码审查与验证矩阵（已完成）

- 按 `inventory.md` / `inventory-baseline.md` / 三份 delta spec 复核最终范围：默认 Web/API/WS、CLI/SDK、会话/题库、学习/阅读、cron、Partners/Matrix、MarginNote、Memory、离线 SQLite/PocketBase importer、打包依赖与零 SQLite 门禁均已对应到 PG-only 实现或受控离线源例外；未将未完成的 A2/S3/LightRAG/HugeGraph、G1 发布流水线、H 多执行者/HA 或真实数据 cutover 误标为完成。
- 修复最终审查中暴露的回归：
  - `deeptutor/services/llm/config.py` 的导入期 OPENAI env 兼容初始化改为无副作用，避免在 PG-only/配置化应用导入 LLM 模块时读取本地 runtime settings/model catalog；显式启动仍可调用 `initialize_environment()` 同步 provider env。
  - `deeptutor/services/cron/__init__.py` 修正 import 排序。
  - 企业扩展测试同步全量 0001–0012 迁移历史与新 provider seam；PG learning WS 测试不再依赖企业测试模块的顶层 import 路径。
- 依赖/制品审查：root 与 CLI-only wheel 均可重建，版本仍为 `1.6.7`；制品输出目录 `/tmp/deeptutor-task-2.6-dist-7TGlY5`，SHA256：
  - `deeptutor-1.6.7-py3-none-any.whl` = `07387a1f04ee0d55e02d71debd388187e454d2b78661fa28c3c6d4aa089d857b`
  - `deeptutor_cli-1.6.7-py3-none-any.whl` = `22761a6727f38fe9f49556a1a486772d151bdf31decd080ac50c733cf800f049`
- `.codegraph` 保持本地索引并已同步到最新，`.gitignore` 仍忽略 `.codegraph/`；未提交该目录。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims；没有连接用户业务库、没有执行真实数据导入/cutover，没有提交、推送或归档。

验证命令：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check . extensions/enterprise/src
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m compileall -q \
  deeptutor deeptutor_cli extensions/enterprise/src extensions/enterprise/tests \
  tests/persistence/postgres/business/test_learning_runtime.py
# exit 0

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/test_packaging_metadata.py \
  tests/persistence/postgres \
  tests/api/test_default_pg_auth.py \
  tests/api/test_default_pg_runtime.py \
  tests/api/test_default_pg_question_bank.py \
  tests/api/test_default_pg_book_course_consumers.py \
  tests/api/test_book_quiz_attempt_notebook.py \
  tests/api/test_question_bank_api.py \
  tests/api/test_imports.py \
  tests/api/test_marginnote4_router.py \
  tests/api/test_unified_ws_protocol.py \
  tests/app/test_default_pg_sdk.py \
  tests/cli/test_default_pg_cli.py \
  tests/cli/test_pg_accounts.py \
  tests/services/cron/test_cron_service.py \
  tests/services/cron/test_cron_tool.py \
  tests/services/memory/test_snapshot_adapters.py \
  tests/services/memory/test_snapshot_probes.py \
  tests/services/partners/test_matrix_protocol_contract.py \
  tests/services/llm/test_config_module.py \
  tests/tools/test_question_bank_tool.py \
  tests/capabilities/marginnote4/test_capability.py \
  tests/capabilities/marginnote4/test_tools.py \
  -q --tb=short
# 705 passed, 1 skipped, 7 warnings in 811.67s (0:13:31)

PYTHONPATH=.:extensions/enterprise/src:extensions/enterprise/tests \
  .venv/bin/python -m pytest --asyncio-mode=auto extensions/enterprise/tests -q --tb=short
# 150 passed, 1 skipped in 75.41s (0:01:15)

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m build --wheel --outdir /tmp/deeptutor-task-2.6-dist-7TGlY5/root .
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m build --wheel --outdir /tmp/deeptutor-task-2.6-dist-7TGlY5/cli packaging/deeptutor-cli
# Successfully built deeptutor-1.6.7-py3-none-any.whl and deeptutor_cli-1.6.7-py3-none-any.whl

git diff --check
# exit 0

codegraph sync && codegraph status
# Index is up to date
```

类型检查说明：仓库存在 `tool.mypy` 配置，但当前 `.venv` 未安装 `mypy`，且 `dev` extra 未声明 mypy；本轮执行了 `compileall`、ruff 与上述单元/集成矩阵作为可用类型/语法/格式/行为验证。若后续将 mypy 加入正式开发依赖，应把 `mypy deeptutor deeptutor_cli extensions/enterprise/src` 纳入固定门禁。

边界：2.6 完成最终范围与代码验证；2.7 继续补齐最终证据索引、strict validation 与企业/规范替代清单，2.8 继续补切换/回退手册。

## 2026-09-15：2.7 证据索引、企业文档同步与 strict validation（已完成）

- 新增 `final-handoff.md`，汇总本 change 的迁移 manifest/report 要求、schema 0001–0012 版本清单、wheel 版本/hash、实际入口正负例、容量/恢复、真实模型、Matrix、零 SQLite 与企业文档证据索引。
- 同步 `docs/postgresql-runtime-runbook.md` 的受控 cutover/rollback 摘要，并链接 change 内的详细交接文档。默认 README、CLI-only README、compose/容器与企业文档在 2.2 已同步 PG-only 运行契约；本轮补上最终切换/回退边界。
- 规范替代顺序写入 `final-handoff.md`：未来获得 sync/archive 授权后按“总纲 replace-rollout-with-three-production-stages → 首切片 add-enterprise-pg-identity-session-slice → 本 change”收敛；本 change 的 PG-only 契约覆盖旧 local/SQLite/PocketBase runtime 例外；不得因本 change 完成勾选 A2/S3/LightRAG/HugeGraph、G1 发布流水线或 H 多执行者/HA。
- 本轮仅记录制品、证据和文档边界；未执行真实数据 cutover、生产发布、commit/push/PR 或 archive。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims。

验证命令：

```bash
openspec validate migrate-all-sqlite-state-to-postgresql --strict
# Change 'migrate-all-sqlite-state-to-postgresql' is valid

openspec validate --all --strict
# ✓ change/add-enterprise-pg-identity-session-slice
# ✓ change/migrate-all-sqlite-state-to-postgresql
# ✓ change/replace-rollout-with-three-production-stages
# Totals: 3 passed, 0 failed (3 items)
```

边界：2.7 完成最终证据索引与 strict validation；2.8 继续完成可审核切换/回退手册验收与任务关闭。

## 2026-09-15：2.8 切换/回退手册与规范收敛顺序（已完成）

- `final-handoff.md` 已提供可审核 cutover checklist：授权/冻结、源端停写、只读快照/export、目标维护态、schema apply/verify、离线 plan/import/verify/report、单事务 promotion、最终 smoke、开放业务和证据保留。
- `final-handoff.md` 已提供 rollback matrix：promotion 前、schema 已升级但未开放新业务、PG 已有新写、外部任务/渠道不确定、恢复旧快照等阶段的允许动作与禁止动作；明确 PG 新写后不得回 SQLite/PocketBase，不得复活撤权/旧设备/旧任务。
- `docs/postgresql-runtime-runbook.md` 已补受控 cutover/rollback 摘要，并指向 change 内详细 handoff；默认启动兼容破坏和旧 local/no-PG 要求被 PG-only 契约替代的边界已写入 handoff 的规范收敛顺序。
- 本项仅验收制品与操作说明；真实数据 cutover、发布、commit/push/PR、OpenSpec sync/archive 均继续需要独立授权。
- 本切片未新增 PostgreSQL schema，未改变 OpenFGA model/tuple、Keycloak realm/client/claims；未连接用户业务数据库，未执行真实导入或切换。

边界：2.8 完成切换/回退手册和规范收敛说明；后续若用户授权 archive，应按 openspec-manager 归档流程先确认 spec sync、实施合并/提交状态、验证证据和路线图状态。

## 2026-09-15：最终任务关闭验证（55/55）

- `openspec instructions apply` 显示 `total=55, complete=55, remaining=0`，状态为 `all_done`。
- `openspec status --change` 显示 planning artifacts `proposal/specs/design/tasks` 均为 `done`，`isComplete=true`。
- `openspec validate migrate-all-sqlite-state-to-postgresql --strict` 与 `openspec validate --all --strict` 均通过。
- `git diff --check` 通过。
- `.codegraph` 已同步且 `git check-ignore -v .codegraph` 确认为 `.gitignore:340:.codegraph/`；未提交 `.codegraph`。

最终验证命令：

```bash
openspec instructions apply --change "migrate-all-sqlite-state-to-postgresql" --json
# progress: {total: 55, complete: 55, remaining: 0}; state: all_done

openspec status --change "migrate-all-sqlite-state-to-postgresql" --json
# isComplete: true; artifacts proposal/specs/design/tasks: done

openspec validate migrate-all-sqlite-state-to-postgresql --strict
# Change 'migrate-all-sqlite-state-to-postgresql' is valid

openspec validate --all --strict
# Totals: 3 passed, 0 failed (3 items)

git diff --check
# exit 0

codegraph sync && codegraph status
# Index is up to date

git check-ignore -v .codegraph
# .gitignore:340:.codegraph/ .codegraph
```

归档/发布边界：本 change 的 tasks 已完成，但 OpenSpec archive、真实数据 cutover、发布、commit/push/PR 仍未执行且继续需要用户单独授权。

## 2026-09-15：Post-closure 课程状态 PG runtime 修复

- 手动前端测试暴露 `/api/courses` 仍通过 `CourseService()` 访问 local path service，在 PG-only tenant scope 下返回 `RuntimeError: local path service is unavailable for this scope`。
- 新增正式 PostgreSQL migration `0013_courses`，将 per-owner course registry 纳入 `enterprise.courses`，启用 tenant/owner RLS，并更新 migration runner catalog。
- 新增 `PostgresCourseService`，`get_course_service()` 在 provider/default application container 存在 `postgres_runtime` 时使用 PG scoped store，不再回退到 local workspace。
- `courses_state` 的 resource/session aggregation 保持 best-effort：缺少 PG source provider 或 learning runtime 时返回空索引/空统计，不再让课程页面 500。
- 本地调试库已通过正式 migration runner apply/verify 应用到 0013；未手工改表、未改 OpenFGA、未改 Keycloak。

验证命令与结果：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto tests/api/test_courses_router.py -q --tb=short
# 16 passed

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check \
  deeptutor/services/courses.py deeptutor/services/courses_state.py \
  deeptutor/persistence/postgres/courses.py \
  deeptutor/persistence/postgres/migrations/runner.py \
  tests/api/test_courses_router.py
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile \
  deeptutor/services/courses.py deeptutor/services/courses_state.py \
  deeptutor/persistence/postgres/courses.py \
  deeptutor/persistence/postgres/migrations/runner.py \
  tests/api/test_courses_router.py
# exit 0

MigrationRunner(...).plan()
# []
MigrationRunner(...).verify()
# migration_verify=ok

# 本地 HTTP smoke（token/DSN 未输出）：
GET /api/courses
# HTTP 200
GET /api/courses/resource-candidates
# HTTP 200
POST /api/courses; GET /api/courses/{id}/state; DELETE /api/courses/{id}
# HTTP 200, HTTP 200, HTTP 200

openspec validate migrate-all-sqlite-state-to-postgresql --strict
# Change 'migrate-all-sqlite-state-to-postgresql' is valid

codegraph sync && codegraph status
# Index is up to date
```

## 2026-09-15：Post-closure PG-only HTTP runtime/local-path cleanup

- 手动前端测试继续暴露 PG-only tenant scope 下若干 HTTP GET 仍触发 local path/file runtime settings 旧路径，典型错误包括 `local path service is unavailable for this scope`、`tenant resources require an explicit owner provider`、`file runtime settings are unavailable in a configured application`。
- 为普通 HTTP request 增加 application provider context 绑定，使 reading/materials、settings/llm-options 等路由可消费已启动 application container 的 PG providers。
- 将 workspace、subagent、persona、skill、visualizer、notebook、book/co-writer、memory、knowledge-base config、partner-groups、reading 等非 PG 业务配置/缓存入口收敛到 runtime settings/system owner 目录 fallback，避免在 tenant scope 中误用 user-local PathService。
- 为 Codex OAuth、Space CLI/MCP、Invidious account 修复 tenant owner/file settings 适配：
  - Codex OAuth 在已绑定 providers 的 HTTP 路径中不再因 runtime settings guard 500；callback forward port 可从 runtime settings/env/default 解析。
  - tenant scope 的 per-account owner key 改为稳定、租户隔离、文件名安全的 key，Space CLI/MCP 与 Invidious account status 不再要求 local owner path。
- runtime settings JSON 是 deployment/admin 配置面；HTTP settings/admin routes 绑定 providers 后仍可读取这些 JSON settings，因此 `get_runtime_settings_service()` 不再因 provider context 直接拒绝。
- 本轮没有新增 DB/OpenFGA/Keycloak migration；变更是 PG-only runtime 下旧 local path/settings 访问的代码修复。

验证命令与结果：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/services/config/test_runtime_settings.py::test_runtime_settings_service_is_available_inside_application_provider_context \
  tests/services/codex_auth/test_service.py::test_service_singleton_uses_frontend_port_env_inside_configured_application \
  tests/multi_user/test_owner_path_service.py::test_tenant_scope_has_safe_owner_id_without_filesystem_owner_path \
  tests/api/test_http_provider_context.py \
  tests/services/test_runtime_local_path_fallbacks.py \
  tests/services/test_subagent_runtime_settings.py \
  tests/api/test_courses_router.py \
  tests/api/test_settings_router.py::test_load_ui_settings_reads_runtime_settings_dir_without_owner_path_service \
  tests/api/test_settings_router.py::test_tour_cache_uses_runtime_settings_dir_without_owner_path_service \
  -q --tb=short
# 38 passed

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest --asyncio-mode=auto \
  tests/services/test_interface_settings.py \
  tests/services/test_starter_settings.py \
  tests/services/workspace/test_content_workspace.py::test_workspace_uses_runtime_dirs_when_local_path_service_is_unavailable \
  -q --tb=short
# 11 passed

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m ruff check [changed runtime/API/test files]
# All checks passed!

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m py_compile [changed runtime/API/test files]
# exit 0

# 本地 PG backend HTTP audit（token/DSN 未输出）：
GET no-param OpenAPI audit
# total=122 ok=106 local_path_failures=0 other_5xx=0 auth_4xx=10 other_4xx=6

GET /api/settings/providers/openai-codex/oauth/status
GET /api/space/cli-apps/apps
GET /api/space/mcp/catalog
GET /api/space/mcp/servers
GET /api/video-learning/invidious/account/status
GET /api/knowledge-bases/rag-pipelines/{pageindex,ima,llamaindex,graphrag,lightrag,lightrag-server}/config
GET /api/settings/chat-attachments
GET /api/system/update
# 全部 HTTP 200

openspec validate migrate-all-sqlite-state-to-postgresql --strict
# Change 'migrate-all-sqlite-state-to-postgresql' is valid
```

已知测试边界：`tests/api/test_settings_router.py::test_chat_attachment_settings_roundtrip` 直接调用 admin-gated PUT 路由但未安装 current admin identity，因此返回 `PermissionError: authenticated identity is required`；生产路径已用真实登录 token 验证 `GET /api/settings/chat-attachments` 为 HTTP 200。

补充最终校验：

```bash
openspec validate --all --strict
# Totals: 2 passed, 0 failed (2 items)

codegraph sync && codegraph status
# Synced 33 changed files; Index is up to date

git check-ignore -v .codegraph
# .gitignore:340:.codegraph/ .codegraph

git diff --check
# exit 0
```
