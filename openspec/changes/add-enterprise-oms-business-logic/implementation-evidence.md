# OMS 业务逻辑实施证据与门禁

> 2026-09-26 基线；用户已明确授权重订依赖提案和实施正式代码，限定使用隔离合成数据验证，不触碰真实租户数据、生产发布、归档或提交。本文件区分**源码审计/待实施契约**与已运行的业务验收；不得以迁移清单替代迁移或总账实现。

## 1.1 PG 现状与版本化迁移清单

| 事实 | 源码证据 | OMS 缺口与裁决 |
| --- | --- | --- |
| 身份与租户资格 | `deeptutor/persistence/postgres/migrations/0001_identity_sessions.sql` 的 `tenants` 分存 `external_eligibility`、`local_enabled`、`provisioning_status`，`users.role` 仅有 `tenant_admin/user`；`auth_sessions` 绑定 `(tenant_id,user_id)` | 当前无独立平台主体与 `ops.*` 动作权限，不能把 `tenant_admin` 提升为 OMS 操作者；OMS 不写租户开停 |
| scope 与个人 owner | `deeptutor/persistence/postgres/scope.py` 的 `TenantScope` 固定 tenant/user；`0001_identity_sessions.sql` 对会话等有 tenant + restrictive owner RLS | 平台跨租户读写不可复用个人 `TenantScope` 伪造目标 tenant；需独立可信平台主体和受控目标绑定，私有正文不进入 OMS |
| 配置版本与 Secret | `0014_externalized_runtime.sql` 的 `runtime_settings` 有 `version/desired/active/status`，`secret_references` 保存引用；`deeptutor/persistence/postgres/governance.py::mark_active` 直接 `active=desired`；企业 `model_catalog.py` 主要装载 LLM，且无 active 时读 desired | 缺目标执行者确认、上一 active 版本、分实例确认和全服务执行适配；该状态不能作为 OMS 发布成功证据。Secret 引用表不是采购或用量总账 |
| 资源 owner 与审计 | `0014_externalized_runtime.sql` 的 `resource_objects` 以 `(tenant_id,owner_id,id)` 标识个人对象；`runtime_audit_events` 为 tenant 范围；`0001_identity_sessions.sql` 另有简要 `audit` | 缺 global/tenant Skill owner、平台资源 owner，以及带平台主体/目标租户/版本/原因/关联 ID 的 OMS 审计 |
| operation 与用量 | `0001_identity_sessions.sql` 的 `operations` 是会话请求幂等表、含 30 天过期和删除状态；`deeptutor/runtime/agentic/usage.py` 可按字符估算汇总 | 无供应商 `attempt_id`、逐调用原始 usage/分摊/待核对；不能把会话 operation 表或 `UsageTracker` 当长期财务事实 |
| 企业迁移机制 | `deeptutor/persistence/postgres/migrations/runner.py` 管 core `enterprise.schema_history`；`extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py` 追加 `eduplus2.schema_history`，且校验真实目录/RLS | OMS 采用企业扩展自己的版本化迁移和目录校验，不改已应用 core SQL，不复制第二套 PG，也不复用 `eduplus2` 身份表作业务总账 |

已新增企业扩展 `oms/migrations/0001_ledger_base.sql`：建立稳定 service ID/原生单位、供给批次及终身容量 CHECK、租户服务授权、统一 `gift|recharge` grant、批次承诺、逐 attempt/operation、双维分摊及脱敏审计的**基础表和索引**；租户事实表使用 `ENABLE + FORCE ROW LEVEL SECURITY`，即使应用数据库用户是表 owner 也不能绕过目标 tenant scope。`0002_grant_source.sql` 追加授予来源字段，`0003_grant_command_idempotency.sql` 追加命令去重，`0004_attempt_lifecycle.sql` 追加发出/待核对状态、稳定分摊顺序、请求指纹和脱敏证据事件；`0005_command_result_summary.sql` 固定撤销幂等响应，`0006_append_only_facts.sql` 禁止原始调用证据与审计事件更新/删除。旧行保留 `NULL` 待核对，不伪造历史 dispatch。`MigrationRunner` 将 OMS schema 作为独立 checksum/version/advisory-lock/catalog-verify 序列纳入 `plan/apply/verify`；现有切片仍没有完整供给/权益管理、平台写 API、可信执行者接线或真实供应商证据适配，不能等同总账闭环。

仍待独立版本化迁移（编号在实施时确定，不修改已应用 `0001`）：平台主体绑定/权限快照/审计导出范围；五类资源/配置不可变版本与目标执行者确认、Secret **引用**；核对更正和 OMS-only 有凭据成本；global/tenant Skill owner、来源、打包摘要/版本与默认零授权。若供应商单位、跨批次兼容及账务状态在服务实现中证明 `0001` 缺列/约束，须**新增**后续 migration，不修改已应用文件。外部 EduPlus2/OpenFGA/Keycloak 若实际改变 relation/client/mapper，走发送端受控迁移，不能本地种伪管理员。

每版须有 immutable checksum、`plan/apply/verify` 和 schema/RLS/index/constraint/trigger drift 校验；已在**临时 PG 合成数据**上验证 `0001`–`0006` 重复 apply、表/RLS/index/attempt 状态约束/追加事实 trigger drift 阻断及表 owner 仍被租户 RLS 限制。内部授予、撤销与 attempt 并发/原子性已有合成测试；尚未验证跨版本真实升级、完整供给管理、真实供应商结算或配置旧 active 回退。既有 core 及 EduPlus2 已应用 SQL 不修改。现有真实数据不作自动推断回填：旧 `runtime_settings`、`runtime_audit_events` 仅可按显式映射 dry-run，无法确定 owner/单位/版本的记录进待核对，不制造供给或授予。DB 迁移：**已新增基础 schema，后续仍需要**；外部 OpenFGA/Keycloak：仅在所选平台身份 provider 实际采用并完成独立契约后判定，当前不得假设已经迁移。

