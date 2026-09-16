# Core 显式文本运行环境执行证据

记录日期：2026-09-13。本文只记录本次 core 运行时子任务的实现和本地确定性验证，不代表整个企业切片、A1/G1 或生产发布通过；不修改 tasks 的勾选状态。

## 实现边界与接口

- `TurnRuntimeManager(..., turn_environment=provider)` 显式启用；不提供该参数仍执行原 local 流程。
- `PreparedTurnEnvironment` 位于 `deeptutor.services.session.turns.environment`，字段为 `payload`、私有 `llm_config`、`chat_params`、`allowed_tools`，以及可选 `summary_agent_params`。
- Provider 提供 `prepare_request(payload, *, session=None)` 和 `authorize_request(action, *, session_id=None, turn_id=None)`。配置对象不进入持久化 payload、事件或消息 metadata。
- 执行继续经过 `TurnRuntimeManager → TurnEngine → ChatOrchestrator → ChatCapability → AgenticChatPipeline/AgentLoop`。没有企业包反向 import、全局 monkeypatch、复制教学循环或生产假模型。
- `TurnRuntimeContext` 显式携带模型、聊天参数、工具 registry 和资源能力集合；空资源集合不探测/创建本地 settings、memory、notebook、workspace、动态 skill/persona、附件、学习或插件工具服务。
- 本次只接通 `chat` 和显式授权的 `ask_user`。资源、其他工具/能力及任意 per-turn config 在 session/turn 写入或模型调用前拒绝。

## 行为

1. 原始规范请求经 `begin_request(payload, operation_id=...)` 原子登记，再创建实际模型任务；provider 补充的默认配置不改变原请求指纹。只为 **start 请求**提供可选 operation ID；`regenerate_last_turn` 的 overrides 携带 `operation_id` 会明确抛出 `ValueError`，不会静默忽略。
2. 新建/继续与选定祖先链上下文复用原 `ContextBuilder`；长历史仍走原预算/摘要逻辑，显式摘要参数避免读取 local agent settings。provider 私有响应状态保留用于模型上下文，不使用展示 trace 截断代替模型历史。
3. Regenerate 保留旧 assistant 分支，不重复写用户消息，新 assistant 关联原 user。写入/选定 user 后通过 Store 的 `link_turn_user_message` 建立 turn 关联。
4. `ask_user` 使用原工具和原暂停逻辑，只有 waiting turn 能接受一次 reply；重复回复不排队进入下一轮。
5. 普通事件先持久化再发布；最终 assistant、终态和 done 交给 Store 的 `finalize_turn` 原子仲裁。没有提交成功就不发布 done；重复 cancel 返回原 cancelled 结果，cancel/完成竞争不追加第二个终态。
6. 原标题服务继续调用受控模型。因为严格 Store 不允许终态后追加事件，首次标题和 `session_meta` 在最终提交前生成/持久化，done 保持最后。无需读取 task model catalog。
7. Subscribe/resume 只返回游标之后真实已提交的事件，显式环境不使用 local 的 synthesized done 补偿。每条公开事件重验身份。
8. 每个执行拥有独立的 1 秒授权监视任务，继承启动任务身份 ContextVar。等待回复或模型长时间无输出时，身份撤销也会主动停止执行并记录受控 failed 中断；DB/执行权不可确认则停止模型、不虚构持久化成功，留给受控恢复。结束时取消并等待监视任务，无后台任务遗留。
9. 显式环境的 Orchestrator/AgentLoop/摘要错误日志和错误事件使用脱敏异常文本；正常调用仍保留原 `result.metadata.cost_summary` 信封。

## 本子任务修改文件

新增：

- `deeptutor/services/session/turns/environment.py`
- `deeptutor/services/session/turns/configured.py`
- `tests/services/session/test_configured_turn_runtime.py`
- 本证据文件

修改：

- `deeptutor/core/context.py`
- `deeptutor/runtime/turn_engine.py`
- `deeptutor/runtime/orchestrator.py`
- `deeptutor/agents/chat/capability.py`
- `deeptutor/agents/loop/pipeline.py`
- `deeptutor/agents/loop/agent_loop.py`
- `deeptutor/agents/base_agent.py`
- `deeptutor/services/session/context_builder.py`
- `deeptutor/services/session/_turn_runtime_shared.py`
- `deeptutor/services/session/turn_runtime.py`
- `deeptutor/services/session/turns/lifecycle.py`
- `deeptutor/services/session/turns/request_preparer.py`
- `deeptutor/services/session/turns/executor.py`
- `deeptutor/services/session/turns/title_service.py`

企业 provider/PG Store、身份、HTTP/WS/application/container、配置副作用修复由同切片其他子任务负责，不计入上述文件清单。

## 实际验证

### TDD 与测试边界

最初新增 20 项 runtime 测试；后续 SDK transport 修复补充 17 项，当前共 37 项。已观察 RED 的主要缺口包括：缺少 environment 构造接口、重复 reply 被接受、身份撤销后仍可读/控制、regenerate 进入 local 资源路径、缺少标题和预算摘要、错误日志泄漏 credential sentinel、terminal 游标制造新 done、regenerate 静默接受 operation ID、waiting/无输出执行不响应撤销；相应实现后重跑 GREEN。

