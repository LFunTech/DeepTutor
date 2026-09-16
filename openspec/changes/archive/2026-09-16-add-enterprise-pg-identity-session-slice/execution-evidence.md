# A1 身份与 PG 会话子切片实施证据

日期：2026-09-13。基于 core `b96589df4e3b027f1c4b8b86b3b647c4de1cd6a0` 的工作区变更；用户已批准实施。未 commit/push/部署或归档，保留既有 `.gitignore`、`AGENTS.md`、企业文档迁移及总纲修改。

**范围仅本 proposal 的 34 项子任务。** 不表示完整 A1、M1、G1 或多执行者 G-H 通过；其余 A1、S3/RAG、TMS/OMS、外部身份、CI/K8s 继续由总纲门禁阻断。

## 1. 入口—实现—持久化与旁路清单

| 入口/层 | 实际路径 | 身份/持久化/拒绝边界 |
| --- | --- | --- |
| 启动 | `deeptutor_enterprise.bootstrap.Enterprise` → 通用 `create_api_application` / `ApplicationContainer` | core 版本 + hook 1、只读配置、Secret、schema、固定 tenant/epoch 预检；不导入 `api.main` 的 local lifespan，不自动 DDL |
| HTTP auth | 显式 auth router → `IdentityService` | PG tenant/user/credential/auth session，签名仅进程 Secret；无公共注册/首用户抢注 |
| HTTP sessions | 原 `api/routers/sessions.py` 的 8 类白名单路由 → 显式 StoreProvider | PG owner guard；branch/message delete 无 SQLite；纯会话删除不调用 LearningStore/AttachmentStore |
| WS | 原 `/api/v1/ws` v2 → `GuardedTurns` → 原 `TurnApplicationService` / runtime | 原始字段缺省语义、当前身份重验、Origin、tenant+owner namespace；command 重放不再次投递 |
| SDK | `Enterprise.sdk(token)` → 原 `DeepTutorApp(container=...)` | 使用同一 runtime/Store；ContextVar 随上下文清理，保留对象也不能回退 notebook 工厂 |
| CLI 会话 | `session --server ... --auth-token-env ...` → 认证 HTTPS/WSS | 操作现有执行者，不另起第二实例；禁止凭证 URL/重定向/任意 tenant；回环 HTTP 仅显式测试选择 |
| CLI 运维 | schema/bootstrap/account/confirm-stopped/recovery | 独立迁移身份与受限应用身份；Secret 只引用 env；恢复必须维护、停止确认及外置新 epoch |
| 实际聊天 | 原 `TurnEngine → ChatOrchestrator → ChatCapability → AgenticChatPipeline → AgentLoop` | 非复制教学循环；只装配授权 chat/ask_user、只读内置 prompts |
| 标题/摘要/模型 | 原标题服务/ContextBuilder/BaseAgent → scoped LLMConfig + LLMTransportConfig | 不读 runtime settings/grants JSON，不发现 local OAuth，不写环境变量；TLS 验证、禁止环境代理，SDK ambient 路由/header 冲突提前拒绝 |
| 后台恢复 | 受限 executor 锁/持久登记 → PG owner 枚举 → finalize failed | 不读本地账号列表；未确认旧执行者停止不接管；不自动重跑模型、工具或旧 reply |
| 数据 | `PostgresSessionStore` / `Database.transaction(TenantScope)` | 同一连接显式事务绑定 tenant/user，RLS/FORCE + 复合 FK/owner；提交成功后才发布事件 |

未交付域包括可编辑 settings/Grant、附件/S3、KB/LightRAG/HugeGraph、动态 skill/persona、memory/notebook、题库/学习/课程/阅读、partners/cron、Plugin、其他 WS、原 auth/admin/TMS/OMS。企业 router 不挂载这些入口；非空相关参数在写 session/turn 与调用模型前拒绝，不返回假空列表/保存成功。core 仍可独立按 local 配置运行，不反向 import 企业包。

## 2. 固定契约与版本