## 1.2 持久化、索引与事务契约

- `service_id` 不因 provider/model 或配置版本切换改变；`unit_code`、计量尺度和兼容池由版本化服务 descriptor 确定。批次必须有来源引用、开始/截止时间、`hard_ceiling`（可空代表不可硬授予）、provider/model 适用范围和不可变原生单位；只读采购金额不转换为服务单位。`CHECK quantity > 0`、`expires_at > starts_at`、`grant.expires_at <= 每笔支撑批次.expires_at`；跨批次兼容性在同一事务校验。
- `supply_lot` 的逻辑账面量分为 `settled_lifetime`、`committed_unspent`、`reserved_inflight`。有限批次始终满足 `0 <= settled_lifetime + committed_unspent + reserved_inflight <= hard_ceiling`。授予增加未使用承诺；准入把承诺**转移**到预留，不再次扣除；可信结算把预留转为历史消耗，未实际使用的预留在 grant 仍有效时归还原 grant 的未使用承诺、否则释放为供给可用量；过期/撤销只释放尚未预留的承诺。批次过期不删除历史和不确定预留。
- `grant` 保持授予原额、已结算、未使用承诺、在途预留；一次 attempt 可关联多笔 grant/lot。使用 `(tenant_id,service_id,status,expires_at)`、`(tenant_id,service_id,acquisition_method,expires_at,created_at,id)` 和 `(pool_id,unit_code,expires_at,id)` 索引；同池账务变更先取得相同 advisory 池锁，避免重放与释放反序持有 attempt/池锁造成死锁。
- 幂等键：平台写入 `(actor,action,idempotency_key)` 与 payload fingerprint；授权/授予更新使用 `expected_version` CAS；供应商 attempt 在 `(tenant_id,attempt_id)` 唯一，`operation_id` 非唯一，一个 operation 可有多次可计费 attempt。可得的供应商 request ID 按 provider/account/服务去重；相同 attempt 的重复回执不得再次结算，不同 attempt 即使属同一 operation 仍分别计量。原始证据不可覆盖，更正只追加 adjustment。
- 供给授予与准入必须在 PG 单事务中锁定上述行、校验有效期/兼容性/授权/配置 readiness/双侧余额，写入承诺或预留与审计后提交。网络调用绝不持有 DB 事务；提交预留后才发往 provider。发出前确定失败可释放；发出后超时、取消、流中断或异步状态未知必须待核对且保留预留。实际 usage 超过已证明的保守上界属契约违规，停止该服务新调用并进入人工核对，不能静默透支。

**隔离 PG 基础契约测试已运行**：`test_oms_ledger_migration.py` 验证有限批次上界 CHECK、并发容量竞争、承诺→预留→历史消耗不重复扣、批次过期不清历史/预留、attempt/供应商回执唯一键。`test_oms_attempt_ledger.py` 已在内部事务验证赠送先于充值、一笔 attempt 跨两笔 grant、并发预留、发送前释放、远端未知保留、迟到可信用量、重复回执、同 operation 双计费 attempt、超上界保持待核对且普通回执不得降级、后来撤销授权仍可幂等读取原预留、授予撤销只释放未使用承诺而保留在途、账务异常回滚、追加证据不可改写及重放/释放锁序死锁。**仍待真实执行边界验证的向量**：流中断、异步任务、provider ID 回执、取消未知、Agent 防双扣、跨实例、供给撤销与后续补赠不重分摊。所有期望值用手工字面量给出，测试不以实现公式计算期望。

**新增内部授予/撤销事务切片**：`oms/ledger.py::OmsGrantLedger.grant` 已在受控 `TenantScope` 的 PG 单事务中验证服务单位与 enabled、目标租户服务授权版本/有效期、有限兼容供给的 provider/account/pool/原生单位/有效期；按最早到期批次锁定并分配，原子写入 gift/recharge 同表授予、逐批次承诺和审计。供给不足只提交脱敏 denied 审计，不留半笔 grant/承诺；两笔并发竞争同一批次的合成测试仅一笔成功。`revoke` 以 `expected_version` CAS 和 actor/action/key 幂等撤销 grant，只释放未用承诺，不抹掉在途或历史结算；随后真实用量仍归原 grant，撤销前后的命令响应不随结算变化。先前 `0001` 若有未知来源保持 `NULL` 待核对，不伪造回填。此组件**未对外装配**，不会把 `TenantScope` 当平台授权；尚无平台授权 API、授予调整/供给登记、执行边界或 TMS 视图，因此 7.2/7.3 等任务仍未勾选。

**新增内部 attempt 事务切片**：`oms/attempts.py::OmsAttemptLedger` 在受控 `TenantScope` 和企业 PG 事务中，依 tenant 服务授权及同 provider/account/pool/unit 的有效有限 grant 做赠送优先预留；一笔 attempt 可拆分多个 grant/lot，同一 operation 可有多个独立计费 attempt。发出前先提交 `dispatch_intent`；网络结果未知保留预留；仅明确未发出可释放，可信回执或受控核对可把预留转为历史消耗并按原 grant 归还仍有效的未用差额。超预留上界不透支或当零用量，保持 `reconcile_required` 和预留；普通回执不能覆盖既有超界。每项转账按统一锁序、行数和分摊总额 fail closed，避免重放/释放反序死锁。**该类仍无真实 provider 适配、可信 CallContext/配置 readiness/平台或租户授权入口，不能供生产调用**；其 `source` 参数不能被直接暴露为用户输入。隔离 PG 定向测试 `test_oms_attempt_ledger.py` 为 **11 passed**，不构成 7.4/7.5 或依赖 usage change 的完整验收。