测试运行真实 TurnEngine、Orchestrator、ChatCapability、AgentLoop、ask_user、ContextBuilder、标题服务和 SQLite 读写。仅外部模型替换为确定性流；测试环境对象提供受控配置/授权与故障状态。测试 Store 是明确临时 SQLite，它的终态适配器用于验证 runtime 的提交调用顺序和失败/竞争处理，**不用于证明 PostgreSQL 原子事务、RLS 或真实数据库故障恢复**。

独立新进程测试在 import 前安装文件 I/O audit hook，运行新建、继续、标题、关闭，拒绝任何 `/data/` 权威路径访问；本测试通过，不是源码 grep 或本地服务 mock。

### 新增运行时测试

```sh
PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages:$PWD" \
/tmp/deeptutor-enterprise-venv/bin/python -m pytest \
  tests/services/session/test_configured_turn_runtime.py \
  -q -o addopts='' -W default --tb=short
```

最近独立执行：**37 passed，6.28 秒**（最初为 20 项）。

### 分组 core/local 回归

```sh
PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages:$PWD" \
/tmp/deeptutor-enterprise-venv/bin/python -m pytest \
  tests/services/session/test_configured_turn_runtime.py \
  tests/services/session/test_turn_runtime.py \
  tests/services/session/test_context_builder.py \
  tests/services/session/test_regenerate.py \
  tests/services/session/test_turn_runtime_subscribe.py \
  tests/services/session/test_provider_response_state.py \
  tests/agents/chat \
  tests/runtime/test_orchestrator.py \
  tests/agents/test_base_agent_binding.py \
  -q -o addopts='' -W default
```

SDK transport 补充后最近执行：**343 passed, 3 warnings，9.43 秒**（原组为 326 项）。3 个警告均来自既有 selection tutor/course 兼容测试使用旧 `config` runtime 字段产生的 `DeprecationWarning`。

对本子任务全部 Python 修改运行 Ruff check/format，check 通过；限定本子任务路径的 `git diff --check` 通过。未 commit、push、迁移用户数据库或创建 worktree。

### 运行环境与已知测试限制

- 最初仅使用隔离 venv 跑 local regenerate 回归，因缺少 `defusedxml` 出现 6 个导入失败；使用许可的现有 `.venv` site-packages 作为 `PYTHONPATH` 后，上述分组全部通过。没有全局安装依赖。
- 一次直接运行整个 `tests/services/session tests/agents/chat` 被中止：既有 `tests/services/session/test_capability_routing.py` 使用自行创建但未 undo 的 `pytest.MonkeyPatch()`，将 `ChatOrchestrator` 等替换泄漏给后续测试，导致新增真实内核测试失败/等待。没有把该整目录运行算作通过，也未擅自修改无关既有测试；最终采用上面的无污染分组命令。
- 本 core 子任务没有执行真实远端模型、企业 PG/HTTP/WS/SDK/CLI 全入口、HA 或生产环境验收。真实 PG 事务/权限/恢复，以及企业组合入口和真实模型 smoke 的结果必须见本切片相应独立证据；不能由上述 core/local 测试推定通过。


## 真实 SDK transport 后续修复（同日）

### 定位与实现

真实端点 smoke 由集成负责人执行，发现配置运行时的 agentic client 构造仍读取 local `load_system_settings()`。本子任务不运行真实外部模型，也不读取 `.secrets`，使用原 SDK 和仅替换外部 HTTP 的测试复核。

- 新增不可变 `deeptutor.services.llm.transport.LLMTransportConfig`：`request_timeout_seconds=90`、`connect_timeout_seconds=10`、`max_retries=0`，超时限制 `(0,600]`，SDK 重试限制 `0..2`。它固定 TLS 验证、`trust_env=False`、不自动跟随重定向，且不访问本地 settings、不修改进程环境。这里是 SDK HTTP 超时/重试参数，不是整个 turn 或所有上层重试的总预算。
- `LLMConfig` / `LLMClientConfig.transport` 为可选字段；`None` 保留 local 原配置行为。`PreparedTurnEnvironment` 未收到 transport 时复制 LLMConfig 并装配安全默认，不修改调用者原配置。
- agentic、OpenAI chat/responses、Anthropic 及 services provider factory 使用同一显式 transport；两个连接池 key 纳入 transport，避免变更超时/重试却重用旧客户端。Anthropic 通过 SDK 公开 `Timeout` 类型兼容 httpx / httpx2，不依赖 SDK 私有模块。
- OpenAI provider 显式模式禁止 `_setup_env`；显式 SDK 必须有 key 和 endpoint，不允许 OAuth 本地凭证后端。摘要 `factory._resolve_call_config` 的完整显式字段分支保留匹配 scoped 配置中的 transport，避免摘要丢失配置重新读 local。
- SDK 会强行合并的 `OPENAI_CUSTOM_HEADERS`、`OPENAI_ORG_ID`、`OPENAI_PROJECT_ID`、`ANTHROPIC_CUSTOM_HEADERS`、`ANTHROPIC_AUTH_TOKEN` 等冲突按相应 backend 明确拒绝，错误不带值；不采用 SDK 私有字段改写或请求内修改环境。公开 `validate_environment(backend=...)` 支持提前验证。企业 `Configuration` 在初始化和每次 `resolve_model` 之前校验，失败发生在 turn 登记之前。显式 key/endpoint 的同名环境 Secret 引用不受此限制。
- 标题的 PG 写失败在 configured 模式重抛，让 turn 失败而非继续提交 completed，日志不输出 raw exception；local 保留原 warning/fallback 行为。