- 企业包 `0.1.0`；core 实测 `1.6.7`，范围 `>=1.6.7,<1.7` 且 `APPLICATION_HOOK_VERSION=1`。CPython 实测 `3.14.7`；未宣称所有声明 Python 版本均实测。
- 原生隔离 PostgreSQL `17.9`；`psycopg[binary] 3.3.5`、`psycopg-pool 3.3.1`。具体安装见 [企业 README](../../../extensions/enterprise/README.md) 与直接依赖锁。
- 自有应用迁移 runner，schema `1`：历史 SHA-256、事务互斥/全回滚、实际 catalog（列/约束/FK/active 索引/RLS/policy）校验，不只信历史行。后续新迁移须同步应用侧预期 catalog。未引入或声称 Flyway/Alembic 已执行。
- 固定 tenant UUID、内部 user opaque text、原 `unified_*` / `turn_*` 字符串 ID、整数 message ID。Scope/cache key 包含 tenant+owner；同名同 ID 双租户的真实 PG/入口测试通过。
- 表覆盖 tenants/users/local_credentials/auth_sessions/audit/sessions/messages/turns/turn_events/operations/turn_commands/executor_state 与 schema_history；未空建检索/外部身份领域表。
- 普通业务使用非 owner/superuser/BYPASSRLS/CREATEROLE/CREATEDB 角色；也拒绝 session_user 高权和继承/SET ROLE/ADMIN 成员路径。运行过程不临时提权。
- `dt_token` 绑定 `tid/sub/sid/ver/epoch/iss/aud/iat/exp`；PG 不存原 token，密码 bcrypt hash。禁用、改密、撤销/退出实际阻断已有 token/WS；tenant_admin 无他人个人会话旁路。
- start 的 operation ID 范围为 tenant+owner，保留 30 天；删除留下指纹/到期时间 tombstone，不复活记录。regenerate 不承诺 operation ID；reply/cancel 使用单独 command ID，保存指纹和最初 waiting 状态版本。
- 三个 HTTP 会话修改入口支持可选整数 `If-Match`；陈旧版本 409，不把它包装为已实现全站 ETag/条件删除。未传时保留既有兼容行为。

## 3. 故障、并发与审查闭环

均先观察对应失败/真实复现，再增加实现并重跑：

- 导入/默认 container、文件身份与 notebook 回退、模型 SDK 隐式 settings/CA/header 发现、摘要复制丢 transport。
- PG 迁移重放/并发/真实 SQL 中断全回滚、内容与实际 schema 漂移、受限角色 DDL/成员链、缺 scope/取消/连接池复用。
- Bootstrap 重放不改密码/提权，冲突与幂等操作审计；认证/Origin/CSRF、限流与 FastAPI validation 输入脱敏。
- 审查确认并修复：取消健康探针不应 fence 全实例；删除共享 user 消息须删除其全部回答/trace；旧 reply command 重试不可消费下一问；CLI cancel 必须连已有执行者；SDK 退出上下文不得切 local notebook。
- 真实进程探针发现并修复：WS `model_dump` 填默认 `parent_message_id=None` 导致普通续聊丢历史。现保留 `exclude_unset=True`，模型请求明确包含上一助手回答。
- 最终独立审查发现并修复：`Authorization: Basic ...` 不能绕过实际 cookie 认证的 CSRF；构造历史期间切分支不能让模型上下文 A 与新 user 父节点 B 不一致。当前 turn 冻结读到的 parent/None；显式 root 和 regenerate 保持兼容。
- 标题写 PG 失败不吞错/假完成；生成期间并发手动改名由条件 UPDATE 保留用户标题。单调事件/唯一 done、finalize 事务、cancel/完成竞争、删除/新派发互斥与 operation tombstone 已验证。

## 4. 本机隔离与实际验证命令

没有读取/修改开发者已有 PG 或集群。`tests/conftest.py` 使用 `/opt/pgsql/bin/initdb` / `pg_ctl` 创建临时集群，只监听 `/tmp` Unix socket、无 TCP；每 case 独立数据库，结束 drop/stop。CLI 网络测试另起 `127.0.0.1` 随机端口 uvicorn；不是外部共享服务。

本轮专用 `/tmp/deeptutor-enterprise-venv`，从已有 `.venv` 读取已安装 core 依赖，不全局 pip：

