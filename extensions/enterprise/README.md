# DeepTutor 企业身份与 PostgreSQL 会话切片

`deeptutor-enterprise` 是独立、显式装配的企业扩展：固定部署租户、本地身份、个人纯文本 `chat` 与 PostgreSQL 会话持久化，复用 core 的 HTTP / WebSocket / Python SDK 契约。它不是默认 local 模式的数据库开关，也不是完整企业产品。

后续范围已调整为[默认 Web/CLI/SDK 全量 PG-only](../../openspec/changes/migrate-all-sqlite-state-to-postgresql/proposal.md)，取消 local/SQLite 兼容并下沉通用 PG 到 core；该 change 尚未实施。本文安装/验收记录仍对应已完成的首切片，不能据此声称默认入口已切 PG。

**状态：本子切片工作区实现与隔离验证已完成，未合并/发布；不代表完整 A1、M1 或生产 G1 已通过。** 真实模型、全进程、恢复和 core 回归以对应实际验收证据为准，不能由包构建成功或本文示例推断完成。范围依据 [本切片 proposal](../../openspec/changes/add-enterprise-pg-identity-session-slice/proposal.md)。

## 1. 兼容性与安装

| 项目 | 本轮实际验证版本 / 约束 |
| --- | --- |
| 企业包 | `deeptutor-enterprise==0.1.0` |
| core | `deeptutor==1.6.7`；声明范围 `>=1.6.7,<1.7` |
| 应用 hook | 必须存在 `deeptutor.core.providers.APPLICATION_HOOK_VERSION == 1` |
| Python | 实测 CPython `3.14.7`；包声明 `>=3.11,<3.15`，不表示全范围均已验证 |
| PostgreSQL | 原生 `17.9`；当前 schema 版本 `1`（迁移 `0001_identity_sessions`） |
| PG driver / pool | `psycopg[binary]==3.3.5` / `psycopg-pool==3.3.1` |
| 测试 | `pytest==9.1.1` / `pytest-asyncio==1.4.0` |
| 构建 | 测试 venv 的 `build==1.6.1`、`wheel==0.47.0`；本轮 PEP 517 **隔离构建**实际解析 `setuptools==84.0.0`、`wheel==0.48.0` |

版本号相同不保证包含本切片所需 hook：须安装本仓库对应 core 构建，缺 hook 或版本不兼容会在企业装配时失败。默认 local 安装不需要企业包或 PG driver。

从仓库根目录，在专用 Python 环境安装源码及直接测试依赖：

```bash
python -m pip install -e '.[server]' -e 'extensions/enterprise[test]' \
  -r extensions/enterprise/requirements-test.lock
python -c 'from deeptutor.core.providers import APPLICATION_HOOK_VERSION; assert APPLICATION_HOOK_VERSION == 1'
python -m build extensions/enterprise --outdir /tmp/deeptutor-enterprise-dist
```

部署构建产物时，先安装经过验证的 core wheel（及 server 依赖），再安装 `deeptutor_enterprise-0.1.0-py3-none-any.whl`。当前包包含迁移 SQL。不要用未包含 hook 的公开同版本 core 替代已验证构建。

[`requirements-test.lock`](requirements-test.lock) **仅固定列出的直接依赖**，不是全部传递依赖、跨平台或 hash 锁，也不约束 PEP 517 的隔离构建依赖。不要把测试 venv 的 wheel 与隔离构建版本混为一谈；重新构建仍需记录实际解析版本。

## 2. 部署配置、Secret 与最小权限

复制 [`deployment.example.json`](deployment.example.json) 为受控部署配置，例如 `deployment.json`，替换假租户 UUID、模型标识和 `*.example` 地址。样例不含真实 Secret 或主机，不能直接提供服务。