**Skill 完整包校验切片**：企业扩展 `oms/skill_package.py::validate_skill_archive` 仅解析 ZIP 字节，不落盘或执行脚本；拒绝缺失/重复 `SKILL.md`、前言缺 name/description、正文为空、目录名不符、多个包根、重复/遍历/隐藏路径、符号链接、危险后缀、加密/损坏/超限/高膨胀包（包括伪装目录的危险条目）。名称和说明仅取自 `SKILL.md`，包内自报 owner/source/status 被拒绝，返回不可变 ZIP 摘要。合成测试 `test_oms_skill_package.py` **18 passed**。此纯校验器尚未接入可信 global/tenant owner、审核发布、版本存储或所有运行入口的授权过滤，不能据此勾选 6.5。

手算断言基准：批次上界 100、历史 20、未用承诺 50、在途 10 时可再授予 **20**；从该未用承诺预留 15 后变为历史 20、未用 35、在途 25，可再授予仍为 **20**（若误重复扣预留会错误变为 5）；这 15 的可信实际用量为 12、原 grant 仍有效时变为历史 32、未用 38、在途 10，可再授予仍为 **20**。另一个上界 100、占用 70 的批次同时申请两笔各 20，最终**最多一笔成功**，另一笔版本/供给冲突且不得留半笔审计或承诺。上述容量和计数已由直接 SQL 的 PG 测试验证，**不代表正式业务事务、审计原子性或真实供应商 dispatch 验收**。

## A2/A3 已识别的后续验收门禁

### 2.1 执行者、单位与失败/取消负例盘点

以下是**当前代码返回形状**，不是供应商计费合同或已开放硬配额。供应商原生单位须逐 adapter/合同核实，不能把成功输出大小或估算值当账务证据。

| 服务 | 实际发出边界/当前返回 | 当前可信单位判定 | 开放硬配额前必须补的证据 |
| --- | --- | --- | --- |
| LLM/task | `services/llm/provider_core/*` 产生 response/stream `usage`；`services/llm/usage_frame.py` 规范化 Token；`runtime/agentic/usage.py` 另有字符估算 | **仅**供应商有效 usage 的 Token；task 未单独配置时回退 LLM，但仍是实际 provider attempt | 每次发出前的可信上界、最终 usage 与 request ID；流中断/重试分别待核对，不以 turn 摘要结算 |
| embedding | 由 catalog/embedding adapter 发往模型端；当前未见统一逐请求业务 usage ledger | 待 provider adapter 证明的 Token 或原生单位 | 不能把向量数/文本字符直接当供应商 Token；缺 usage 和硬上界时关闭硬额度 |
| 搜索与 web fetch | `services/search/providers/*` 返回 `WebSearchResponse.usage`；Firecrawl 有 `credits_used`、部分 provider 有 Token、Tavily/Serper 为空 | 按 provider 分型：可核验 credits/Token；在一请求一计费有证据时可计**调用次数** | 搜索、抓取/页面数可能分别计费，不得统一按一次 Tool 调用；空 usage 不等于零，失败后不确定发出待核对 |
| TTS/STT | `services/voice/__init__.py` 与 `voice/base.py` 分别只返回音频 bytes、识别文本/时间 cue | 当前无统一供应商 usage；音频时长/字符须 provider 证明，输出 bytes 不是单位 | 适配器返回 request ID、可信时长/字符及最大输入/输出上界；上传后取消/超时不得按零 |
| imagegen | `services/imagegen/base.py` 返回 `(image_bytes, content_type)` 列表 | 可在**证明每张计费且请求 n 有硬上界**的 adapter 计图片张数；当前返回不是供应商 usage | `n` 与 provider 实际生成/计费数、失败部分生成、重试的证明；不能凭收到的文件数结算远端已生成但下载失败的图片 |
| videogen | `services/videogen/base.py` 和 `adapters/async_task.py` 的 submit → poll → download，submit 有 provider task ID，generate 只返回视频 bytes | 当前无可信秒数/分辨率计费回执；若合同证明固定一次提交计费，才可计任务次数 | submit 成功后 polling 失败、取消或下载失败必须保持远端待核对；配置测试 `probe_video` 也可能提交可计费任务 |
| 文档解析/OCR | `services/parsing/service.py` 的 parse cache 命中不发外部请求，engine 可本地或云端；无统一 provider 用量 | 本地处理不应虚构供应商配额；远端引擎须证明页数/请求次数/原生单位 | 区分 cache hit、云端提交、部分页失败与重试；OCR 仅按真实引擎能力开放，不能从目录标题推出独立 OCR Provider |
| LightRAG | 企业 `EnterpriseLightRAGTool` 通过受控 `/query` 检索；返回正文与 sources，没有计费 usage | 当前最多可在上游契约证明后计**检索请求次数**；索引/解析另有任务单位 | 远端查询超时未知、索引任务排队/失败/取消、引用与 KB owner 对账；不能把一轮 Agent 当一次 RAG 供应商调用 |
| 工具/外部 Agent | `tools/builtin` 各自包装搜索、模型、沙箱等；Agent 可多次子调用 | 顶层只有流程指标；每个真实外部子服务按其自身单位结算 | 继承可信 operation/subject，每个计费 retry 独立 attempt；内置本地工具不能当外部采购消耗，顶层不可对底层再次扣款 |

负例必须在合成集成测试中覆盖：**发出前校验失败**不生成 provider attempt/消耗；**发出后网络超时**保留预留并待核对；**用户取消异步视频**若供应商取消未确认不能释放；**流无最终 usage**不以字符估算结算；**解析 cache hit**不产生远端 parse attempt；**Agent 重试两次均计费**两笔 attempt，重复回执零新增；**图文输出下载失败**不凭本地空 bytes 推断远端零费用。当前仅为测试设计，未宣称这些负例已运行。

### 2.2 LightRAG 对账状态与 OMS 投影