```bash
export PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages"
PY=/tmp/deeptutor-enterprise-venv/bin/python
$PY -m pytest -c extensions/enterprise/pytest.ini extensions/enterprise/tests -q \
  --ignore=extensions/enterprise/tests/test_real_model.py
$PY -m pytest tests/services/session tests/app tests/cli tests/multi_user tests/runtime \
  tests/services/config tests/services/llm tests/agents/chat tests/agents/test_base_agent_binding.py \
  tests/api/test_auth_contextvar.py tests/api/test_auth_logout_cookie.py \
  tests/api/test_session_organization.py tests/api/test_sessions_trace.py \
  tests/api/test_sessions_truncation.py tests/api/test_unified_ws_protocol.py \
  tests/api/test_unified_ws_turn_runtime.py \
  --ignore=tests/services/session/test_capability_routing.py -q -rs
$PY -m pytest tests/services/session/test_capability_routing.py -q
```

`test_capability_routing.py` 单独进程执行，避免它既有未 undo 的 `MonkeyPatch` 污染后续真实 runtime 测试；不是略过。上述大分组首轮为 **1547 passed、4 skipped**，单独文件 **4 passed**。企业首轮 **124 passed**，其后增加并发标题/分支/CSRF 等回归；最终计数见下方最终验证记录。

### 新进程与恢复实测

`test_process_rebuild.py` 启动两个全新 Python 解释器与不同 scratch：在 import 前安装 audit hook，禁止本地 data/.secrets 访问和 SQLite connect。只在外部 HTTP 层模拟 OpenAI SSE，真实模型 SDK、provider、标题/摘要、原 chat/ask_user、HTTP/WS/SDK、PG 全运行。第一进程完成聊天/摘要/分支/reply/cancel/delete 后带 running+waiting 退出；第二进程证实未确认不能接管，再在父进程确认 PID 已结束后受控恢复两 turn 为 failed。历史不丢、operation 不重跑、旧 reply 不投递，模型恢复调用 **0 次**、本地权威 I/O **0 次**。

`test_restore.py` 实际 `pg_dump` / `pg_restore`：备份后改密、撤销/禁用，再恢复旧快照；维护期推进外置 epoch、撤销认证会话、删除旧 hash、未知账号保持禁用。仅核验并重置的管理员可 release，旧/中间密码及旧 token 不复活，历史/事件引用保留。CLI recovery 的维护/停止确认负例另有真实 PG 测试。

仅验证本应用 schema 1 的受控恢复；未宣称完整 RPO/RTO、S3/检索联合恢复或 HA 验收。回退须停写并用兼容 schema 的 core+扩展，或经授权恢复；不能切 SQLite 丢弃 PG 新数据。

## 5. 真实模型验收与费用边界

用户授权从 `.secrets` 获取测试参数，仅读取指定模型 key/host，密钥只绑定进程 `SMOKE_KEY`，不输出/写入制品。以 `qwen-plus` 运行合成教学内容：HTTP 登录/历史、WS chat/有历史的继续/regenerate、SDK ask_user 真实工具暂停与回复。没有替身模型、演示 capability 或把纯文本回答当成交互。

```bash
DT_RUN_REAL_MODEL=1 PYTHONPATH="$PWD:$PWD/.venv/lib/python3.14/site-packages" \
  /tmp/deeptutor-enterprise-venv/bin/python -m pytest \
  -c extensions/enterprise/pytest.ini extensions/enterprise/tests/test_real_model.py -q --tb=short
```

最终实跑 **1 passed，63.53 秒**；4 个 turn 均 completed，7 次实际模型 HTTP（包括标题），实际观察到 **15,045 tokens = 10,205 prompt + 4,840 completion**，含供应商报告的 reasoning tokens。实际续聊请求含上一助手答复。原 `cost_summary` 信封保留，但不含全部标题费，不能把其 USD 估算当供应商账单。

证据：[最终逐调用/PG事件记录](evidence/real-model-smoke.json)、[全轮次调用记录与缺失说明](evidence/real-model-run-log.json)。首轮仅连通通过、后发现缺省字段丢历史，故 [首轮记录](evidence/real-model-first-pass.json) 不冒充续聊验收；第二轮业务通过但全部 usage 断言失败且未在断言前落盘，其完整用量无法准确回溯，明确不按 0 计。