- 一个部署固定一个 `tenant_id`，只接受配置中的精确 HTTPS `origins`；客户端不能以 header、query 或请求体改租户。`resource` 是执行登记标识，不是多执行者隔离开关。
- JSON 只承载非敏感只读配置与 `env:VAR` 引用。由 Secret 管理器或受控进程环境注入值；不从项目根 `.env` 加载，不把 DSN、密码、token、模型 key 放入配置、命令参数、URL、日志或版本库。
- `DT_DATABASE_DSN`：目标库的单数据库用户 DSN。当前 G1/test-cn 模式下迁移可使用相同的 `DT_MIGRATION_DSN`/`PG_MIGRATOR_DSN`，该用户应只拥有本目标库及其对象，且不得是 superuser、createdb、createrole 或 bypassrls。生产网络认证、数据库 TLS、证书和 Secret 分发须由部署侧配置，不能复用测试的 trust 认证。
- `DT_SIGNING_KEY`：至少 32 字符的独立签名 Secret；`DT_BOOTSTRAP_SECRET`：至少 32 字符的一次性初始化 Secret；`DT_AUTH_EPOCH`：非空、由快照之外的可信系统维护的认证世代，不能随 PG 备份一起回退。密码要求 UTF-8 长度 12–72 字节。
- `DT_MODEL_API_KEY` 只在模型调用配置中解析。模型 `base_url` 必须为不含凭证、query、fragment 的 HTTPS 地址；`provider` 仅 `openai` 或 `anthropic`。每项模型必须显式设置 `allowed_roles` 或 `allowed_user_ids`，二者按“或”授权；`tenant_admin` 没有模型权限旁路。
- `allowed_tools` 只允许 `ask_user`，也可设 `[]`；仅装配 `chat`，不加载动态插件。模型/工具配置没有写入或“保存设置”API，修改部署配置后须受控重启。`max_tokens` 是发送给供应商的输出参数，未必限制额外 reasoning tokens；超时/重试/轮数也不是货币硬上限。标题、摘要同样可能计费，付费测试需供应商侧预算/思考额度并记录缺失用量，不能按 0 处理。

### 数据库角色与迁移

由数据库管理员为**专用目标库**准备一个单数据库用户及认证。当前迁移不再创建固定运行角色（例如 `dt_enterprise_app`），也不再执行数据库级 GRANT/REVOKE 来表达业务权限；首次迁移身份只需要能在目标库内创建/变更 DeepTutor schema 与对象。该用户可以是目标库、schema、表和 sequence 的 owner，但不得拥有跨库/集群管理能力（superuser、createdb、createrole、bypassrls）。

运行连接检查会拒绝高权限角色，以及能经继承、`SET ROLE` 或可管理成员关系到达高权限角色的路径；不再因为当前用户是目标库或对象 owner 而拒绝。权限边界由 DeepTutor 应用层鉴权、scope、owner guard、审计与受控入口负责；租户表保留 `ENABLE ROW LEVEL SECURITY` 与 policy 作为目录漂移和未来角色拆分的防线，但不使用 `FORCE ROW LEVEL SECURITY` 作为当前单用户模型的主要隔离机制。`schema_history` 和执行登记表不是租户正文表。

下列命令仅应在核实目标、备份与维护窗口后由获准操作者执行；本文不要求对已有共享库试运行：

```bash
deeptutor-enterprise --config deployment.json schema plan --dsn-env DT_DATABASE_DSN
deeptutor-enterprise --config deployment.json schema apply --dsn-env DT_DATABASE_DSN
deeptutor-enterprise --config deployment.json schema verify --dsn-env DT_DATABASE_DSN
```

`plan` 列出待执行版本并核对历史 checksum；`apply` 在迁移互斥与事务内执行 DDL 和历史登记，失败整体回滚；`verify` 要求没有待执行版本，并核对实际列、关键约束/FK、唯一 active-turn 索引及 RLS/policy，不能只伪造历史表通过。漂移会拒绝，不会自动接管或修复。**应用启动只 `verify`，从不自动 `apply` 或回退 SQLite。**

### 先初始化，后接流量

注入 `DT_INITIAL_PASSWORD` 与前述 Secret 后：

```bash
deeptutor-enterprise --config deployment.json bootstrap \
  --username initial-admin --password-env DT_INITIAL_PASSWORD
deeptutor-enterprise --config deployment.json serve --port 8002
```

`bootstrap` 使用受限应用 DSN，创建固定 tenant 与首位 `tenant_admin`，同一已完成初始化可幂等重试，不覆盖密码或把普通账号升级。初始化成功后，从部署配置移除 `bootstrap_secret` 并撤去进程中的一次性 Secret。未初始化、被禁用/隔离、世代不匹配或不兼容 schema 均不能启动接流量。