**边界核验结果（现状，不代表托管索引已交付）**：`LightRagServerClient` 的实际外部请求仅为 `POST /query`、`GET /auth-status` 和 `GET /documents/pipeline_status`，无直接 PG/HugeGraph 客户端；`LightRagServerPipeline.initialize/add_documents` 明确拒绝本地代建索引。企业运行态 `EnterpriseLightRAGTool.execute` 的检索结果包含 `content/sources`，只供已授权回答路径使用，不能流入 OMS；现有 `build_resource_binding_evidence` 仅输出脱敏 endpoint、workspace hash、index/contract version、服务状态与样本就绪位，不读取检索正文或 Secret。企业 HTTP 目前未装配 OMS 路由，因此不存在可访问正文的 OMS 平台 API。合成回归 `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q tests/services/rag/test_lightrag_server_pipeline.py extensions/enterprise/tests/test_m1_g1_baseline.py::test_resource_binding_evidence_records_hashes_and_blocks_missing_lightrag_sample extensions/enterprise/tests/test_application.py::test_m1_does_not_expose_tms_or_oms_surfaces --tb=short` 为 **17 passed**。尚缺受控托管导入、远端任务查询/取消、索引版本及批量对账 API；上线状态投影仍须新测试证明其不调用 `/query`、不透传 `content/sources`。这次完成的是任务 2.2 的**核对和缺口列举**，不是任务 6.2/7.7 的正式 OMS 能力。

OMS 可读平台级 endpoint/Secret 引用是否就绪、workspace/index binding **版本**、任务数量与脱敏状态；不可读 `/query` 的 `content`/`sources`、租户正文、文件原文、图节点或内部表。托管任务至少区分 `accepted/queued/running/indexing/ready/failed/cancel_requested/cancel_confirmed/remote_unknown/reconcile_required`；binding 切换还须区分 `desired/active`。目前企业工具仅有检索、现有本地 LightRAG server pipeline 对 add/initialize 明确拒绝，故**托管导入、远端任务查询/取消、索引版本对账 API 尚缺**，`remote_unknown` 不能显示为完成。若未来检索 API 返回正文，该数据仅给获授权的 DeepTutor 回答路径，不得作为 OMS 状态 DTO。

- `deeptutor/services/rag/pipelines/lightrag_server/client.py` 当前只发 `POST /query`（`only_need_context=True`）及只读 `GET /auth-status`、`/documents/pipeline_status`；`EnterpriseLightRAGTool` 见 `extensions/enterprise/src/deeptutor_enterprise/knowledge_bases.py`，其结果含检索正文，不适合直接给 OMS。旧本地 pipeline 的文档 add 明确不可用，delete 仅解绑指针。OMS 仅可取脱敏平台状态，托管导入/任务/索引版本/远端对账需独立受控 API 验收；不得直连 LightRAG 内部 PG/HugeGraph 或复制租户正文。
- `extensions/enterprise/src/deeptutor_enterprise/api/application.py` 的显式 router 白名单只挂 `settings.public_router`，未挂核心 `settings.router`、`governance.tms_router`、`governance.oms_router`；但 `voice.router`、resources、WS 等仍是实际执行入口，且 CLI/SDK/后台不经该 HTTP 白名单。核心 `deeptutor/api/routers/governance.py` 的 OMS/TMS 名称路由都使用 `require_admin`（tenant admin）且可 `mark_active` 直接复制 desired；云端不得挂载为平台 API。本地 `deeptutor/api/main.py` 继续保留设置路由。正式切片须用路由快照和直调负例证明云端所有平台写旁路关闭，不能只隐藏前端。
- `deeptutor/runtime/agentic/usage.py::UsageTracker` 包含字符估算，不能结算 Token；search provider 的 `WebSearchResponse.usage` 是各供应商异构字段（Firecrawl credits、部分 Token、Tavily/Serper 为空）；TTS/STT 门面仅返回 bytes/text，imagegen 返回图片，videogen 为异步任务，解析引擎返回文档结果，均尚无统一可信结算证据或硬上界。正式逐服务接线前要分别确定可信单位、发出边界、上界和取消/迟到状态；缺任一项不开放硬额度，不将空 usage 视为零。

隔离回归命令：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q tests/services/rag/test_lightrag_server_pipeline.py extensions/enterprise/tests/test_application.py --tb=short`，结果 **42 passed, 1 skipped**。未加 `-c` 的首次运行是 pytest 未加载企业目录的 `asyncio_mode=auto` 导致 27 个 async fixture setup 错误；无产品代码故障，已用仓库企业测试配置重跑。现有回归仅证明当前 M1 路由封闭和本地 LightRAG 客户端契约，不证明 OMS 平台状态 API、远端任务/索引对账或全入口准入已实现。

另新增 `test_enterprise_does_not_mount_legacy_management_writes`，用已登录的租户管理员 token 加伪造 `X-Scopes`，逐条请求云端旧 settings 草稿/应用/测试/OAuth、Skill 创建及 OMS Provider/额度写路径，断言 **404**；单项命令 `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_enterprise_does_not_mount_legacy_management_writes --tb=short` 结果 **1 passed**。它是当前显式 router 白名单的防回归负例；未来真实 OMS router 装配后需把 OMS 写路径改成 401/403/获授权正例矩阵，并证明旧旁路继续 404，因此 3.1 仍未完成。

本地 Web 保留正例与云端旧写入口负例联合回归：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q tests/api/test_settings_router.py::test_get_ui_settings_is_public_without_auth tests/multi_user/test_grants_and_settings.py::test_tenant_admin_can_manage_settings_catalog extensions/enterprise/tests/test_application.py::test_enterprise_does_not_mount_legacy_management_writes --tb=short` 得 **3 passed，1 条 Starlette/anyio deprecation warning**。这说明当前本地设置与企业路由隔离未被基础 schema/身份代码破坏，但 CLI/SDK/后台管理写入以及未来新 OMS 路由的拒绝矩阵仍待验证。