测试限制为 4 turn、每 turn 最多 3 轮、最多 14 个实际 HTTP 调用、聊天请求 `max_tokens=512` / 标题 `80`、SDK 重试 0；**这些不是货币或含全部推理 token 的硬上限**。实测标题 `max_tokens=80` 仍有 1,854 reasoning tokens；供应商的混合思考模式可有额外思考用量，后续须用供应商侧预算/明确思考参数控制，参见 [阿里云思考模式说明](https://www.alibabacloud.com/help/en/model-studio/deep-thinking)。本次已停止计费调用，不因格式/文档检查重复调用模型。

## 6. 任务覆盖索引

| tasks | 主要实现/验证证据 |
| --- | --- |
| 1.1–1.3 | 本清单、scope/config/preflight/persistence/session 协议测试、直接依赖锁 |
| 1.4 | 独立 pyproject/wheel/SQL 资源、hook/版本预检、local 分组回归 |
| 1.5–1.8 | `test_persistence.py`、`test_sessions.py`：真实 PG/角色/catalog/RLS/FK/事件与取消回滚 |
| 1.9–1.12 | `test_identity.py`、`test_application.py`、`test_denials.py`、`test_cli.py` |
| 1.13–1.17 | `test_core_bindings.py`、`test_preflight.py`、原 configured runtime 测试、CLI TCP 测试 |
| 1.18–1.24 | sessions/flows/isolation_matrix/versions/branch_consistency、原 HTTP/WS/local 回归 |
| 1.25–1.27 | 双问 command 重放、真实 ask_user、cancel/删除/版本竞争/trace/tombstone、CLI TCP 测试 |
| 1.28–1.29 | executor/process_rebuild/configured 授权监视与无虚假终态测试 |
| 1.30 | `test_isolation_matrix.py` 双租户同 ID 与三用户全入口；CLI TCP owner/token 负例 |
| 1.31 | 新解释器 audit 全链路 + 实际 SDK HTTP 探针；本清单未适配域与架构静态检查 |
| 1.32 | 显式真实模型 smoke 与上述脱敏证据/费用边界 |
| 1.33 | 实际 process crash/scratch 重建、pg_dump/pg_restore、CLI recovery 门禁 |
| 1.34 | 最终分组回归、包构建/安装、Ruff、diff/依赖边界/OpenSpec strict、独立审查闭环 |

更细 core TDD 与回归见 [runtime 证据](execution-evidence-runtime.md)。总纲 1.1/1.3/1.7 仍包含其它 A1 领域；本子切片不替代这些汇总任务或把总纲 checkbox 勾为完成。

## 7. 最终验证记录

- 企业独立测试（真实 PG，显式排除计费测试）：**133 passed，59.32 秒**。
- core/local 大分组：**1547 passed，4 skipped，8 warnings，78.10 秒**；单独 capability routing：**4 passed，2 warnings，0.57 秒**。
- 4 个 skip：3 个既有 Redis 集成/压力测试缺 `DEEPTUTOR_TEST_REDIS_URL`，1 个 Linux `/proc` fallback 测试在 macOS 不适用。Redis 不在本子切片单执行 PG 运行路径，未把 skip 称为通过。
- 实际计费 smoke：**1 passed，63.53 秒**；详见第 5 节与逐调用记录，不叠加存在重叠的 agent 分组数字。
- 77 个受影响/新增 Python 文件 Ruff check 与 format check 通过；`git diff --check` 通过。静态检查 core 无企业反向依赖、默认 core 依赖未增加 PG；交付文件未包含授权模型 key 明文。
- 独立构建 **sdist + wheel 成功**；重新安装 wheel 到 `/tmp/deeptutor-enterprise-installed` 后 import、core hook 1 与 packaged migration SQL 校验通过。PEP 517 隔离解析 `setuptools 84.0.0` / `wheel 0.48.0`，构建日志 `/tmp/deeptutor-enterprise-build.log`。
- 独立审查提出的问题均已修复并有专项真实 PG/TDD 回归；最终分支竞争额外 5 项也在上述 133 个企业测试内。
- OpenSpec change-scoped strict 与 `openspec validate --all --strict` 均通过，全量 **2 changes passed、0 failed**；apply 状态为 **34/34、all_done**。文档相对链接 **71 个目标均存在**；总纲 90 个 checkbox 未由本次子切片实施改动。
- 尚未发布、合并、归档；不宣称剩余 A1/G1 或 HA 完成。