`serve` 只监听 `127.0.0.1`，固定 `workers=1`。外部 HTTPS/WSS 由受信反向代理终止；代理必须正确转发 WebSocket、Origin 和认证信息，不能把应用原始 HTTP 端口暴露为公网绕过路径。不要使用普通 `deeptutor serve/start` 代替企业组合入口。

## 3. HTTP、WebSocket、SDK 与 CLI

### 认证与 HTTP 会话

- `POST /api/auth/login`：JSON `username` / `password`，浏览器请求需配置允许的 `Origin`。返回本人信息；token 在 `dt_token` cookie 中，**JSON 不返回 token**。
- `GET /api/auth/status`：匿名只返回最小认证状态；有效 cookie 或 bearer 可查询本人身份。
- `POST /api/auth/logout`：撤销当前认证会话。`dt_token` 为 `HttpOnly; Secure; SameSite=lax`；`dt_csrf` 为 `Secure; SameSite=lax`。
- Cookie 模式的非只读请求（登录除外）需要允许的 `Origin` 及 `X-CSRF-Token`，其值须与 `dt_csrf` cookie 匹配。受控非浏览器客户端可用 `Authorization: Bearer …`；不要把 bearer 放到 URL。
- 退出、账号禁用、密码变化及会话撤销后，旧 token 和已有 WS 后续操作不再获得授权。未知或他人资源不能被请求者接管；认证失败、拒绝、资源不存在和冲突按入口返回安全错误，不回显凭证。

已纳入 HTTP 路由：

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/sessions` | 本人会话列表，`limit` / `offset` |
| `GET /api/sessions/{session_id}` | 会话与消息历史 |
| `PATCH /api/sessions/{session_id}` | `{"title":"新标题"}` |
| `PATCH /api/sessions/{session_id}/organization` | `pinned`、`archived`、同 owner 的 `parent_session_id`，仅 `session_kind="chat"` |
| `PUT /api/sessions/{session_id}/branch-selection` | `{"selected_branches":{"父消息整数ID":子消息整数ID}}` |
| `GET /api/sessions/{session_id}/messages/{message_id}/events` | 当前 owner 的消息 trace / 事件 |
| `DELETE /api/sessions/{session_id}/messages/{message_id}` | 删除对应轮次；运行中拒绝，删除共享 user 消息会删除它的所有回答分支 |
| `DELETE /api/sessions/{session_id}` | 阻止新派发、取消活动 turn 后删除；有外部资源依赖则前置拒绝 |

摘要、版本、会话偏好与父子消息链保存在 PG。历史/trace 对 provider 私有 metadata 脱敏，并对展示内容截断；trace 可用 `after_seq` / `limit` 分页，不能靠更换 message ID 读取他人事件。

重命名、组织信息修改、分支选择这 **3 个修改接口**接受可选 `If-Match: 7`（也接受引号包裹的整数）。值来自会话响应的 `version`，须为正整数；陈旧版本返回 `409`，格式错误返回 `400`。未提供时保留兼容的非条件更新语义。冲突后重新读取再决定修改，不盲目覆盖。**这不是所有请求通用的 ETag/条件删除协议；当前 SDK 和远程 CLI 也未暴露该参数。**

受控 HTTP 客户端的 cookie 登录与条件重命名示例（密码由环境注入，不打印 cookie）：

```python
import os

import httpx


async def rename_owned_session(session_id, title):
    origin = "https://school.example"
    async with httpx.AsyncClient(
        base_url=origin, follow_redirects=False, trust_env=False
    ) as client:
        login = await client.post("/api/auth/login", headers={"Origin": origin}, json={
            "username": os.environ["DT_USERNAME"],
            "password": os.environ["DT_PASSWORD"],
        })
        login.raise_for_status()
        path = "/api/sessions/" + session_id
        current = await client.get(path)
        current.raise_for_status()
        response = await client.patch(path, json={"title": title}, headers={
            "Origin": origin,
            "X-CSRF-Token": client.cookies["dt_csrf"],
            "If-Match": str(current.json()["version"]),
        })
        response.raise_for_status()  # 409 时重新读会话，由调用方决定如何合并。
        return response.json()
```

### WebSocket v2

连接 `wss://school.example/api/v1/ws`，提供有效 cookie 或受控客户端的 Authorization header；**两种方式均须精确允许的 `Origin`**。每条命令包含 `protocol_version: "2.0"`。以下为独立示例，后续 ID 必须换成服务实际返回值：