## P0 依赖提案重订清单（尚未将旧版 tasks 视作获批）

| 旧 change | 必须修改的正式契约 | 当前不能实施的旧语义 |
| --- | --- | --- |
| `add-b2-oms-platform-read-governance` | 改为可信平台主体、`ops.*` 动作能力、显式目标租户、OMS 读写 API、最小投影/审计/导出；默认和自定义角色迁移，负例覆盖伪造平台 claim、tenant admin、跨租户/无成本权限 | “OMS 仅只读”和把同名 core `require_admin` 路由当平台写入口 |
| `add-enterprise-all-service-provider-settings` | OMS 为云端唯一平台管理入口；本地 Web 设置保留；全服务 descriptor 与条件属性、Secret ref、逐执行者版本确认/部分失败回退；企业装配阻断云端旧写 API/CLI/SDK | “云端 DeepTutor 平台设置单独写，OMS 仅看状态”和 `desired` 复制即 active |
| `add-enterprise-exact-token-usage-ledger` | 统一 Token/非 Token 原生单位的 attempt 账务证据、上界预留、异步/取消未知状态、重复回执和多次可计费重试；作为唯一 OMS 消耗事实，不推导租户费用 | Token-only、字符估算补账、独立计费/欠费 change 作下游 |
| `add-b2-eduplus2-tenant-lifecycle-webhook` | 仅保留签名租户开停/恢复、分源状态、乱序/重放/对账；服务额度不足为 OMS 服务准入事件，不影响 EduPlus2 资格 | 独立“欠费模型资格”事件及 OMS 欠费停模 |
| `add-c1-c2-oms-operator-interface` | 独立 OMS 前端按五类资源与供给→授权/额度→使用→核对列表→详情接真实 API；权限分普通运营/高权限/审计；生产原型 404 | 本地 `web/app/oms` 是正式入口、Token 售价/费用/欠费页面、Provider 只读 |
| `add-oms-token-billing-and-arrears` | 不执行旧任务、不做 `--skip-specs` 归档；先在替代契约完成并经用户单独同意后决定 archive/sync 策略 | 租户售价、账单、欠费状态、支付和 EduPlus2 欠费模型资格 |

重订须同步每个 change 的 proposal、design、delta spec、tasks 并分别 `openspec validate --strict`；含旧财务要求的已停用 delta 不可直接归并正式 spec。下述五份旧目标现已完成重订并获用户分别批准；`7.1` 的契约/基础迁移门禁据 §7.1 勾选，但 `6.1` 所需平台权限 PG/发送端迁移仍缺合同，不得勾选。平台身份的可信 issuer/claim/角色来源目前在文档中只写为目标，尚无可执行契约；该选择必须在跨租户写 API、权限迁移之前锁定。

`add-b2-oms-platform-read-governance`、`add-enterprise-all-service-provider-settings`、`add-enterprise-exact-token-usage-ledger`、`add-b2-eduplus2-tenant-lifecycle-webhook` 与 `add-c1-c2-oms-operator-interface` 的 proposal、design、delta spec、tasks 已正式重订，用户已分别批准五份按现版实施。旧 `add-oms-token-billing-and-arrears/replacement-decision-draft-2026-09-26.md` 的退役目标也已获单独批准，**不执行旧 tasks、不归档或同步冲突旧 spec**。上述批准不等于已完成代码、迁移或运行验收。

用户后续明确选择 **EduPlus2 平台身份与权限** 为 OMS 可信来源。现有 `deeptutor_enterprise/eduplus2/client.py` 的 JWT verifier 要求 `tid/eui/sub/azp`，`service.py::exchange_user_jwt` 将外部 tenant/user 映射进固定租户 `enterprise.users`；`_ordinary_usages` 特意过滤 `tms./oms./ops./platform.` 前缀。故该租户换票流程不能“加一个平台 role claim”直接变 OMS：需独立 OMS audience/client、可信 issuer/subject 绑定、EduPlus2 平台权限逐动作核验与版本/撤权、受控平台 session、目标 tenant 范围和平台审计。未知 EduPlus2 发送端接口/角色 relation 不能凭 DeepTutor 自造；在双方契约和隔离负例确认前，跨租户写路由必须保持未装配。DB 权限/角色迁移需要；EduPlus2 侧若新增 relation/claim/client，须由其独立版本化迁移交付，不能在本仓库手工伪造。