### 本轮新增/扩展文件

新增 `deeptutor/services/llm/transport.py`。扩展：

- `deeptutor/services/llm/config.py`
- `deeptutor/services/llm/openai_http_client.py`
- `deeptutor/services/llm/provider_factory.py`
- `deeptutor/services/llm/factory.py`
- `deeptutor/services/llm/provider_core/openai_compat_provider.py`
- `deeptutor/services/llm/provider_core/anthropic_provider.py`
- `deeptutor/services/llm/provider_core/azure_openai_provider.py`
- `deeptutor/runtime/agentic/client.py`
- `deeptutor/agents/loop/pipeline.py`
- `deeptutor/services/session/turns/environment.py`
- `deeptutor/services/session/turns/title_service.py`
- `extensions/enterprise/src/deeptutor_enterprise/configuration.py`：仅 transport 部署字段/构造/校验，其余企业配置实现由组合根子任务负责。
- 原 `tests/services/session/test_configured_turn_runtime.py` 及本文件。

### TDD / 确定性证据

- 6 个不 mock client factory 的 SDK 构造测试先 RED：agentic 必经 local settings；services OpenAI 同样回退设置；Anthropic 默认信任陈旧 CA 环境。修复后 6 项 GREEN，确认 90/10/0 参数及不改环境。
- 标题写失败先 RED：原代码仍提交 completed，日志暴露 credential sentinel；修复后失败关闭且不泄漏。
- 原 HTTP SDK 的 summary→chat→title 测试先发现摘要 transport 丢失，摘要失败退化（RED），补充原 factory 复制字段后 GREEN。测试不替换 SDK/client factory；仅外部模型 HTTP transport 产出确定性响应。每条 chat/summary/title 请求必须带 `stream_options.include_usage=True`，usage 使用 `choices=[]` 的独立末帧，原聊天 UsageTracker 信封准确记录 18 个合成 token。
- 新进程从 import 前安装文件 I/O audit hook，实际 SDK 工厂覆盖 OpenAI chat/responses/Anthropic；完整 OpenAI 短历史和长历史 turn 覆盖摘要、聊天、标题、关闭。拒绝 `/data/` 与本地 SDK 凭证路径，检查零命中；无 SDK 工厂替身、无真实网络。
- 5 种 ambient 冲突字段先 RED（构造被允许），后 GREEN（脱敏拒绝）。开发机已有其他 SDK 身份环境会按该契约拒绝；测试 fixture 清除相应环境，仅供测试隔离并在结束后恢复，没有修改实际部署环境。

### 实际回归命令

除上面 343 项 core/local 分组，还执行：

```sh
PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages:$PWD" \
/tmp/deeptutor-enterprise-venv/bin/python -m pytest \
  tests/services/llm/test_openai_http_client.py \
  tests/services/llm/test_ssl_env_sanitizer.py \
  tests/services/llm/test_provider_pool.py \
  tests/services/llm/test_config_module.py \
  tests/services/llm/test_factory_provider_exec.py \
  tests/services/llm/test_anthropic_provider_fixes.py \
  tests/services/llm/test_azure_openai_provider.py \
  tests/services/llm/test_openai_compat_wire_api.py \
  tests/core/test_agentic_client_api_format.py \
  tests/core/test_agentic_client_provider_kwargs.py \
  tests/services/session/test_configured_turn_runtime.py \
  -q -o addopts='' -W default --tb=short
```

结果：**171 passed，6.49 秒**。该分组与 343 项分组有重叠，不应相加宣称唯一测试数。

### 用量核查边界

本轮未发现原 AgentLoop 或 OpenAI services 流缺少 include_usage 的缺陷，也没有为补真实 smoke 的 unknown usage 而修改生产用量逻辑。原标题调用有 20 秒超时及 fallback；可能取消尚未取得 usage 末帧的流。真实端点缺 usage 的具体调用必须由集成负责人按实际响应/取消日志定位，不以假 usage 或合成测试替代供应方数据。Anthropic 本轮覆盖真实 SDK 构造与本地文件隔离，没有执行真实远端 Anthropic 模型。

本轮完成前再次执行 `openspec validate add-enterprise-pg-identity-session-slice --strict --no-interactive`：通过。未修改任何任务 checkbox。