```json
{"protocol_version":"2.0","type":"start_turn","content":"解释二分之一","operation_id":"example-start-1"}
```

```json
{"protocol_version":"2.0","type":"start_turn","session_id":"返回的会话ID","content":"再举一个例子","operation_id":"example-start-2"}
```

```json
{"protocol_version":"2.0","type":"regenerate","session_id":"返回的会话ID"}
```

```json
{"protocol_version":"2.0","type":"subscribe_turn","turn_id":"返回的turn ID","after_seq":0}
{"protocol_version":"2.0","type":"resume_from","turn_id":"返回的turn ID","seq":12}
{"protocol_version":"2.0","type":"check_active_turn","session_id":"返回的会话ID"}
{"protocol_version":"2.0","type":"submit_user_reply","turn_id":"返回的turn ID","text":"我的选择","command_id":"example-reply-1"}
{"protocol_version":"2.0","type":"cancel_turn","turn_id":"返回的turn ID","command_id":"example-cancel-1"}
```

最后一段是逐行独立消息，不是一个 JSON 数组。也支持 `subscribe_session`、`unsubscribe` 和 `ping`。事件保留单调 `seq`、turn/session 标识和原信封；最终 assistant 消息、终态、`done` 在同一 PG 事务提交，随后才发布。继续会话沿当前分支取上下文；regenerate 保留旧回答分支。`parent_message_id` 必须是同会话整数 ID；显式 `null` 表示新 root，而非隐式接到当前叶子。

**两类重试不可混用：**

- `operation_id` 只用于 `start_turn`（包括在既有会话发起下一轮），SDK `start_turn` 和 CLI `session run` 可传递；WS `regenerate` 不提供该字段。作用域为 tenant + owner。登记先于派发，同 key 同规范请求复用原 turn，不重复模型调用；同 key 异内容冲突。没有 key 的旧客户端仍是每次新请求，不获得幂等保证。
- operation 保留期为登记后 **30 天**。相关内容删除后只留指纹、到期时间等最小 tombstone，清除正文与 session/turn 引用；保留期内重放返回 `deleted`，不复活已删内容。到期后可清理/重新登记，不承诺永久去重；当前按该 key 访问时清理到期记录，而非定时全表清扫。
- `submit_user_reply` 与 `cancel_turn` 必须有 `command_id`。同 turn、同 key、同种类/内容重试返回原接受结果，不重新排队；异种类/内容冲突。reply 仅接受当前 `waiting_input`，旧 reply 的 ACK 重试不能回答下一次 `ask_user`。每次新的逻辑回复/取消使用新 key；重发同命令则保留原 key。命令记录跟随 turn/session 删除，不使用 operation 的 30 天规则。
- 重连优先用已知 turn ID 与游标订阅。崩溃恢复不会因保留了 operation/command 自动重放模型或工具。

### Python SDK：使用已有企业实例

在**同一服务进程、已完成 `Enterprise.start()` 的实例**中借用认证上下文，不要另建默认 `DeepTutorApp()` 或在在线服务旁再启动一个企业执行者：

```python
import uuid


async def chat_in_existing_process(enterprise, token):
    # token 来自受控登录；只在上下文有效期内使用此 SDK。
    async with enterprise.sdk(token) as sdk:
        session, turn = await sdk.start_turn({
            "content": "解释二分之一",
            "operation_id": str(uuid.uuid4()),
        })
        async for event in sdk.stream_turn(turn["id"]):
            # 在这里处理事件，勿记录凭证或未经授权的正文。
            if event.get("type") == "done":
                break
        return await sdk.get_session(session["id"])
```

SDK 还支持 `list_sessions`、`get_active_turn`、`rename_session`、`delete_session`、`regenerate_last_turn`、`submit_user_reply`、`cancel_turn`；每次操作重新校验身份与 owner。当前 facade 的 reply/cancel 不暴露 `command_id`，不能把 WS 的持久命令去重保证套到 SDK 重试上。远程客户端使用 HTTPS/WSS，而不是尝试把此进程内 facade 连到服务器。

### 受控 CLI

CLI 没有 `login` 子命令。由受控登录客户端从 HTTPS 登录响应的 `dt_token` cookie 取得 token，安全注入 `DT_AUTH_TOKEN`，不输出到日志或放入命令行。账号运维直接使用配置中的 PG；会话命令只连接**已运行**企业服务，不再获取执行者租约：