用户提供的 [EduPlus2 开发者文档](https://eduplus-test.f123.pub/docs/) 已于 2026-09-26 经只读 `curl` 核实：[`OAuth/OIDC 概述`](https://eduplus-test.f123.pub/docs/oauth-oidc/) 与 [`JWT 验证`](https://eduplus-test.f123.pub/docs/oauth-oidc/jwt-verification/) 给出 Keycloak realm 的 OIDC discovery/JWKS、RS256、验证 `iss/aud/exp/iat`；[`Token Claims`](https://eduplus-test.f123.pub/docs/user-data/token-claims/) 和 [slim-JWT ADR](https://eduplus-test.f123.pub/docs/decisions/slim-jwt-to-identity-assertion/) 明确 access token 是 identity assertion，**不能用 realm/client role 作为 EduPlus2 业务权限**，`tid/eui/eit` 可能为空；权限应查 API/OpenFGA。这里的“独立平台身份”指**独立 OMS client/audience、DeepTutor 平台认证路径与动作授权**，不要求 EduPlus2 新建第二个 issuer（可使用同一受信 Keycloak realm）。[`权限检查 API`](https://eduplus-test.f123.pub/docs/permission/api/check/) 示例用当前 JWT 的 `sub/tid` 且注明调用者须有租户 admin 权限；概述与 API 参考对路径 `/api/v1/permissions/check` vs `/v1/permissions/check` 不一致。文档未定义 OMS 平台 operator 可用的 relation/object、目标 tenant 授权范围、OMS client/audience 或撤权版本。因此目前只足以确认**认证机制的通用部分**，不足以安全实现正式 OMS 跨租户授权；不能假设租户 admin 权限检查接口可授权平台操作者。后续须取得准确的 OMS client 注册和 `ops.*` 权限契约。

另对该文档站点 sitemap 的 120 个页面做只读关键词盘点；[`基本概念`](https://eduplus-test.f123.pub/docs/getting-started/concepts/) 确认存在系统预定义 `platform_admin` 与 `platform_operator` 角色及 `/ops/**` 平台运营前端路径，但没有给出角色对应的 OMS `ops.*` relation/object、专用 audience/client 或平台权限 API 调用者规则。故不能仅凭角色名称或 `/ops/` 路径推导本系统写权限。

应用户指引复查本仓库 `docs/enterprise/`：[`08-auth-and-identity.md`](../../../docs/enterprise/08-auth-and-identity.md) 给出 TMS/OMS 的**建议** Handoff 流程和 `azp`/JWT/profile 校验，但明确写“尚未实现”两端交互登录；[`09-authorization-and-grants.md`](../../../docs/enterprise/09-authorization-and-grants.md) 的平台角色与权限对象为**建议映射**，要求确认 EduPlus2 实际 relation/object 后再迁移；[`12-platform-operations-admin.md`](../../../docs/enterprise/12-platform-operations-admin.md) 明写 `ops.*` 是 DeepTutor **拟新增能力 key，不声称 EduPlus2 已有同名 relation**，而且这一页保留已被本 change 取代的旧 OMS 只读、费用/欠费与独立 Provider 设置叙述。[`07-resource-isolation.md`](../../../docs/enterprise/07-resource-isolation.md) 仍有旧“租户预算与费用账本”用语；`09` 曾建议 OMS 注册 client，而 [`11-api-and-entrypoints.md`](../../../docs/enterprise/11-api-and-entrypoints.md) 当前只规划 OMS client 只读。这些跨页差异也证明不能把历史目标文本视为已实施的外部授权契约。故这些文档提供产品目标、入口分层与安全约束，**不是已签发 OMS client/audience、平台 operator 可调用权限 API、撤权版本或 OpenFGA relation/tuple 的执行契约**；不能把旧“平台白名单账号”文字当成生产权限迁移。本文与已获批准的新 OpenSpec 对冲突处优先；`02/11/12` 的逐处重订仍属 P0，未因阅读完成而勾选。

本机另发现同级 `/Users/minwang/Projects/edu-plus-2` 发送端源码，仅作**只读**核对：`backend/src/main/java/com/eduplus/module/permission/controller/PermissionCheckController.java` 的 `/v1/permissions/check` 从 JWT 取 `sub` 和 tenant claim，缺 tenant 即拒绝；它不是平台 operator 的 OMS 跨租户目标授权接口。`backend/src/main/resources/db/migration/public/V20260517_009__add_platform_runtime_capabilities.sql` 有通用 `platform_ops:*` 默认能力，但发送端源码、Flyway 与 env-tool 中未找到 DeepTutor 专用 OMS client/audience 或 `ops.*` 能力迁移。由此进一步确认既有通用平台能力不能直接推成 OMS 动作/目标租户许可；未修改发送端仓库，也未执行其迁移。需要发送端明确合同与修改授权后才能完成 4.2/平台治理依赖门禁。

生命周期 Webhook 的接入顺序按用户新说明调整：`.secrets/.test-secrets` 已有测试 secret 引用，已在企业组合实现 `POST /api/v1/eduplus2/webhooks` 的**三段式 HMAC 已验签 mock URL 接收**，隔离合成测试 204 且租户状态不变；真实事件未有单调版本/绑定/对账时返回 503。已核对现行发送端 demo 使用 `subscription.*`、`mock_` event ID 和 `X-EduPlus-Mock: true`，并非旧暂拟 `tenant.enabled|suspended|resumed`。尚未部署 HTTPS 测试 URL 或从 EduPlus2 控制台实际发起 demo；见 [`add-b2-eduplus2-tenant-lifecycle-webhook/implementation-evidence.md`](../add-b2-eduplus2-tenant-lifecycle-webhook/implementation-evidence.md)。此切片不满足本 change 4.1，也不解决 OMS 平台 operator 权限 4.2。

已在企业扩展新增 `oms/identity.py::PlatformOidcJwtVerifier`：复用现有 OIDC discovery/JWKS 客户端获取受信 RS256 key，但独立验证配置的 OMS audience/client、`sub`、`typ=Bearer`、`iss/exp/iat`，只返回脱敏身份与 token hash，**不从 JWT role 产生任何 `ops.*` 权限，也不转换为租户 session**。配置的 issuer/discovery 必须是同源 HTTPS，discovery 不得把 JWKS 指向异源或非 HTTPS，避免以受信 discovery 的可变字段扩展网络/信任边界。此类尚未装配到路由或授权服务，因 EduPlus2 OMS relation/object/目标 tenant 契约仍缺失；绝不以“JWT 验证通过”视作跨租户写权。TDD 红灯为 `ModuleNotFoundError: deeptutor_enterprise.oms`（7 项）及新增 HTTPS/JWKS 同源负例 1 项，绿灯命令 `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_oms_platform_identity.py --tb=short` 为 **10 passed**，含错 audience/azp/issuer、空 subject、ID token `typ`、未来 `iat`、篡改签名、HS256 混淆与异源 JWKS 负例。该切片仅覆盖身份断言验证，不满足任务 4.2 的完整权限/角色迁移验收。

## 3.1 管理旁路路由审计（当前入口基线完成）

| 入口 | 当前审计与阻断证据 | 后续重验边界 |
| --- | --- | --- |
| 本地 Web/API | `deeptutor/api/main.py` 保留完整 `/api/settings`、workspace/video-learning/MCP 等本地管理 router；`web/features/settings` 保留本地页面。`test_get_ui_settings_is_public_without_auth` 与 `test_tenant_admin_can_manage_settings_catalog` 合成正例通过。 | 本地行为不可为云端安全而删减；未来改通用入口后须重跑同组正例。 |
| 企业 HTTP/WS | `api/application.py` 显式白名单只挂 `/api/settings/ui` 公共偏好、session/resource/voice/WS/health 等。`test_enterprise_management_route_allowlist_is_narrow` 从实际 OpenAPI 路径确认 `/api/settings` 仅有 `/ui`，无旧 Skill、TMS/OMS governance、MCP、Partners、system、workspace/video-learning 设置。`test_enterprise_does_not_mount_legacy_management_writes` 以已登录 tenant admin 加伪造 `X-Scopes` 请求 18 个旧写路径，均为 404（`PUT /api/settings/ui` 为 405）；个人 `/api/settings/ui` 只返回 theme/language/response_language。 | 真实 OMS/TMS router 当前仍未装配；新 router 上线前按逐动作主体/目标租户矩阵重验，不把旧 `require_admin` 复用为平台权限。 |
| 核心同名治理 API | `deeptutor/api/routers/governance.py` 的 TMS setting/activate 与 OMS secret 写仅依赖租户 `require_admin`，`mark_active` 不具执行者确认。上述云端路由测试确认它们完全不在企业组合内，不能从用户角色或伪造 header 调用。 | 必须以独立可信平台主体和权限契约实现新 OMS API，不能开放同名旧 router。 |
| 受保护镜像启动 | 原 `start-backend.sh` 在 `DEEPTUTOR_POSTGRES_CONFIG` 缺失时会回退到 `deeptutor.api.main:app`，即使是受保护镜像也可意外暴露旧管理面。现由 `Dockerfile.protected-runtime` 与受保护 K8s `backend.yaml` 固定 `DEEPTUTOR_PROTECTED_RUNTIME=1`；脚本在缺/不可读配置或 ASGI 模块被覆写时直接退出，只允许 `deeptutor_enterprise.runtime_app:app`。`test_protected_backend_start.py` 的实际 shell 子进程负例与 K8s 渲染测试通过；未设置该标记的本地镜像仍按原逻辑回退核心 app。 | 这是启动失败关闭与本地兼容回退证据，**不是**生产 K8s 发布/回滚演练；拥有 Pod exec/镜像/环境修改权的运维主体仍需外部 RBAC 控制。 |
| CLI/SDK/后台 | 核心 `deeptutor_cli/config_cmd.py` 只读本地设置，`provider_cmd.py` 可写本地 OAuth 文件但不修改企业配置权威；企业 CLI 命令集只有 schema/bootstrap/account/session/serve/confirm-stopped/recovery，会话命令走远端 token；`Enterprise.sdk(token)` 返回现有 `DeepTutorApp` 会话 facade，没有 OMS 管理方法。`test_oms_management_entrypoints.py` 锁定公开命令/方法负例。企业组合不启动 core `api.main` 的 Partners/cron 路由与本地后台管理器。 | Pod 内任意代码执行/数据库凭据不属于应用级 CLI 授权；未来后台作业、OMS SDK 方法或远端 CLI 管理命令必须重新纳入平台主体/动作授权测试。 |

本节完成的是**当前未开放 OMS 写 API**的入口审计与阻断，不是正式 OMS 授权完成。受保护启动修复采用镜像/脚本/部署模板而非 DeepTutor 核心运行时补丁，保留上游合并能力。后续 4.2、6.3、7.7 的平台权限和新路由上线时，必须重新测试无权 operator、tenant admin、伪造 header/target tenant、Secret 导出、审计关联及真实回退；不能以本节勾选代替 G3。

## 3.2 Core seam 审阅记录（候选，尚未批准 core patch）

| 缺口与源码 | 优先替代方案 | 如确需通用 seam 的最窄入口与合并风险 | smoke 门禁 |
| --- | --- | --- | --- |
| Skill：`deeptutor/services/skill/externalized.py` 的 `list_skills/read_skill_file/load_always_for_context` 自动包含 builtin；`tools/builtin/__init__.py::ReadSkillTool` 还可能读管理员分配来源 | 企业 `SkillService` 装配层先做同一租户授权过滤、摘要/版本固定和 tenant 同名优先，注入现有 runtime service，不改本地自动发现 | 若 `read_skill` 的回退服务绕过注入策略，给通用 SkillResolver/Policy hook，覆盖 manifest、显式请求、正文/参考文件、`always`，默认本地 permissive；风险是上游增加新读取入口时漏拦 | CLI/HTTP/WS/SDK/Partners 六类入口，未授权 builtin 全部不可达；本地 builtin 正例及 tenant 同名优先；升级摘要变化拒绝旧授权 |
| 准入/用量：`UsageTracker` 是 turn 汇总且可字符估算；LLM、搜索、语音、媒体等真实 provider 边界分散 | 企业执行环境/adapter 包装最外层实际供应商调用，用不可变 CallContext 传可信主体、operation/attempt，与 PG ledger 事务相连；不在 orchestrator 硬写 OMS | 如果子调用无通用上下文传播或包装不覆盖 retry/stream，新增 upstream-neutral `ProviderAttemptHook`/上下文只负责 before-dispatch、provider evidence、unknown outcome，不含租户余额计算；风险是上游新增 adapter 未接 hook 或同步/异步边界不一致 | CLI、HTTP/WS、SDK、后台、Agent 子调用各一条正常与无权/无供给负例；重试/流中断/异步未知、session owner 与审计关联 |
| 配置：`runtime_settings.mark_active` 和企业 `model_catalog` 只读部分服务，其他 service 仍按本地 JSON/config | 优先在企业组合根注入 descriptor 对应的配置读取 provider，逐执行者确认，旧 API 不挂载 | 仅在真实执行者不能注入时加通用 ConfigProvider/版本确认 hook，不得让 core 依赖 OMS 表；风险是上游新增字段后 descriptor 与企业适配漂移 | 本地设置与云端 active 各服务真实读取；部分确认/超时保留旧 active；新实例先装载；Secret 不回显 |
| 跨租户平台 API：当前 `TenantScope` + owner RLS 不适合作平台管理查询 | 企业包独立可信平台主体/权限服务和显式目标 tenant 的受控只读/写事务，不向核心 router 注入 `tenant_admin` 假身份 | 只在 app composition 缺路由/身份 provider 扩展点时添加通用 composition seam；风险是修改核心 auth middleware/路由注册造成 upstream 冲突 | 平台/租户主体互不继承；401/403/404 防枚举；HTTP/WS turn、session ownership 和审计 request ID 不回归 |

本轮沿 Skill 全调用链进一步核对：`get_runtime_skill_service()` 只由 Store/ObjectStore 自动构造 `ExternalizedSkillService`，尚无企业可注入 resolver；`TurnExecutor` 的 manifest/显式请求/`always`、`ConfiguredTurn` 的显式请求、`ReadSkillTool` 的正文/参考文件、企业 conversation-test 选项均走该服务，当前内置 Skill 会自动出现。`ReadSkillTool` 的管理员分配 fallback 仅在本地 `SkillService` 分支触发，但不能只过滤清单而不同时过滤正文；核心 Partners 实现还直接调用 `get_skill_service()`，若未来在企业路径启用需单独接同一策略。因完整 owner/授权/不可变版本/摘要和全入口策略尚未实施，任务 6.5 保持未勾选；不能把现有 ZIP 纯校验或尚未装配的策略当生产授权。

当前 `git merge-base HEAD upstream/main` 与 `git rev-parse upstream/main` 同为 `897fce52f24bf22e6e50d8a3e4df532632a26322`（本地已获取引用的兼容基线），但**尚未实施 core patch**，也未对未来变更完成当前 upstream 拉取/merge smoke；不能以该静态祖先检查代替 3.2 的最终 upstream 兼容验收。逐条需要先以 TDD 证明企业装配不足，再审阅通用接口、受影响路径与回退，不能先改 orchestrator 或依赖 monkey patch。

## 7.1 统一总账契约与旧财务目标退役（门禁完成）

`add-enterprise-exact-token-usage-ledger` 已将旧逐 Token 目标正式重订为 Token 与非 Token 原生单位共享的逐 attempt 证据、上界预留、远端未知待核对与幂等结算；proposal/design/spec/tasks 均重写并获用户单独批准。`add-oms-token-billing-and-arrears` 的旧租户售价/账单/欠费目标获用户**退役批准**，没有运行其 tasks、归档或同步冲突旧 spec。用户对本 OMS change 的实施授权涵盖供给批次、同表 `gift|recharge` 授予、可信消耗、仅 OMS 可见的供应商成本证据以及版本化 PG 迁移；前述 `0001`–`0006` 基础迁移由 `MigrationRunner` 管理 checksum、plan/apply/verify，隔离 PG 测试 10 项通过。迁移/代码中没有租户售价、费用、欠费或独立欠费资格字段；OMS-only 成本凭据与核定视图仍属于 7.6 的后续迁移/实现，不以缺凭据推断零成本或租户费用。

因此勾选 7.1 只表示**替代方案与基础迁移门禁获批、旧目标不再执行**。未进行真实租户数据迁移、外部权限迁移、生产部署或旧 change 归档；供给登记/采购、租户权益运营写入、真实执行者准入、可信核对和成本视图仍由 7.2–7.7 验收，不能凭总账表存在放行。

## 本轮隔离验证快照

- `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short`：**316 passed，3 skipped**（2026-09-26，临时 PG/合成数据；不含真实 EduPlus2/供应商或生产环境）。
- OMS attempt 定向测试：**11 passed**；迁移定向测试：**10 passed**；Skill 包校验：**18 passed**；其余授予/身份/当前 OMS 404 等定向测试已被上述全量企业测试覆盖，不相加当总数。首次全量测试因 `test_persistence.py` 的预期迁移清单漏列 `0005/0006` 出现 30 个同源断言失败；补齐清单后定向复验与全量重跑均通过，并非跳过失败。
- 七个相关 OpenSpec change 均 `openspec validate <change> --strict` 通过；`ruff check` 与本轮新增/修改 OMS 文件及 migration runner 的 `ruff format --check` 通过（两份原有大测试文件有历史格式差异，未做无关格式化）；企业 wheel 构建通过，确认包含 OMS 身份、授予/撤销、attempt、Skill 包校验模块及六份版本化 SQL。限定范围 `git diff --check` 通过；工作区另有预先存在的 Web/PDF license 等改动，未作清理或覆盖。
- 受保护启动/管理入口定向 31 项及本地设置/CLI/SDK 定向 4 项通过；`ruff check` 覆盖本轮新测试，`ruff format --check` 覆盖两份新测试，`bash -n deploy/docker-runtime/start-backend.sh` 通过。受保护镜像/脚本/部署模板改变只做静态和合成 shell 验证，未实际构建/发布镜像。
- `openspec instructions apply --change add-enterprise-oms-business-logic --json` 实测为 **6/23**，尚有 **17 项未完成**（本轮勾选 3.1 当前入口基线与 7.1 契约/迁移门禁）。用户已明确答复目前无 EduPlus2 OMS 平台权限契约、正式跨租户写 API 继续未开放；无真实 tenant 数据迁移、发送端变更、生产发布、归档或提交。当前代码切片不得用于 G2/G3 放行。