```bash
deeptutor-enterprise --config deployment.json account create \
  --auth-token-env DT_AUTH_TOKEN --username learner --password-env DT_NEW_PASSWORD
deeptutor-enterprise --config deployment.json account password \
  --auth-token-env DT_AUTH_TOKEN --user-id USER_ID --password-env DT_NEW_PASSWORD
deeptutor-enterprise --config deployment.json account disable \
  --auth-token-env DT_AUTH_TOKEN --user-id USER_ID
deeptutor-enterprise --config deployment.json account enable \
  --auth-token-env DT_AUTH_TOKEN --user-id USER_ID
deeptutor-enterprise --config deployment.json account revoke \
  --auth-token-env DT_AUTH_TOKEN --user-id USER_ID

deeptutor-enterprise --config deployment.json session list \
  --server https://school.example --auth-token-env DT_AUTH_TOKEN
deeptutor-enterprise --config deployment.json session run \
  --server https://school.example --auth-token-env DT_AUTH_TOKEN \
  --text '解释二分之一' --operation-id example-cli-start-1
deeptutor-enterprise --config deployment.json session show \
  --server https://school.example --auth-token-env DT_AUTH_TOKEN --session-id SESSION_ID
deeptutor-enterprise --config deployment.json session rename \
  --server https://school.example --auth-token-env DT_AUTH_TOKEN \
  --session-id SESSION_ID --text '分数练习'
deeptutor-enterprise --config deployment.json session cancel \
  --server https://school.example --auth-token-env DT_AUTH_TOKEN --turn-id TURN_ID
deeptutor-enterprise --config deployment.json session delete \
  --server https://school.example --auth-token-env DT_AUTH_TOKEN --session-id SESSION_ID
```

普通用户只能改自己的密码；账号创建、启停、撤销等管理操作要求 `tenant_admin`，仍不赋予他人会话权限。`session run` 可加 `--session-id` 继续；遇到当前 `ask_user` 从标准输入读取回复，并生成 command ID。远程 HTTP/WSS 拒绝重定向，避免 token 被转发。仅原生隔离测试可显式使用 `--allow-loopback-http` 与字面 loopback IP，不能用于普通 HTTP 主机或生产。

## 4. 单执行者、停止与恢复

这不是 HA：只支持一个 backend worker / 执行进程，进程内事件与命令协调，不支持多 pod 扩容。PG advisory lock 与持久执行登记共同阻止第二执行者；换 `resource` 不会绕过数据库级互斥。PG/执行权丢失会停止新派发和提交；不按心跳超时自动接管。

### 普通重启或进程异常退出

1. 关闭入口并停止旧进程，等待正常清理。正常关闭会登记 stopped；不要在旧执行者仍可能运行时启动替代者。
2. 若异常退出留下 active 登记，先在进程管理/主机层**确认旧进程确实停止**，从受控执行登记取得准确 `execution_id`。建立同部署的 `maintenance.json`，仅将 `maintenance` 设为 `true`。
3. 执行人工确认（仍会拒绝持有锁的旧执行者）：

   ```bash
   deeptutor-enterprise --config maintenance.json confirm-stopped \
     --execution-id EXECUTION_UUID --old-process-confirmed-stopped
   ```

4. 使用正常配置启动。旧 `running` / `waiting_input` 等未终态 turn 会以 `failed`、`failure_code="worker_lost"` 和可重试标记完成，不自动续跑 agent。用户确认后须发起**新的 operation**，旧 operation 重放只读原结果。

命令里的确认标志不能代替外部停机核实；PG 锁也不能证明所有外部模型请求已无副作用。

### PG 快照恢复后的身份隔离

恢复不是普通重启。备份可能含已退出、被禁用或已改密之前的旧凭证；只恢复库再换签名 key，不能保证旧密码不复活。

1. 阻断登录/聊天入口，确认旧执行进程停止。在隔离的恢复目标检查备份及 schema 兼容性；具体备份/恢复命令由数据库运维流程提供，**不要直接用本文操作共享库**。
2. 在不随 PG 快照回退的 Secret 系统生成**新的** `DT_AUTH_EPOCH`，注入本次恢复维护进程。保持 `maintenance=true`；tenant/resource 与恢复目标一致。新世代未完成隔离前普通服务会拒绝启动。
3. 核验身份后按顺序执行：

   ```bash
   deeptutor-enterprise --config maintenance.json recovery quarantine \
     --old-process-confirmed-stopped
   deeptutor-enterprise --config maintenance.json recovery reset-account \
     --old-process-confirmed-stopped --user-id VERIFIED_ADMIN_ID \
     --password-env DT_RESET_ADMIN_PASSWORD --enable
   deeptutor-enterprise --config maintenance.json recovery reset-account \
     --old-process-confirmed-stopped --user-id VERIFIED_USER_ID \
     --password-env DT_RESET_USER_PASSWORD
   deeptutor-enterprise --config maintenance.json recovery release \
     --old-process-confirmed-stopped
   ```

`quarantine` 要求新外置世代且无运行执行者，禁用登录和全部账号、递增身份版本、撤销认证会话，并删除快照恢复出的所有旧密码 hash；相同隔离状态可幂等重试。`reset-account` 只为已人工核实的账号写入新密码，**默认仍禁用**，需 `--enable` 才启用。`release` 要求至少一个已重置且启用的管理员，否则拒绝；未重置/未启用用户不会因此复活。

4. 保持**新世代**，把正常服务配置恢复 `maintenance=false` 后启动，再检查身份、历史、事件引用和中断 turn。用户须用新密码登录；旧 token 和旧密码不得重新接受。不要恢复旧世代、重导旧 credential 表或重新 bootstrap 来绕过隔离。

当前只支持 schema `1` 的兼容构建回退与同版本恢复，没有 down migration。未知版本、checksum 或实际目录漂移会拒绝启动；不能切到 SQLite 作为降级。此切片不承诺 RPO/RTO，也未交付 PG / S3 / 检索系统成套灾备或完整生产恢复验收。

## 5. 明确未支持的领域

未装配的依赖会明确拒绝，不以空列表、假保存或本地文件回退冒充完成：

- KB/RAG、教材检索、LightRAG/HugeGraph、S3、附件与持久文件；
- memory、notebook、学习/课程/题库/阅读/掌握路径状态，以及 `course_id` 关联；
- 动态 skills/personas/plugins、高级 capability 与 `ask_user` 以外工具、运行中任意 user-input 中断；
- 可编辑模型目录/settings/grants、完整审计查询、原 local admin/Plugin 管理接口；
- EduPlus2/外部身份、TMS/OMS 完整管理、多租户生产入口、K8s/CI 发布、多执行者/HA。

未交付域与完整 M1 要求仍是后续责任，不能因为本切片拒绝它们而视为生产门禁满足。

## 6. 验证入口与安全边界

从仓库根目录，在专用测试环境中执行：

```bash
# 指向本机原生 PG 17.9 的可执行目录，不是现有服务 DSN。
export DT_TEST_PG_BIN=/opt/pgsql/bin
PYTHONPATH="$PWD" python -m pytest -c extensions/enterprise/pytest.ini \
  extensions/enterprise/tests --ignore=extensions/enterprise/tests/test_real_model.py
```

fixture 使用 `initdb` / `pg_ctl` 启动临时 PG 集群，只监听临时 Unix socket、禁用 TCP，每 case 创建独立临时库，结束后清理。测试会创建仅限该库的非特权 owner 用户（无 superuser/createdb/createrole/bypassrls）并以同一用户覆盖迁移、verify 与应用路径；**不连接共享或开发者已有数据库**。缺原生 PG 明确失败，不跳过为 mock。

覆盖入口包括 `test_persistence.py`、`test_sessions.py`、`test_identity.py`、`test_application.py`、`test_flows.py`、`test_denials.py`、`test_isolation_matrix.py`、`test_versions.py`、`test_cli*.py`、`test_executor.py`、`test_restore.py` 与 `test_process_rebuild.py`。确定性入口测试使用受控模型替身，但数据库、鉴权、事务和入口是真实路径；不能用这些测试代替真实模型验收。

`test_real_model.py` 是可能计费的单独验收，默认需 `DT_RUN_REAL_MODEL=1` 才启用；普通测试命令还显式排除了该文件。仅在另获授权、准备受控凭证和预算后按该验收流程运行，不要为执行普通测试读取 `.secrets` 或开启真实模型。最终放行还需对应 core/local 回归、全进程无本地权威路径、恢复和模型费用证据；本文不宣称这些剩余验收已完成。
