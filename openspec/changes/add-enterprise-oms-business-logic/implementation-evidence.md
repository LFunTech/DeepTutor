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

已新增企业扩展 `oms/migrations/0001_ledger_base.sql`：建立稳定 service ID/原生单位、供给批次及终身容量 CHECK、租户服务授权、统一 `gift|recharge` grant、批次承诺、逐 attempt/operation、双维分摊及脱敏审计的**基础表和索引**；租户事实表使用 `ENABLE + FORCE ROW LEVEL SECURITY`，即使应用数据库用户是表 owner 也不能绕过目标 tenant scope。`0002_grant_source.sql` 追加授予来源字段，`0003_grant_command_idempotency.sql` 追加命令去重，`0004_attempt_lifecycle.sql` 追加发出/待核对状态、稳定分摊顺序、请求指纹和脱敏证据事件；`0005_command_result_summary.sql` 固定撤销幂等响应，`0006_append_only_facts.sql` 禁止原始调用证据与审计事件更新/删除；`0007_supply_evidence.sql` 追加供给类型、核验时间、操作者与版本，历史行默认 `legacy_unverified`，不把既有数字自动推断为已核验硬上界。旧 attempt 行保留 `NULL` 待核对，不伪造历史 dispatch。`MigrationRunner` 将 OMS schema 作为独立 checksum/version/advisory-lock/catalog-verify 序列纳入 `plan/apply/verify`；现有切片仍没有平台写 API、可信执行者接线或真实供应商证据适配，不能等同总账闭环。

`0008_quota_expiry.sql` 后续新增 `expired` 状态，将自然到期与人工撤销区分为不同总账事实；`0009_entitlement_commands.sql` 为服务授权命令增加独立幂等记录及目标学校 FORCE RLS；`0010_quota_adjustment.sql` 增加额度调整累计释放列，旧行默认零，不覆盖历史总承诺。仍待独立版本化迁移（编号在实施时确定，不修改已应用 `0001`）：平台主体绑定/权限快照/审计导出范围；五类资源/配置不可变版本与目标执行者确认、Secret **引用**；核对更正和 OMS-only 有凭据成本；global/tenant Skill owner、来源、打包摘要/版本与默认零授权。若供应商单位、跨批次兼容及账务状态在服务实现中证明 `0001` 缺列/约束，须**新增**后续 migration，不修改已应用文件。外部 EduPlus2/OpenFGA/Keycloak 若实际改变 relation/client/mapper，走发送端受控迁移，不能本地种伪管理员。

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

历史决策：用户此前选择 **EduPlus2 平台身份与权限** 为 OMS 可信来源；2026-09-27 已改为 EduPlus2 既存身份/学校权威 + DeepTutor 本产品 OMS 应用权限，以下为当时的风险审计，不是当前权限权威。现有 `deeptutor_enterprise/eduplus2/client.py` 的 JWT verifier 要求 `tid/eui/sub/azp`，`service.py::exchange_user_jwt` 将外部 tenant/user 映射进固定租户 `enterprise.users`；`_ordinary_usages` 特意过滤 `tms./oms./ops./platform.` 前缀。故该租户换票流程不能“加一个平台 role claim”直接变 OMS：需独立 OMS audience/client、可信 issuer/subject 绑定、EduPlus2 平台权限逐动作核验与版本/撤权、受控平台 session、目标 tenant 范围和平台审计。未知 EduPlus2 发送端接口/角色 relation 不能凭 DeepTutor 自造；在双方契约和隔离负例确认前，跨租户写路由必须保持未装配。DB 权限/角色迁移需要；EduPlus2 侧若新增 relation/claim/client，须由其独立版本化迁移交付，不能在本仓库手工伪造。

用户提供的 [EduPlus2 开发者文档](https://eduplus-test.f123.pub/docs/) 已于 2026-09-26 经只读 `curl` 核实：[`OAuth/OIDC 概述`](https://eduplus-test.f123.pub/docs/oauth-oidc/) 与 [`JWT 验证`](https://eduplus-test.f123.pub/docs/oauth-oidc/jwt-verification/) 给出 Keycloak realm 的 OIDC discovery/JWKS、RS256、验证 `iss/aud/exp/iat`；[`Token Claims`](https://eduplus-test.f123.pub/docs/user-data/token-claims/) 和 [slim-JWT ADR](https://eduplus-test.f123.pub/docs/decisions/slim-jwt-to-identity-assertion/) 明确 access token 是 identity assertion，**不能用 realm/client role 作为 EduPlus2 业务权限**，`tid/eui/eit` 可能为空；权限应查 API/OpenFGA。这里的“独立平台身份”指**独立 OMS client/audience、DeepTutor 平台认证路径与动作授权**，不要求 EduPlus2 新建第二个 issuer（可使用同一受信 Keycloak realm）。[`权限检查 API`](https://eduplus-test.f123.pub/docs/permission/api/check/) 示例用当前 JWT 的 `sub/tid` 且注明调用者须有租户 admin 权限；概述与 API 参考对路径 `/api/v1/permissions/check` vs `/v1/permissions/check` 不一致。文档未定义 OMS 平台 operator 可用的 relation/object、目标 tenant 授权范围、OMS client/audience 或撤权版本。因此目前只足以确认**认证机制的通用部分**，不足以安全实现正式 OMS 跨租户授权；不能假设租户 admin 权限检查接口可授权平台操作者。当前须核实既存适用的 OIDC client/audience、在线账号状态与学校接口；`ops.*` 动作和学校范围改由 DeepTutor 自有权限迁移承接，不再索取发送端 OMS relation。

另对该文档站点 sitemap 的 120 个页面做只读关键词盘点；[`基本概念`](https://eduplus-test.f123.pub/docs/getting-started/concepts/) 确认存在系统预定义 `platform_admin` 与 `platform_operator` 角色及 `/ops/**` 平台运营前端路径，但没有给出角色对应的 OMS `ops.*` relation/object、专用 audience/client 或平台权限 API 调用者规则。故不能仅凭角色名称或 `/ops/` 路径推导本系统写权限。

应用户指引当时复查本仓库 `docs/enterprise/`（以下为当时快照，2026-09-27 后续双域权限设计以当前文档和 `add-enterprise-management-authorization` 为准）：[`08-auth-and-identity.md`](../../../docs/enterprise/08-auth-and-identity.md) 当时已区分 TMS 候选 Handoff 与独立 OMS OIDC 会话和 `azp`/JWT/profile 校验，但明确写“尚未实现”两端交互登录；[`09-authorization-and-grants.md`](../../../docs/enterprise/09-authorization-and-grants.md) 当时标注 OMS 权限由 DeepTutor 迁移、TMS 外部权限仍待核实实际契约；此旧 TMS 假设已由双域本产品权限设计取代；[`12-platform-operations-admin.md`](../../../docs/enterprise/12-platform-operations-admin.md) 明写 `ops.*` 是 DeepTutor **拟新增能力 key，不声称 EduPlus2 已有同名 relation**，该页已移除旧 OMS 只读、费用/欠费与独立 Provider 设置作为现行目标。[`07-resource-isolation.md`](../../../docs/enterprise/07-resource-isolation.md) 仍有旧“租户预算与费用账本”用语；`09` 历史上曾建议 OMS 注册 client，现已删除该写权，而 [`11-api-and-entrypoints.md`](../../../docs/enterprise/11-api-and-entrypoints.md) 当前只规划 OMS client 只读。这些跨页差异也证明不能把历史目标文本视为已实施的外部授权契约。故这些文档提供产品目标、入口分层与安全约束，**不是已签发 OMS client/audience、平台 operator 可调用权限 API、撤权版本或 OpenFGA relation/tuple 的执行契约**；不能把旧“平台白名单账号”文字当成生产权限迁移。2026-09-27 新权威划分已写入 OpenSpec 修订稿并待重新批准；`02/08/09/11/12` 的现行边界已同步，剩余实施与验证仍须逐任务验收。

本机此前只读核对同级 `/Users/minwang/Projects/edu-plus-2` 发送端源码：`backend/src/main/java/com/eduplus/module/permission/controller/PermissionCheckController.java` 的 `/v1/permissions/check` 从 JWT 取 `sub` 和 tenant claim，缺 tenant 即拒绝；它不是平台 operator 的 OMS 跨租户目标授权接口。`backend/src/main/resources/db/migration/public/V20260517_009__add_platform_runtime_capabilities.sql` 有通用 `platform_ops:*` 默认能力，但既有发送端源码、Flyway 与 env-tool 中未找到 DeepTutor 专用 OMS client/audience 或 `ops.*` 能力迁移。由此进一步确认既有通用平台能力不能直接推成 OMS 动作/目标租户许可；本代理之后一度编写但现已全部撤销的发送端草稿不算交付，也未执行其迁移。若既存 OIDC、在线账号状态或学校核验能力缺失，只能由 EduPlus2 团队独立提供；DeepTutor 自行完成本产品动作/学校授权后，4.2 仍须以真实外部接口和本地权限负例验收。

生命周期 Webhook 的接入顺序按用户新说明调整：`.secrets/.test-secrets` 已有测试 secret 引用，已在企业组合实现 `POST /api/v1/eduplus2/webhooks` 的**三段式 HMAC 已验签 mock URL 接收**，隔离合成测试 204 且租户状态不变；真实事件未有单调版本/绑定/对账时返回 503。已核对现行发送端 demo 使用 `subscription.*`、`mock_` event ID 和 `X-EduPlus-Mock: true`，并非旧暂拟 `tenant.enabled|suspended|resumed`。2026-09-26 测试 URL 已由 EduPlus2 `智能体基座` 控制台执行 8 类 mock 投递，外部记录均为 HTTP 204；见 [`add-b2-eduplus2-tenant-lifecycle-webhook/implementation-evidence.md`](../add-b2-eduplus2-tenant-lifecycle-webhook/implementation-evidence.md)。此切片不满足本 change 4.1，也不解决 OMS 平台 operator 权限 4.2。

已在企业扩展新增 `oms/identity.py::PlatformOidcJwtVerifier`：复用现有 OIDC discovery/JWKS 客户端获取受信 RS256 key，但独立验证配置的 OMS audience/client、`sub`、`typ=Bearer`、`iss/exp/iat`，只返回脱敏身份与 token hash，**不从 JWT role 产生任何 `ops.*` 权限，也不转换为租户 session**。配置的 issuer/discovery 必须是同源 HTTPS，discovery 不得把 JWKS 指向异源或非 HTTPS，避免以受信 discovery 的可变字段扩展网络/信任边界。此类尚未装配到路由或授权服务；当前欠缺的是既存外部 OIDC/账号/学校接口核验与 DeepTutor 自有 OMS 权限及目标绑定实施，而非等待发送端 `ops.*` relation；绝不以“JWT 验证通过”视作跨租户写权。TDD 红灯为 `ModuleNotFoundError: deeptutor_enterprise.oms`（7 项）及新增 HTTPS/JWKS 同源负例 1 项，绿灯命令 `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_oms_platform_identity.py --tb=short` 为 **10 passed**，含错 audience/azp/issuer、空 subject、ID token `typ`、未来 `iat`、篡改签名、HS256 混淆与异源 JWKS 负例。该切片仅覆盖身份断言验证，不满足任务 4.2 的完整权限/角色迁移验收。

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

供给登记证明现有 `Database.transaction()` 只接受 `TenantScope`，不能把平台全局供给事务伪装成目标租户用户；因此新增最窄的 upstream-neutral `GlobalScope` 数据库范围，沿用同一连接池、受限 PG role、超时、事务和取消保障，但将 `app.tenant_id` 置空，使所有 tenant RLS 表不可读。它**不是身份或权限证明**，只能在未来平台动作鉴权后由企业扩展调用；核心只改 `scope.py` 与 `connection.py` 的范围类型，不改 orchestrator/路由/会话。`test_global_scope_cannot_read_tenant_rls_and_does_not_leak_on_pool_reuse` 红灯为缺 `GlobalScope`，绿灯与完整 core PG connection 测试 **59 passed**；企业 suite **332 passed、3 skipped**。受影响入口是使用同一 `Database` 的 CLI/HTTP/WS/SDK/后台 PG 调用，现有 `TenantScope` 分支未变；仍需本地/企业各入口执行 smoke、当前 upstream merge 审阅和完整平台授权负例才能勾选 3.2。先前 `git merge-base HEAD upstream/main` 与 `git rev-parse upstream/main` 同为 `897fce52f24bf22e6e50d8a3e4df532632a26322`（本地已获取引用的兼容基线），不能以该静态祖先检查代替最终 upstream 兼容验收。

## 6.1 平台权限与全服务配置依赖提案重订（当前修订版复核完成）

`add-b2-oms-platform-read-governance` 曾按 EduPlus2 同时管理平台身份与 OMS 权限的旧目标获批，`add-enterprise-all-service-provider-settings` 的 Provider/连接配置目标亦曾获批；2026-09-26 strict validation 是**旧版文档**证据。2026-09-27 用户确认 DeepTutor Enterprise 程序自主管理仅限本产品 OMS 的 `ops.*` 动作、目标学校授权和撤权，PG 仅存事实，EduPlus2 仅提供既存身份/学校接口，本代理不得修改其仓库。用户随后分别批准 `add-enterprise-management-authorization`、`add-b2-oms-platform-read-governance`、`add-enterprise-all-service-provider-settings` 当前修订版。复核三份 proposal/design 的授权来源、`platform`/`school` 范围、Secret/导出边界、全服务设置、逐实例确认及核心本地设置兼容，并清除直接依赖提案顶部过期的“待重新批准”标记和一处旧双人首管文字；三份 change 均执行 `openspec validate <change-id> --strict` 且返回 valid。此处 6.1 只标记依赖方案重订、批准和文档一致性，不宣称身份接口、应用权限、配置服务或 OMS 写 API 已交付。实际 OMS OIDC/账号在线状态/学校接口和 DeepTutor 应用权限迁移仍待验收，跨学校写 router 继续不装配。

本轮另以 `management/0004_oms_skill_actions.sql` 在本仓库新增五个 `ops.skills.*` 动作及三个角色的 v2 候选模板，**不自动给已有主体或 assignment 升权**；`MigrationRunner.verify()` 复核目录状态/范围与模板，校验失败关闭。隔离临时 PG 定向迁移测试为 **24 passed**，含新动作/模板、重复 apply、默认零权、目录退役漂移，以及受 FORCE RLS 限制的数据库 owner 迁移。此迁移只完成 Skill 权限事实目录的一部分，不代表 3.2 的统一 PEP、6.5 的 Skill 持久化/审核/运行时过滤或任何正式 API 已完成。

Skill ZIP 纯校验器现从唯一 `SKILL.md` 额外解析 `tags`、布尔 `always` 与 `requires.bins/env/sandbox`，而不把字符串等错误类型当作真值或将错误依赖忽略。新行为测试先见 8 个失败，再实施严格解析；定向 `test_oms_skill_package.py` **26 passed**。包仍未持久保存、服务端审查或接入企业运行时，6.5 继续未勾选。

本轮所有代码改动后的企业测试全量重跑为 **515 passed、3 skipped**（隔离合成 PG）；`ruff check`/`ruff format --check` 覆盖受影响 Python 文件，`openspec validate --all --strict` 为 **29 passed、0 failed**，`git diff --check` 通过。最终企业 wheel 构建并核对包含 `management/0004_oms_skill_actions.sql` 与更新后的 Skill 包校验模块。未对真实学校/供应商执行调用，未部署、提交或推送。

## 7.1 统一总账契约与旧财务目标退役（门禁完成）

`add-enterprise-exact-token-usage-ledger` 已将旧逐 Token 目标正式重订为 Token 与非 Token 原生单位共享的逐 attempt 证据、上界预留、远端未知待核对与幂等结算；proposal/design/spec/tasks 均重写并获用户单独批准。`add-oms-token-billing-and-arrears` 的旧租户售价/账单/欠费目标获用户**退役批准**，没有运行其 tasks、归档或同步冲突旧 spec。用户对本 OMS change 的实施授权涵盖供给批次、同表 `gift|recharge` 授予、可信消耗、仅 OMS 可见的供应商成本证据以及版本化 PG 迁移；前述 `0001`–`0006` 基础迁移由 `MigrationRunner` 管理 checksum、plan/apply/verify，隔离 PG 测试 10 项通过。迁移/代码中没有租户售价、费用、欠费或独立欠费资格字段；OMS-only 成本凭据与核定视图仍属于 7.6 的后续迁移/实现，不以缺凭据推断零成本或租户费用。

因此勾选 7.1 只表示**替代方案与基础迁移门禁获批、旧目标不再执行**。未进行真实租户数据迁移、外部权限迁移、生产部署或旧 change 归档；供给登记/采购、租户权益运营写入、真实执行者准入、可信核对和成本视图仍由 7.2–7.7 验收，不能凭总账表存在放行。

## 7.2 供给批次与可授予量（内部事务完成；未开放采购 API）

`oms/supply.py::OmsSupplyLedger` 在全局非租户范围登记原生单位供给批次、来源引用、provider/account/兼容池、有效期、核验标志和操作者；同一 lot ID 仅能重放完全相同的业务载荷，冲突拒绝。撤销采用版本条件和与授予/预留相同的池 advisory 锁，写追加审计并阻断新准入，既有终身计数不抹除。`available()` 只合计当前有效、active、`native_units` 且有 `verified_at` 与有限硬上界的匹配批次。`0007_supply_evidence.sql` 对来源类型、核验状态与上界设置 CHECK；历史行默认待核对，不自动取得授予资格。`OmsGrantLedger.grant()` 与 `OmsAttemptLedger.reserve()` 同时要求已核验有限批次，金额、credits、paygo 的无可信原生上界批次不能硬授予或开启新调用。授予继续以池锁和批次行锁事务分配，不晚于供给有效期，硬上界 CHECK 防止累计结算、未用承诺与在途预留超出容量。

隔离 PG 合成 `test_oms_supply_ledger.py` **9 passed**：批次登记重放/冲突、已停用服务仍可幂等重放但不得新登记、版本撤销、无原生上界的三种来源拒绝硬额度与新 attempt、畸形容量/标志拒绝、未核验和过期批次拒绝授予/新调用、6 单位远端未知预留在批次过期后仍留账、迟到可信回执结算 5 单位后保留历史 5 与未用承诺 14、授予期限长于批次拒绝、两笔并发各授予 20 对容量 30 仅一笔成功。迁移定向测试检查 `0007` 重复 apply 与约束 drift 阻断，`test_persistence.py` 的迁移序列同步更新。完整企业测试 **332 passed、3 skipped**，核心 PG connection 测试 **59 passed**；所有测试仅合成临时 PG。企业 wheel 构建与压缩包读取已确认包含 `oms/supply.py` 和 `0007_supply_evidence.sql`。`verified_native` 是内部供应证据复核结果字段，当前没有对外可写路由，也**不能**把客户端 boolean、JWT role 或未经核验的凭据直接写为已核验；真实采购凭据/操作者动作权限与供应商证据适配仍需 4.2、6.2、7.6/7.7 门禁，真实执行边界接线属于 7.4。

## 本轮隔离验证快照

### 7.3 到期释放切片（仍未完成整项）

`OmsGrantLedger.expire()` 新增带 `expected_version` 和幂等键的到期事务：到期前拒绝，到期后将该 grant 尚未使用的承诺从各支撑批次释放，保留已发出且结果未知的 attempt 预留，待迟到可信 usage 按原分摊结算；自然到期与人工撤销分别写 `quota.expire`/`quota.revoke` 追加审计。`0008_quota_expiry.sql` 增加 `expired` 状态，迁移校验覆盖状态约束漂移。隔离 PG 合成测试覆盖到期前拒绝、重复命令不双放、版本冲突、过期后迟到结算与账面不变量。完整企业测试本轮重跑 **335 passed、3 skipped**；企业 wheel 已确认包含 `0008_quota_expiry.sql`。服务授权的正式管理、额度调整和经平台权限守门的对外 API 尚未实现，因此 **7.3 不勾选**；此内部函数不得当成已授权平台入口。

`OmsEntitlementLedger.set()` 进一步增加服务授权 active/revoked 的内部版本化幂等事务及追加审计，撤销不重写既有 grant/attempt；再次启用被撤销授权时，如果存在尚有效的旧 active grant 则拒绝，避免旧额度在恢复授权后意外复活。`0009_entitlement_commands.sql` 的命令行按目标学校 FORCE RLS；另一学校的相同操作者 scope 无法读取记录。隔离 PG 测试覆盖创建→续期→撤销、同键重放/异载荷冲突、旧版本拒绝、旧 grant 复活负例和跨学校 RLS；完整企业 suite 重跑 **338 passed、3 skipped**。此类仍是**内部事务**，没有 OMS 平台身份/逐动作检查、正式 API 或额度调整，7.3/5.2 仍未完成。

`OmsGrantLedger.adjust()` 再增加正/负额度调整：版本 CAS 和操作者/动作/幂等键固定结果；正向仅从同池、同原生单位、仍有效且已核验的有限批次增加承诺，容量不足记录脱敏 denied 审计且不留部分账；负向只释放未用承诺，以 `0010` 的累计释放列保留原总承诺及在途/已结算事实。合成 PG 测试覆盖 20→25→15、重复/异载荷重放、容量不足重放、旧版本、调整后撤销，以及 6 单位在途预留时过度下调拒绝、合法下调后迟到结算。定向账务/迁移回归 **64 passed**。这仍是**内部事务**，未提供正式平台权限/API；7.3 继续未勾选，上段“额度调整尚无实现”是此切片之前的历史快照。

本切片完整企业 suite 重跑 **341 passed、3 skipped**；`ruff check` 与本轮调整文件 `ruff format --check` 通过，企业 wheel 构建并检查包含 `oms/ledger.py` 与 `0010_quota_adjustment.sql`。未接入真实执行者或开放 OMS 写 API。

**2026-09-27 职责边界更正：**此前曾在同机 EduPlus2 工作树编写 `add-deeptutor-oms-platform-contract` 及其发送端代码，但用户明确该仓库属于另一团队、严禁本代理修改，故全部发送端工作树改动已撤销。此前发送端单元测试、临时 PG 测试和 OpenSpec 验证仅是已撤回草稿的历史记录，**不是当前发送端交付或可调用契约证据**；未执行真实 provider migration、真实学校数据操作、提交、推送或发布。当前方案只读核实 EduPlus2 既存 OIDC client/audience、账号在线状态与学校核验能力；OMS 逐动作/目标学校授权和撤权版本由 DeepTutor 自行迁移实现。缺外部既存接口时由 EduPlus2 团队独立补足，本系统不得越界代做。DeepTutor OMS 跨学校写路由继续关闭。

跨学校目标 ID 还需显式绑定：已撤回的发送端草稿曾设想授权 API 的 `targetTenantId` 使用学校数字 ID，但**这不是已交付的外部契约**；DeepTutor `enterprise.tenants.id` 与 OMS 总账 scope 是内部 UUID，已有 `external_tid` 为可空文本，既无数字格式也无唯一/已核验的 OMS 绑定约束。因此消费端不得把 UUID、`schoolCode` 或客户端传值直接转换为发送端目标 ID；须依据 EduPlus2 团队正式契约建立版本化、唯一、经权威核验的学校绑定及受控创建/核对，再接在线决策和账务事务。当前没有这条绑定路径，属于 4.2/7.7 的未完成门禁。

已新增 `oms/migrations/0011_school_binding.sql` 建立空的显式映射表：内部 UUID 与 EduPlus2 数字学校 ID 一对一，`verified` 必须有验证时间/操作者，默认 pending，无历史数据自动回填；迁移校验覆盖唯一性/正数/验证状态约束。隔离 PG 测试证明没有自动绑定、重复 EduPlus2 ID 被拒绝、约束漂移阻断 verify。**尚无经 EduPlus2 权威核验的创建/撤权流程或账务事务内绑定版本栅栏，因此该 schema 不代表目标学校绑定已可用。**

其后新增 `oms/authorization.py::OmsPlatformAuthorizationClient` 内部消费切片：先由独立 OMS OIDC/JWKS verifier 验证 access token 的主体/client/audience，再以原始 Bearer token 对发送端固定 HTTPS 路径逐次 POST 动作、EduPlus2 数字学校 ID 和关联 ID；不提交调用方自报主体/角色，不跟随 302，不缓存允许结果。仅接受主体/目标回显一致、正数版本、UUID 决策 ID、带时区且仍有效的短期 200/allowed 决策；403、503、重定向、畸形/过期响应均失败关闭。合成 HTTP 单测 **5 passed**。该客户端基于已撤回的发送端专有授权端点，仍未装配且**不再适合作为现行方案的生产授权后端**；后续应在本仓库用 DeepTutor 自有权限服务替换或受控移除。绑定表亦缺权威核验与版本复核，不能据此开放写入。

加入授权客户端后完整企业 suite 重跑 **348 passed、3 skipped**；wheel 构建确认包含 `oms/authorization.py` 和 `0011_school_binding.sql`，OpenSpec strict validation 与 `git diff --check` 通过。先前 **343 passed** 是此模块加入前的快照。

加入 `0011` 后完整企业 suite 重跑 **343 passed、3 skipped**；wheel 构建确认包含 `0010` 与 `0011` SQL，`ruff check`/本轮改动文件格式检查、`openspec validate add-enterprise-oms-business-logic --strict` 与 `git diff --check` 均通过。先前 **341 passed** 是加入 `0011` 之前的快照。

- `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short`：**338 passed，3 skipped**（2026-09-26，临时 PG/合成数据；不含真实 EduPlus2/供应商或生产环境）；`tests/persistence/postgres/test_connection.py` 上一切片 **59 passed**，本轮未重跑。
- OMS supply 定向 **9 passed**，attempt 定向 **11 passed**，迁移定向测试覆盖 `0001`–`0007`；不与完整企业测试重复相加。中途首次全量企业测试因 `test_persistence.py` 预期迁移清单漏列新 `0007` 出现 30 个同源断言失败，补齐清单后完整重跑为上述结果，并非跳过失败。
- `openspec validate add-enterprise-oms-business-logic --strict` 通过；`ruff check`、本轮新文件的 `ruff format --check` 与 `git diff --check` 通过。企业 wheel 构建通过，确认包含 OMS 供给服务与第七版 SQL；完整旧七 change strict 验证和此前包含六版 SQL 的 wheel 是历史快照，不把旧命令冒充本轮重跑。
- 仓库根目录 `.venv/bin/python -m pytest -q --tb=short` **未进入执行阶段**：收集时 `tests/multi_user/conftest.py`、`tests/services/session/conftest.py` 的非顶层 `pytest_plugins` 与当前 pytest 不兼容，且可选伙伴依赖 `slack_sdk`、`telegram` 缺失，计 4 个 collection error。此问题不影响上述独立企业与 core PG 定向结果，但根测试套件不能宣称通过。
- 进一步尝试 `.venv/bin/python -m pytest -q tests/persistence/postgres --tb=short`，发现未改动的 `business/test_externalized_turn_attachments.py` 两个断言失败（ObjectStore 错误预期与 `FakeWebSocket.headers` 缺失），`business/test_learning_runtime.py` 的 async fixture 在当前 pytest/pytest-asyncio 配置下发生 19 个 setup error；为避免同源错误继续刷屏，中断时为 **2 failed、45 passed、2 skipped、19 errors**。这些不属于本轮 `GlobalScope` 修改路径，不能把更宽 core PG 套件报告为通过，后续须单独修复测试环境/原有失败。
- 受保护启动/管理入口定向 31 项及本地设置/CLI/SDK 定向 4 项通过；`ruff check` 覆盖本轮新测试，`ruff format --check` 覆盖两份新测试，`bash -n deploy/docker-runtime/start-backend.sh` 通过。受保护镜像/脚本/部署模板改变只做静态和合成 shell 验证，未实际构建/发布镜像。
- 2026-09-27 权威修订后、6.1 重审前的 `openspec instructions apply --change add-enterprise-oms-business-logic --json` 历史快照为 **7/23，尚有 16 项未完成**；6.1 当前复核结果见下文，不能用历史数字覆盖当前进度。7.2 仅标内部总账事务门禁，不能越过 4.2、7.4、7.7 开放平台采购或服务新调用。EduPlus2 发送端改动已撤销；正式跨学校写 API 继续未开放；无真实 tenant 数据迁移、生产发布或归档。此前 test-cn Webhook mock 联调不等于 G2/G3 或 OMS 生产放行。

## 发送端前置联调状态（2026-09-27，更正）

先前 2026-09-26 在 EduPlus2 工作树中的 OMS tuple 投影、目标学校授权 API、Flyway/OpenFGA/Keycloak 草稿与测试已全部撤销，不再构成联调切片或交付证据。DeepTutor 不再要求发送端新增 OMS 权限 API；本代理只在本仓库开发 OIDC 身份消费、OMS 应用权限、学校绑定及业务代码。既存外部身份/账号/学校接口未核实、本地权限未验收前，已撤回的发送端授权客户端继续未装配且 OMS 写路由关闭。任务 4.2 和 7.7 不勾选，不能据此授权真实学校或发布写入。

## 2026-09-27 权威修订版逐项批准

用户已单独批准本 change 的 2026-09-27 权威拆分修订版；`add-enterprise-management-authorization`、`add-b2-oms-platform-read-governance` 和 `add-enterprise-all-service-provider-settings` 当前修订版亦分别获批。6.1 只要求这些依赖提案重审、权威边界与 Secret/导出、全服务 Provider 入口保持一致，故重新勾选，进度 **8/23**。批准不等于已交付 OMS client/audience、在线账号/学校核验或正式业务 API；4.2、6.2–6.5、7.x 相应未完成，跨学校写路由继续关闭，不修改 EduPlus2 或触碰真实学校数据。

## 2026-09-27 已撤回发送端授权客户端清理

`oms/authorization.py::OmsPlatformAuthorizationClient` 仅服务于已撤回的 EduPlus2 专有在线权限端点和 `oms:*` 动作，与已批准的 DeepTutor PG `ops.*` 权威冲突。删除该未装配模块及旧合成测试，新增入口负例固定不可导入；先红后绿，OMS 入口/OIDC 身份定向 **13 passed**。`oms/identity.py` 的 OIDC 验签能力仍只验证身份，不产生任何本产品权限；正式写 API 继续关闭，4.2/7.7 不据此勾选。

## 2026-09-28 正式 OMS 身份与全局模型草稿切片（任务未整项完成）

- 企业 HTTP 装配新增精确的 `/api/v1/oms/me`、`GET /models`、`GET|POST /models/draft`；OMS Bearer 不再被租户 `dt_token` 中间件误当成个人会话，缺 Bearer、错误令牌、停用平台账号、无本产品动作授权分别失败关闭。`PlatformOidcJwtVerifier` 只给出受信 issuer/sub/client 身份；`trusted_oms_identity_from_token` 还要求显式装配的**在线账号状态检查器**并查本仓库主体 policy version。所有 OMS 动作由 `require_management_permission` 判定，写草稿时与 CAS 和追加审计在同一 PG 事务内再次核验；安全管理员有 `ops.oms.access` 但无 `ops.providers.read/manage` 时仍为 403。默认不装配外部 verifier/账号状态检查器，目标环境未核实 `eduplus-platform-admin` 的真实换票/在线接口前受保护入口为 503，**不能算正式登录验收**。
- `oms/0013_global_model_catalog.sql` 仅建全局模型草稿/旧 active 字段，不从租户或部署配置回填，不在 migration 中自动赋权。`POST /models/draft` 只接收符合 `ModelDeployment` 和 `env:` Secret 引用的模型，按 `expected_version` CAS，重复旧版本返回 409；响应/只读草稿 DTO 和审计不回显 Secret 引用或 endpoint。迁移可重复 apply/verify、状态约束 drift 检查已覆盖。运行时修正了现有 `load_runtime_model_deployments` 在 `status=saved` 时错误读取 `desired` 的旁路：现在未发布草稿不参与执行，已有 `active` 保持不变；若无 active，继续使用部署基线。旧测试维护 helper 仍属内部代码，非 OMS 发布入口。
- 先红后绿定向身份、权限、草稿、迁移和运行时负例；完整企业套件本轮 **521 passed、3 skipped**，`ruff check` 和受影响文件格式检查通过。全部只使用临时 PG 合成数据。**此切片尚无 OIDC 授权码/服务端 OMS 会话、真实在线账号适配、受控首管理员、配置测试/目标执行者确认/发布/回退、Skill 存储与执行过滤、独立正式前端、服务准入/用量和 test-cn 真实联调。**所以 4.2、6.2–6.5、7.4–7.7 均不勾选，OMS 仍为 **8/23**；草稿不可作为首个 Agent 的 active 模型。
- 本轮企业 wheel 无隔离构建通过，包内确认包含 `oms/model_drafts.py`、`oms/identity.py` 与 `oms/migrations/0013_global_model_catalog.sql`；两份相关 OpenSpec change strict validation 和 `git diff --check` 通过。根仓库 `.venv/bin/pytest -q --tb=short` 仅在收集阶段中止：两处非顶层 `pytest_plugins` 与当前 pytest 不兼容，另缺可选 `slack_sdk`、`telegram`，共 4 个 collection error；不能宣称根套件通过。

## 2026-09-28 4.1 生命周期与 OMS 权威边界核对

`add-b2-eduplus2-tenant-lifecycle-webhook` 的已验签 Webhook-only 修订版已把订阅事件持久化于 `eduplus2.lifecycle_inbox`，按学校/应用 generation 投影至 `eduplus2.webhook_school_state` 与 `enterprise.tenants.external_eligibility`；同步异常、冻结、久未投递只作为诊断/保守门禁，不凭 OMS 额度或后台按钮改写外部订阅。`local_enabled`/资源 ready 与外部资格独立。当前正式 OMS 路由只含主体、模型草稿与 Skill 草稿，无订阅开停 API；OMS 供给、grant、attempt 服务不写 `external_eligibility` 或发送 `tenant.suspended`。额度不足的合成负例在 `OmsAttemptLedger.reserve()` 返回 `QuotaUnavailable` 后核对学校资格、本地开关、认证 epoch 均不变；OMS `/me` 与生命周期投影/学校管理路径均不读取 quota ledger。`test_lifecycle_reconcile.py` 全文件与额度边界负例 **40 passed**，仅临时 PG/合成事件；已部署 test-cn 的真实 Webhook 验收仍以 lifecycle change 自身证据为准。此项完成的是跨 change 边界核对，不放行 OMS 跨学校写入，也不表示漏送事件可被自动纠正。

## 2026-09-28 Skill 不可变草稿的独立切片（6.5 仍未完成）

`oms/0014_skill_packages.sql` 新建分 `global`/`tenant` owner 的版本、发布指针和学校授权表，全部无默认 publication/grant；当前应用层只有追加新修订的入口，尚无更新/删除入口。`upload_global_skill()` 仅接收经服务端 `SKILL.md`/ZIP 验证的完整包，以不可变对象键存 ObjectStore、版本 CAS/本产品 `ops.skills.manage` 事务复核及脱敏审计保存待复核草稿。正式 `POST /api/v1/oms/skills/draft` 先鉴权再解析 multipart，拒绝无权者、大包、非法 ZIP 和旧版本；响应不含对象键或内容。对象上传后 PG 再次校验失败可能留下不可访问孤儿对象，后续需受控 ObjectStore 对账；草稿未审查、发布、授予或进入任何运行时 Skill 解析。按新的仓库规则，撤回了本轮新增的数据库函数/触发器及 `0015_skill_owner_guards.sql`；owner/发布/授权的一致性必须在后续应用层事务中校验，不能凭 DB 函数放行。此前带函数版本的测试数字是历史快照，不代表当前验证结果。这不是 6.5 的完成证据，更不能让首个 Agent 使用该草稿。

## 2026-09-28 OMS 模型发布与授权 Skill 运行时切片（6.3/6.5 仍未整项完成）

- 在 `POST /api/v1/oms/models/publish` 增加草稿发布事务：平台主体仍须通过 OMS Bearer、在线账号状态检查和本仓库 `ops.providers.manage`；发布命令使用 `expected_version` CAS，先把草稿转换为 `ModelDeployment` 并调用当前 backend 配置解析，确认 Secret 引用可由执行者装载后，才写入 `oms.model_catalog_config.active` 与 `enterprise.runtime_settings.active`，并追加脱敏审计。`GET /api/v1/oms/models` 现在优先展示已发布 active 的脱敏模型，否则只展示部署基线；Secret ref 与 endpoint 不进入响应。学校 scope 在无本校 active 设置时会读取 OMS global active，草稿 `status=saved` 仍不会参与运行时。
- 新增企业 Skill 运行时组合服务：企业 `ApplicationProviders.skill_service_factory` 装配 `EnterpriseRuntimeSkillService`，学校本地动态 Skill 继续走 PG/ObjectStore，OMS global Skill 只在学校显式 grant、发布版本、独立 review、生命周期/绑定状态均通过 `resolve_authorized_global_skill()` 时出现在 manifest、`read_skill`、`load_for_context` 与 `always` 注入中。同名学校 Skill 优先于 global；未授权 global 不可见。随程序打包的 builtin Skill 在企业学校运行时默认不可见且禁止以同名创建/覆盖，后续仍需独立的打包版本授权目录；本地 DeepTutor 非企业默认 Skill 行为未改。
- 先红后绿验证：模型发布新增测试先失败于 `/models/publish` 404，后验证发布结果、active runtime、脱敏响应和学校 scope global fallback；Skill runtime 新测试先失败于缺 `runtime_skills` 模块，后又以 builtin 未授权仍可见、同名 builtin 可创建为红灯，最终验证未授权 builtin 隐藏、global grant 后可读/always、生效依赖不足标记仍走 core availability、本校同名覆盖优先。
- 本轮定向验证通过：`test_oms_skill_runtime.py`、`test_oms_skill_store.py`、`test_oms_skill_package.py`、`test_oms_builtin_skill_readonly.py` 共 **47 passed**；模型/对话选项定向 **8 passed**；联合关键用例 **4 passed**。完整企业扩展套件 `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short` 重跑为 **753 passed, 3 skipped, 2 warnings**（两个既有非 async 测试继承全局 asyncio mark 的 PytestWarning）；`ruff check`/`ruff format` 已覆盖本轮改动文件。全部仍为隔离临时 PG/ObjectStore 合成数据，未调用真实供应商、未部署 test-cn、未触碰真实学校数据。

限制：6.3 仍缺多执行者逐实例确认、配置测试探针、部分确认/超时失败保留旧 active 的完整状态机、正式回退 API 与独立 OMS 前端；6.5 仍缺 builtin 打包版本授权目录、TMS tenant owner 管理、ObjectStore 孤儿对账和 test-cn 真实学校/受控服务主体运行验收。因此不勾选 6.3 或 6.5；`add-enterprise-oms-business-logic` 当前仍按 OpenSpec tasks 为 **9/23**，不是完整 OMS 交付。

## 2026-09-28 OMS 服务授权与额度 API（7.3 完成；仍未开放真实执行）

本轮把此前仅内部可调用的服务授权与额度总账接入正式 OMS 受保护 API：新增 `/api/v1/oms/schools/{school_id}/entitlements/{service_id}`、`/quota`、`/quota-grants`、`/quota-grants/{grant_id}`、`/revoke` 与 `/expire`。所有学校级写入口先通过 OMS Bearer、在线账号状态与本产品 `ops.oms.access`/目标学校权限，再在同一个 `TenantScope` 账务事务内由 `require_management_permission(..., write=True, _lock_school_id=school_id)` 复核 `ops.entitlements.manage` 或 `ops.quotas.manage`，并复用已验证的 school binding / lifecycle / local ready 门禁；租户 `dt_token`、伪造 header、平台无学校授权或漂移绑定不能进入账务写入。响应只返回服务、额度、版本、状态、分配和 `source_ref_hash`，不回显供应来源、Secret、成本或外部凭据。

新增 API 集成测试先红于 404，后验证：目标学校显式绑定与 school-scope `platform_operator` 授权后可创建服务授权；旧 `expected_version` 返回冲突；同一列表中赠送额度授予、下调、人工撤销和自然到期释放均落入真实 `oms.quota_grants`/`oms.grant_commitments`/`oms.supply_lots`，操作审计包含 `service_entitlement.set`、`quota.grant`、`quota.adjust`、`quota.revoke`、`quota.expire`，未使用承诺最终释放为 0，响应与审计不泄露 `source_ref` 明文。已有 `test_oms_attempt_ledger.py` 继续覆盖赠送优先消耗、未知远端结果保留预留、迟到 usage 结算与防双扣；`test_oms_grant_ledger.py`/`test_oms_entitlement_ledger.py` 覆盖幂等、容量不足 denied、调整/撤销/过期版本冲突与账面不变量。

定向验证：`ruff check` 覆盖 `api/application.py`、`oms/entitlements.py`、`oms/ledger.py` 与 `test_application.py`；`ruff format` 覆盖上述改动。`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_school_entitlement_and_quota_commands_are_authorized_and_audited extensions/enterprise/tests/test_application.py::test_enterprise_management_route_allowlist_is_narrow extensions/enterprise/tests/test_oms_entitlement_ledger.py extensions/enterprise/tests/test_oms_grant_ledger.py extensions/enterprise/tests/test_oms_attempt_ledger.py --tb=short` 为 **26 passed, 1 warning**（既有全局 asyncio mark 作用于同步 allowlist 测试）。全部仍为隔离临时 PG/合成学校与供给数据；未调用真实供应商、未使用真实学校业务数据、未部署、未发布。7.3 勾选后，本 change 进度应为 **10/23**；7.4/7.5/7.6/7.7 仍未完成，不能据此发起真实 Agent 可计费调用。

## 2026-09-28 OMS 平台资源安全状态 API（6.2 完成；不做发布确认）

新增 `oms/resource_status.py` 与 `GET /api/v1/oms/resources/status`，由正式 OMS Bearer、在线账号状态和 `ops.providers.read` 保护；API 从当前部署描述符和已发布 OMS active 模型生成五类平台资源状态：`model_external`、`agent_capability`、`tool_integration`、`knowledge_content`、`runtime`。返回字段只包含 `id/category/kind/status/managed/display_name/safe_fields`，显式排除 Secret ref、明文 Secret、endpoint/base_url、对象存储地址、LightRAG 地址和租户正文。

状态映射覆盖任务要求的条件字段：模型描述符含 chat model、task 缺单独配置时回退 chat model；embedding 明确完整 HTTPS endpoint 契约；TTS/STT、image/video 均标注原生单位和异步/usage 证据来源但在未配置时为 `not_configured`；search 标注 provider usage 或调用次数来源且无可信硬上界时不开放硬额度；解析/RAG 显示 LightRAG workspace/index/contract 及对象存储是否配置；外部 Agent、global Skill、MCP/外部工具均只显示需要 OMS descriptor、学校授权或租户绑定的条件，不将本地 Web 设置或旧 core 管理页面提升为云端配置权威；runtime 标注 PostgreSQL-only、ObjectStore、SecretProvider 和当前单实例 executor 非 HA。

TDD 红灯为 `/api/v1/oms/resources/status` 404，绿灯 `test_oms_resource_status_maps_platform_categories_without_secrets` 验证五类分类顺序、部署模型脱敏、LightRAG/对象存储安全字段、search、task fallback、embedding、TTS/STT、image/video、外部 Agent、MCP 与 runtime 状态；同时断言 `DT_TEST`、`objects.example`、`lightrag.example`、`model.example` 不在响应中。定向验证：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_resource_status_maps_platform_categories_without_secrets extensions/enterprise/tests/test_application.py::test_oms_model_inventory_requires_provider_read_and_redacts_credentials extensions/enterprise/tests/test_application.py::test_enterprise_management_route_allowlist_is_narrow --tb=short` 为 **3 passed, 1 warning**（既有全局 asyncio mark 作用于同步 allowlist 测试）；`ruff check`/`ruff format` 覆盖新模块、API 与测试。此项不执行真实 provider 探针、不改变 runtime active、不开放旧设置旁路；6.3 的测试/发布/逐实例确认仍需单独完成。

## 2026-09-28 单实例运行边界（8.1 完成；未启用多实例 HA）

当前企业部署模型仍是单 backend executor：`DeploymentConfig.backend_workers` 为 `Literal[1]`，默认 memory coordination 时 `Enterprise.authorize()` 继续持有单执行者 PG advisory lease；`DEEPTUTOR_BACKEND_WORKERS>1` 且未配置 Redis coordination 会失败关闭。OMS 资源状态 API 的 `runtime:executor` 明确返回 `status=single_instance`、`backend_workers=1`、`ha=false`，作为平台可见的容量/可用性边界。容量目标是单 backend 进程/单执行者吞吐，故不声明横向扩展能力；恢复目标是进程重启后由既有 PostgreSQL 持久状态、usage attempt 的 unknown/reconcile 状态和配置 active 版本保守恢复，不能在新实例就绪前接流量或把多实例一致性视为已验证。

定向验证：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_enterprise_runtime_coordination.py extensions/enterprise/tests/test_application.py::test_oms_resource_status_maps_platform_categories_without_secrets --tb=short` 为 **6 passed**，覆盖默认 memory coordination 隔离、多 worker 无 Redis 拒绝、Redis coordination 禁用 singleton lease、Redis recovery 不 bulk-fail 其他 Pod 的 live turn，以及 OMS 状态 API 明示非 HA。多实例路径仍需另按 G-H 验证准入/预留/结算、配置版本传播、取消/重试幂等和故障恢复；本项完成的是单实例边界声明，不代表 test-cn 或生产已具备 HA。

## 2026-09-28 模型配置测试与逐执行者确认切片（6.3 仍未整项完成）

在既有 `draft/publish/rollback` 基础上新增 `POST /api/v1/oms/models/test`，使用同一 OMS Bearer、在线账号状态和 `ops.providers.manage` 保护。`test_global_model_catalog()` 在账务事务内读取指定版本草稿，按 `enterprise.oms_model_publish_executors` 逐目标执行者执行真实模型配置解析，并支持受控 `oms_model_confirmation_hook` 模拟后续实例确认；测试成功只把目录状态推进为 `tested`，不写 `active`、不写 runtime settings，因此不会让首个 Agent 或普通学校 runtime 误读草稿。发布路径也复用同一逐执行者确认函数；既有缺 Secret 失败场景仍返回 503、记录 `failed` 并保留旧 active，随后可由 `/models/rollback` 丢弃坏草稿。

TDD 红灯为 `/api/v1/oms/models/test` 404；绿灯 `test_oms_model_test_confirms_target_executors_without_activating` 覆盖 `backend` 与 `canary` 两个目标执行者均被确认、状态变为 `tested`、`GET /models` 仍展示 deployment 基线而不是草稿、`active` 仍为空。回归命令 `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_model_draft_is_versioned_audited_and_never_active_without_publish extensions/enterprise/tests/test_application.py::test_oms_model_test_confirms_target_executors_without_activating extensions/enterprise/tests/test_application.py::test_oms_model_publish_confirms_backend_and_becomes_runtime_active extensions/enterprise/tests/test_application.py::test_oms_model_publish_failure_keeps_active_and_rollback_discards_bad_draft extensions/enterprise/tests/test_application.py::test_enterprise_management_route_allowlist_is_narrow --tb=short` 为 **5 passed, 1 warning**（既有全局 asyncio mark 作用于同步 allowlist 测试）；`ruff check`/`ruff format` 覆盖模型草稿服务、API 与测试。限制：当前仅覆盖模型目录，未覆盖 search/embedding/TTS/STT/image/video/解析/RAG 等全服务配置草稿与探针，也未接入独立 OMS 前端的待生效/错误态，因此 6.3 暂不勾选。

## 2026-09-28 本轮完整企业回归与 upstream 状态

本轮新增资源状态 API、OMS 服务授权/额度 API、模型测试/逐执行者确认后，完整企业扩展测试重跑：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short` 为 **757 passed, 3 skipped, 2 warnings in 253.11s**（两个既有同步测试继承全局 asyncio mark 的 PytestWarning）。`ruff check`、`ruff format --check` 覆盖 10 个本轮变更 Python 文件，`openspec validate add-enterprise-oms-business-logic --strict` 通过；`git diff --check` 无输出。入口/CLI/SDK/后台 smoke 定向 `test_oms_management_entrypoints.py`、企业 route allowlist、Skill runtime 为 **5 passed, 1 warning**；WS/lifecycle 与 flow 定向为 **13 passed**。

`git rev-parse --verify upstream/main` 当前为 `a053fecf6eeca51ded680de8b8fc41ef63857b11`，而 `git merge-base HEAD upstream/main` 为 `897fce52f24bf22e6e50d8a3e4df532632a26322`，说明 upstream 已前进且本轮尚未执行真实 merge/rebase 兼容验收；因此 3.2 仍不勾选。当前 OpenSpec 进度为 12/23：本轮完成 6.2、7.3、8.1；6.3 仅新增模型测试切片但未覆盖全服务配置/独立前端；4.2、5.1、5.2、6.4、6.5、7.4–7.7 仍待真实身份/学校接口、TMS/OMS 前端、全服务执行/用量/成本与 test-cn 端到端联调。后续 5.1 已于下文完成，进度更新为 13/23。

## 2026-09-28 TMS 当前学校配额只读投影（5.1 完成；不含完整 TMS 前端）

新增 `GET /api/v1/tms/quotas` 作为学校侧只读配额安全 DTO：入口不复用租户 `dt_token`，而是沿用 TMS bootstrap 的 EduPlus2 OIDC 验签、Webhook-only 学校绑定、active client、已完成 onboarding 与本仓库 `management.principals`/`tenant.*` 授权事实；服务端仅从已验证身份得到当前 `school_id`，不读取 URL/body/header 中的 tenant 目标。事务内依次复核 `tenant.tms.access`、`tenant.quotas.read` 与 `tenant.usage.read`，再返回当前学校的 service entitlement、grant 与 usage 汇总。DTO 保留服务 ID、单位、获取方式、数量、状态、版本、有效期、attempt 计数及原生单位汇总；显式不返回 provider/account/pool、采购凭据、`source_ref`/hash、模型/endpoint、供应商成本、Secret 或跨学校字段。TMS 下没有额度新增、充值、调整、撤销、过期、手工核销或用量修改 API；配额写入仍只存在于 OMS 受保护路由。

TDD 红灯为 `/api/v1/tms/quotas` 使用已完成本人激活的学校账号访问时返回 401（路由未开放）；绿灯 `test_tms_quota_summary_is_current_school_read_only_and_redacted` 通过真实签名 Webhook 创建学校、本人激活首位 TMS 管理员、写入隔离合成 entitlement/grant/usage 后，验证只读响应绑定当前学校并隐藏 `source_ref`、provider/account/pool、Secret、模型、成本等字段；`POST /api/v1/tms/quotas` 为 405，`POST /api/v1/tms/quotas/grants` 失败关闭且不提供写能力。企业 route allowlist 同步新增唯一 TMS quota 读路由。

定向验证：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_webhook_authority.py::test_tms_quota_summary_is_current_school_read_only_and_redacted extensions/enterprise/tests/test_application.py::test_m1_does_not_expose_tms_or_oms_surfaces extensions/enterprise/tests/test_application.py::test_enterprise_management_route_allowlist_is_narrow --tb=short` 为 **3 passed, 1 warning**（既有全局 asyncio mark 作用于同步 allowlist 测试）。此项完成 OMS change 所需的 TMS 只读 DTO/API 边界，不代表 `add-enterprise-tms-business-logic` 中成员/应用 grant、KB/文档、筛选/详情前端、attempt 分摊明细、导出或真实服务执行结算已完成；5.2、7.4–7.7 仍未完成。

## 2026-09-28 TMS 服务访问 grant 与额度隔离（5.2 完成；不含正式 TMS 页面）

新增 `oms.tenant_service_access_grants` 迁移与 `oms/service_access.py::ServiceAccessLedger`。该表只保存当前学校中成员、应用或服务主体对某个 OMS 已授权服务的访问资格、授权代际、有效期、版本、撤销时间与本地同步状态；迁移只定义物理表、索引与 tenant RLS，不新增数据库函数、触发器、PostgreSQL ENUM 或枚举 CHECK。状态、主体类型、有效期、代际和重复 active grant 均在 DeepTutor 应用事务中校验。

`ServiceAccessLedger.grant()`/`revoke()` 在同一个 `TenantScope` 事务中要求 TMS `ManagementIdentity` 通过 `tenant.access.manage`，并复核学校绑定、本地生命周期、主体 policy version 与对应 `tenant_service_entitlements` 的 active 状态/版本/有效期；创建 grant 时写入 `status=active`、`sync_status=local_ready`，撤销时 CAS 更新版本和 `revoked_at`。该账本只记录调用资格，不调用 `OmsGrantLedger` 或 `OmsAttemptLedger`，不写 `oms.quota_grants`、`oms.grant_commitments`、`oms.usage_attempts`、`oms.attempt_allocations`，也不改变供给批次或额度余额；真实执行仍必须在 7.4 经 OMS 授权、配置 readiness、兼容供给和额度准入。

TDD 红灯为缺少 `deeptutor_enterprise.oms.service_access` 模块；绿灯 `test_tms_service_access_grant_is_permissioned_versioned_and_quota_neutral` 验证：`school_auditor` 无 `tenant.access.manage` 被拒，`school_admin` 可分别给 member/application 创建访问 grant，重复 member grant 冲突，撤销按版本更新；整个过程中 `quota_grants`、`grant_commitments`、`usage_attempts`、`attempt_allocations` 计数保持不变。定向验证：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_tms_service_access_grants.py::test_tms_service_access_grant_is_permissioned_versioned_and_quota_neutral --tb=short` 为 **1 passed**；`ruff check`/`ruff format` 覆盖新增模块、迁移 runner 和测试。此项完成 OMS change 对“服务访问 grant 不是额度”的后端边界证明；TMS 成员/应用管理 API、前端按钮、审计导出与真实执行准入仍由 `add-enterprise-tms-business-logic` 与 7.4–7.7 后续验收。

## 2026-09-28 综合回归与剩余门禁更新

完成 5.1/5.2 后重新执行完整企业扩展回归：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests --tb=short` 为 **759 passed, 3 skipped, 2 warnings in 254.92s**（两个既有同步测试继承全局 asyncio mark 的 PytestWarning）。新增 `0018_tenant_service_access_grants` 后，首次完整回归有 34 个同源失败，根因是 `test_persistence.py` 的期望迁移清单尚未包含 `oms/0018_tenant_service_access_grants`；补齐清单后 `test_persistence.py` **42 passed**，完整企业套件重跑通过。新增迁移定向 `test_tms_service_access_grants.py` + `test_oms_ledger_migration.py` 为 **24 passed**。

本轮 lint/格式/规范验证：`ruff check` 与 `ruff format --check` 覆盖 16 个改动/新增 Python 文件并通过；`openspec validate add-enterprise-oms-business-logic --strict` 通过；`git diff --check` 通过。`openspec instructions apply` 当前进度为 **14/23**。

上游兼容门禁仍未完成：`git merge-tree $(git merge-base HEAD upstream/main) HEAD upstream/main` 对当前 `upstream/main=a053fecf6eeca51ded680de8b8fc41ef63857b11` 显示多处 textual conflict，因此 3.2 不能勾选。4.2/7.7 仍依赖既存 EduPlus2 OIDC/在线账号/学校接口的真实核实与 test-cn 联调；7.4–7.6 仍缺真实 CLI/HTTP/WS/SDK/后台/Agent 执行边界、供应商 usage 核对和 OMS-only 成本视图；6.3 仍缺全服务配置测试/逐执行者确认/独立前端；6.5 仍缺 TMS tenant Skill 管理与 builtin 打包版本授权目录。正式跨学校写入、真实可计费调用和生产发布继续关闭。

## 2026-09-28 任务 6.3：受控配置草稿、执行者确认、发布与回退

完成任务：6.3。

实现内容：

- 模型目录：`oms.model_catalog_config` 与 `/api/v1/oms/models/*` 已支持 draft、test、publish、rollback；发布前通过当前 backend/canary 执行者确认 `env:` Secret 可解析和真实模型配置可装载，失败时保留旧 active。
- 全服务 Provider 设置：`oms.provider_setting_configs` 与 `/api/v1/oms/provider-settings/*` 已支持 legacy JSON dry-run、draft、test、publish、rollback；应用层校验 section 白名单、HTTPS endpoint、Secret ref，不接受明文 Secret；逐执行者确认写入 `provider_setting_confirmations`。
- 权限与旁路：所有写 API 均经 `ops.providers.manage` + `ops.oms.access` 的 DeepTutor Enterprise 本地 PEP；无写权限 403、旧版本 409、坏 Secret/配置 422/503；旧云端 settings/skills/partners 等管理写路由仍未挂载。
- 安全响应：读 API 只返回脱敏 desired/active、安全状态和 descriptor，不回显 Secret ref 明文、环境变量名、供应商密钥或审计中的敏感字段。

验证：

- 模型目录相关测试：`test_oms_model_draft_is_versioned_audited_and_never_active_without_publish`、`test_oms_model_test_confirms_target_executors_without_activating`、`test_oms_model_publish_confirms_backend_and_becomes_runtime_active`、`test_oms_model_publish_failure_keeps_active_and_rollback_discards_bad_draft`。
- Provider 设置相关测试：`test_oms_provider_settings_are_versioned_redacted_confirmed_and_permissioned`。
- 企业 route allowlist：`test_enterprise_management_route_allowlist_is_narrow`。
- 本轮已运行上述 Provider/allowlist 目标测试与 ruff；最终回归会再次跑 `test_application.py` 相关切片。

限制：

- 6.3 完成的是后端正式 API 与执行者确认状态机；独立 OMS 正式前端接入、逐服务真实 adapter 探针和可计费学校测试仍归 6.4、Provider 设置 2.3/2.4 与 OMS 7.4/7.5。

## 2026-09-30 正式 OMS 前端/API 接线与本地回归同步

本节同步 2026-09-30 已由 `add-c1-c2-oms-operator-interface` 与 `add-enterprise-management-authorization` 验证的本地成果，不改变 7.4–7.7 真实执行/对账/成本门禁：

- 正式 OMS 独立前端：
  - `/oms` 使用正式受控入口读取 `/api/v1/oms/me`、`/me/permissions`、`/status/catalog`、`/resources/status`、`/models/draft`、`/provider-settings`、`/tenants`、`/supply`、`/schools/{school_id}/quota|usage|jobs`、`/audit`、`/cost`、`/permissions`、`/approvals` 与 `/skills` 安全 DTO。
  - 学校、资源、模型/Provider、供给、用量、审计、权限治理、Skill 均保留列表→详情抽屉；后端 display descriptor 优先呈现 raw 状态码；未授权或 DTO 失败时失败关闭，不回退原型或 mock。
  - `/oms/prototype*` 在非 development 服务端 `notFound()`；旧学校后台开通深链 `/oms/tms-bootstrap*` 返回 404。
- OMS 写入口：
  - Provider/模型草稿 test/publish/rollback、Skill review/publish/grant、学校服务 entitlement、quota grant/adjust/revoke/expire、供给批次 register/revoke 均已接正式 API。
  - 供给批次前端目前只开放基于安全 DTO `lot_id/version` 的撤销；补充供给 UI 未开放，因为缺少真实采购 evidence 输入合同，不能伪造 `evidence_ref`。
  - 供给 register/revoke 后端均经 `ops.supply.manage` platform 范围授权；school-scope operator 调用全局供给注册返回 403。
- 本地验证：
  - `npm test --prefix extensions/enterprise/frontends` → **27 files / 297 tests passed**。
  - `npm run typecheck:oms --prefix extensions/enterprise/frontends && npm run typecheck:tms --prefix extensions/enterprise/frontends && npm run build:oms --prefix extensions/enterprise/frontends && npm run build:tms --prefix extensions/enterprise/frontends` → **通过**。
  - `npm run lint --prefix extensions/enterprise/frontends` → **通过**。
  - `.venv/bin/python -m pytest extensions/enterprise/tests -q` → **803 passed, 3 skipped, 2 warnings**；其中迁移 catalog 期望清单已同步包含 `eduplus2/0014_actor_identity_context.sql`，未修改迁移本身。
  - `openspec validate add-enterprise-oms-business-logic --strict` → 见本轮验证记录；`git diff --check` → **通过**。
  - 只读 upstream mergeability smoke：merge-base `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`，`git merge-tree "$BASE" HEAD upstream/main` 未发现 `<<<<<<<`/`=======`/`>>>>>>>` 冲突标记，未执行 merge/rebase/reset。

任务影响：新增勾选 **3.2.1、6.4.1、6.5.1**。父任务 **3.2、6.4、6.5、7.4–7.7** 仍不关闭；全服务真实 adapter 探针、真实 CLI/HTTP/WS/SDK/后台执行准入、供应商 usage 对账、OMS-only 成本、真实采购补充 UI、test-cn 跨学校/真实账号综合验收仍待完成。

## 2026-09-30 OMS-only 未核定成本安全投影切片（7.6.1 完成；7.6 父任务未完成）

本轮只推进 OMS 逻辑，不扩展 TMS：`GET /api/v1/oms/cost` 由原先固定空响应改为调用 `oms.governance.cost_projection()`。入口仍先经 OMS Bearer/在线账号状态与 DeepTutor Enterprise 本地 PEP 复核 `ops.oms.access` 和 `ops.cost.read`，且 `ops.cost.read` 仍为 platform 范围敏感读取；未获该权限时沿用 403 失败关闭。由于 `oms.usage_attempts` 对租户账本启用 FORCE RLS，成本投影先以全局只读事务枚举本地学校，再逐学校使用 `TenantScope` 聚合 usage attempt，避免为了平台视图绕过 RLS 或把 PG role 当作应用授权。

DTO 只新增 `uncosted_usage`：按 `school_id/service_id/provider_id/provider_account_id/model_id/unit_code` 聚合 attempt 数、`settled_units` 和 `pending_units`（`reserved_units - settled_units` 的非负和），并复用后端 `not_configured` display descriptor 说明当前成本规则未配置。`costs` 继续为空，`notice` 明确“不会从配额或用量推导经营成本”。响应不包含采购 evidence、`evidence_ref`、`provider_request_id`、诊断原文、Secret、金额、单价、币种、账单、欠费或租户费用字段；供应商合同未核实时只显示用量待核定摘要，不能把缺成本解释为零成本。

TDD 红灯：`test_oms_governance_read_api_filters_by_local_school_grants_and_descriptors` 先写入一条合成 `remote_unknown` usage attempt 和一条带 `contract://safe` 的 supply lot，期望 `/api/v1/oms/cost` 返回 `uncosted_usage` 且不泄露合同引用、provider receipt、诊断、金额/单价；旧实现因缺少 `uncosted_usage` 失败。绿灯实现后，同一测试通过，并继续验证 usage/jobs/supply/audit 的原有脱敏与跨学校 403 行为。

验证：

- `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -k "oms_governance_read_api_filters_by_local_school_grants_and_descriptors" -q` → **1 passed, 54 deselected**。
- `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -q` → **54 passed, 1 skipped, 2 warnings**（两个既有同步测试继承全局 asyncio mark 的 PytestWarning）。
- `.venv/bin/python -m ruff check extensions/enterprise/src/deeptutor_enterprise/oms/governance.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py` → **通过**。

限制：本切片不是完整 7.6。尚未实现真实供应商成本合同/币种/分摊规则、人工核对/更正写命令、成本导出、真实 provider usage 对账、test-cn 真实学校/账号/供应商端到端验收，也未完成 7.4/7.5 的真实执行边界与逐 attempt 结算接线；因此 7.6、7.7 继续保持未完成。

## 2026-09-30 OMS 人工核对结算写入口切片（7.6.2 完成；7.6 父任务未完成）

本轮只推进 OMS 后端逻辑，不扩展 TMS：新增 `POST /api/v1/oms/schools/{school_id}/attempts/{attempt_id}/settle`，用于平台运营在供应商对账或可信人工核对后，对已发出但 `remote_unknown`/`reconcile_required` 的 attempt 做一次幂等结算。入口先经 OMS Bearer、在线账号状态与 DeepTutor Enterprise 本地 PEP 校验 `ops.oms.access` 和目标学校范围 `ops.reconciliation.manage`；随后 `OmsAttemptLedger.settle_as_reconciler()` 在同一个 `TenantScope` 账务事务中再次以 `_lock_school_id` 复核该动作权限并锁定 attempt/供给/分摊行，避免撤权与写入竞态。

结算写入保留原始证据但不回显：请求中的 `evidence_ref`、`provider_request_id` 和 source 写入 `oms.usage_attempts.evidence`、`provider_request_id` 及 `oms.attempt_evidence_events`；HTTP 响应只返回 `attempt_id/status/settled_units`，审计 `safe_summary` 只含 service、settled units 与 source，避免供应商 receipt、工单引用或合同线索进入普通响应/审计摘要。若核对量不超过预留，则按既有分摊逐笔把 reserved 转为 settled，未用且供给/授予仍有效的部分退回 unspent；若核对量超过预留，则保持 `reconcile_required` 并返回 409，后续仍需更完整的 overage/调整流程。该写入口不创建租户费用、不生成成本金额、不改写原始待核对事件，也不授予 TMS 任何写能力。

TDD 红灯：先写 `test_oms_reconciliation_settles_remote_unknown_attempt_with_school_scope_permission`，构造真实 OMS 双主体权限、学校绑定、供给批次、服务授权、额度承诺和一条 `remote_unknown` attempt；旧实现因 route 未注册返回 404。绿灯实现后，该测试验证：仅有 `ops.usage.read` 的 operator 调用结算 API 返回 403；拥有目标学校 `ops.reconciliation.manage` 的 operator 可结算 7/10 单位；响应不包含 `ticket-secret` 或 provider request secret；DB 中 attempt、commitment、supply、evidence events 和 `usage.settle` 审计均按预期更新且原始 evidence 仅留在数据库。

验证：

- `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -k "oms_reconciliation_settles_remote_unknown_attempt_with_school_scope_permission" -q` → **1 passed, 55 deselected**。
- `.venv/bin/python -m ruff check extensions/enterprise/src/deeptutor_enterprise/oms/attempts.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py` → **通过**。
- `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -q` → **55 passed, 1 skipped, 2 warnings**（两个既有同步测试继承全局 asyncio mark 的 PytestWarning）。

限制：本切片仍不是完整 7.6。尚未实现成本导出、已核定供应商成本合同/币种/分摊规则、真实 provider usage 自动对账、超预留人工调整闭环、test-cn 真实学校/账号/供应商端到端验收，也未完成 7.4/7.5 的真实 CLI/HTTP/WS/SDK/后台/Agent 执行边界与逐 attempt 结算接线；因此 7.6、7.7 继续保持未完成。

## 2026-09-30 OMS 待核对队列安全上下文投影（7.6.3 完成；7.6 父任务未完成）

为配合人工核对结算写入口，`GET /api/v1/oms/schools/{school_id}/jobs` 仍由目标学校 `ops.jobs.read` 保护，但待核对队列从只返回 attempt/service/status 扩展为 OMS 操作者可判断对象的安全上下文：`provider_id`、`provider_account_id`、`model_id`、`subject_kind`、`subject_id`、`user_id`、`app_id` 以及 `pending_units`。这些字段来自本地 usage attempt 事实，便于运营在不查看原始 evidence 的情况下定位供应商、模型和调用主体。DTO 继续不返回 `provider_request_id`、`evidence`、诊断 JSON、供应商 receipt、Secret 或合同引用；写入仍必须走 7.6.2 的 `ops.reconciliation.manage` 结算 API。

TDD 红灯：扩展 `test_oms_governance_read_api_filters_by_local_school_grants_and_descriptors`，要求 jobs DTO 包含 provider/model/subject/pending units；旧实现只返回基础字段而失败。绿灯实现后，同一测试继续验证 `provider_request_id` 和合成 `diagnostic` 不在响应文本中。

验证：

- `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -k "oms_governance_read_api_filters_by_local_school_grants_and_descriptors" -q` → **1 passed, 55 deselected**。
- `.venv/bin/python -m ruff check extensions/enterprise/src/deeptutor_enterprise/oms/governance.py extensions/enterprise/tests/test_application.py` → **通过**。

限制：本切片仍不是完整 7.6。待核对队列尚未实现导出、真实 provider 自动对账、超预留调整闭环或 test-cn 真实账号/供应商端到端验收；7.4/7.5 的真实执行边界与逐 attempt 结算接线仍未完成。

## 2026-09-30 OMS 学校用量安全导出切片（7.6.4 完成；7.6 父任务未完成）

新增 `GET /api/v1/oms/schools/{school_id}/usage/export`，用于 OMS 高权限操作者导出目标学校 usage attempt 的安全 JSON 快照。入口仍先经 OMS Bearer、在线账号状态与 DeepTutor Enterprise 本地 PEP 校验 `ops.oms.access`，再校验目标学校范围 `ops.audit.export`；只有被授权的学校可导出，跨学校目标返回 403。导出函数在 `TenantScope` 事务中读取本地 attempt 事实并写入 `oms.audit_events`，审计动作为 `usage.export`，safe summary 仅包含 `item_count` 与 `format`。

导出 DTO 只包含 attempt/operation/service/unit/provider/model/subject/status/reserved/settled/pending/time 等可核对字段；明确不返回 `evidence`、provider request id、provider receipt、diagnostic JSON、Secret、合同引用、金额、单价或成本字段。脱敏说明也使用类别化名称，避免把敏感字段名原样输出到导出文本。该端点不生成租户费用、不推导供应商成本，也不修改结算状态；实际核对写入仍必须走 7.6.2 的结算 API。

TDD 红灯：扩展 `test_oms_governance_read_api_filters_by_local_school_grants_and_descriptors`，给同一 school-scope 角色增加 `ops.audit.export` 后要求 `/usage/export` 返回安全 JSON、隐藏跨学校返回 403，并在 `/audit` 中看到 `usage.export` 审计；旧实现因 route 未注册返回 404。绿灯实现后，测试同时验证导出文本不包含 `provider_request_id`、合成 `diagnostic`、`contract://safe` 或 Secret/成本线索。

验证：

- `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -k "oms_governance_read_api_filters_by_local_school_grants_and_descriptors" -q` → **1 passed, 55 deselected**。
- `.venv/bin/python -m ruff check extensions/enterprise/src/deeptutor_enterprise/oms/governance.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py` → **通过**。
- `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -q` → **55 passed, 1 skipped, 2 warnings**（两个既有同步测试继承全局 asyncio mark 的 PytestWarning）。

限制：本切片仍不是完整 7.6。尚未实现真实 provider 自动对账、已核定供应商成本合同/币种/分摊规则、超预留人工调整闭环或 test-cn 真实账号/供应商端到端验收；7.4/7.5 的真实执行边界与逐 attempt 结算接线仍未完成。

## 2026-09-30 OMS 确认未发出释放入口切片（7.6.5 完成；7.6 父任务未完成）

新增 `POST /api/v1/oms/schools/{school_id}/attempts/{attempt_id}/release`，用于 OMS 操作者在确认供应商未收到请求、attempt 仍处于 `reserved` 且未 dispatch 时释放保守预留。入口先经 OMS Bearer、在线账号状态与 DeepTutor Enterprise 本地 PEP 校验目标学校范围 `ops.reconciliation.manage`；`OmsAttemptLedger.release_as_reconciler()` 在同一个 `TenantScope` 账务事务中以 `_lock_school_id` 再次复核该动作权限并锁定 attempt/供给/分摊行，避免撤权与释放竞态。

释放只适用于 `reserved` 状态；已经 dispatch、remote unknown、settled 或 released-with-conflicting-evidence 的 attempt 均拒绝，避免把可能已发生的远端消耗按失败零耗处理。成功释放时按原分摊逐笔把 reserved 归零，若支撑 grant/lot 仍有效则退回 unspent/committed_unspent；`usage_attempts` 写入 `status=released`、`settled_units=0` 和 `source=confirmed_not_sent` 的 evidence，`attempt_evidence_events` 留存 `confirmed_not_sent` 原始证据引用，HTTP 响应和审计 safe summary 不回显原始 evidence。

TDD 红灯：扩展 `test_oms_reconciliation_settles_remote_unknown_attempt_with_school_scope_permission`，在已结算一条 `remote_unknown` attempt 后重新预留 3 个单位并要求只读 operator 调 release 返回 403、reconcile operator 可释放且响应不包含 `not-sent-secret`；旧实现因 route 未注册返回 404。绿灯实现后，同一测试验证 release attempt 状态、evidence events、grant commitment 与 supply counters 均保持可核对一致。

验证：

- `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -k "oms_reconciliation_settles_remote_unknown_attempt_with_school_scope_permission" -q` → **1 passed, 55 deselected**。
- `.venv/bin/python -m ruff check extensions/enterprise/src/deeptutor_enterprise/oms/attempts.py extensions/enterprise/src/deeptutor_enterprise/oms/governance.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py` → **通过**。
- `.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -q` → **55 passed, 1 skipped, 2 warnings**（两个既有同步测试继承全局 asyncio mark 的 PytestWarning）。

限制：本切片仍不是完整 7.6。尚未实现真实 provider 自动对账、已核定供应商成本合同/币种/分摊规则、超预留人工调整闭环或 test-cn 真实账号/供应商端到端验收；7.4/7.5 的真实执行边界与逐 attempt 结算接线仍未完成。

## 2026-09-30 Provider request ID 对账切片（7.5.1 完成；7.5/7.6 父任务未完成）

本轮继续只推进 OMS 后端逻辑，不扩展 TMS，也不调用真实供应商。`OmsAttemptLedger.mark_dispatched()` 现在可在发出 intent 时记录供应商 request/task ID，并把该 ID 写入 append-only `attempt_evidence_events`；同一 attempt 后续只能幂等复用相同 provider request ID，冲突 ID 直接拒绝，避免一个 provider receipt 被错误挂到另一笔 attempt。`UsageCallContext.safe_request_hash()` 同步加强为递归、大小写无关地拒绝 `prompt/messages/answer/content/attachment(s)` 等私有正文 key，`UsageCallContext.attempt()` 也在生成 `AttemptRequest` 前校验 user/delegated_user/app/service 主体归属，防止真实执行边界把错误 user/app 组合带入总账。

新增 `POST /api/v1/oms/schools/{school_id}/usage/provider-receipts`：入口先经 OMS Bearer、在线账号状态与本产品 `ops.oms.access`/目标学校 `ops.reconciliation.manage` 授权，再按 `provider_id/provider_account_id/provider_request_id` 在该学校账本中找回原 attempt，并调用同一 `settle_as_reconciler()` 事务结算。重复供应商回执返回同一结算结果，不再次扣减；未知 provider request ID 返回冲突，不按零消耗释放预留。HTTP 响应仍只返回 `attempt_id/status/settled_units`，不回显 provider receipt、evidence、Secret 或账单内容；原始 evidence 仅留在 `usage_attempts.evidence` 与 append-only evidence events 中。

TDD 红灯：

- `test_provider_request_receipt_reconciles_original_attempt_once` 先失败于 `mark_dispatched()` 不接受 `provider_request_id`，后验证 provider request ID 回填、按 receipt 幂等结算、未知 receipt 失败关闭、冲突 request ID 拒绝及总账不双扣。
- `test_oms_reconciliation_settles_remote_unknown_attempt_with_school_scope_permission` 扩展后先失败于 provider receipt API 404，后验证只读 operator 403、reconcile operator 可按 provider request ID 结算原 attempt，响应不回显 receipt。
- `test_usage_request_hash_rejects_private_content_and_is_deterministic` 与 `test_usage_call_context_rejects_invalid_subject_attribution` 先分别失败于嵌套私有正文 key 未拒绝、错误主体归属未拒绝，后通过。

验证：

- `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_oms_attempt_ledger.py --tb=short` → **16 passed**。
- `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_oms_call_context.py --tb=short` → **3 passed**。
- `.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_reconciliation_settles_remote_unknown_attempt_with_school_scope_permission --tb=short` → **1 passed**。
- `ruff check` 覆盖 `oms/attempts.py`、`oms/call_context.py`、`api/application.py` 与相关测试 → **通过**。

限制：本切片只是 request/task ID 级别的本地 OMS 对账能力，不等于真实供应商自动对账完成。仍缺真实 provider adapter 调用样本、可核验账单批处理、pending 告警、流式/异步取消/Agent 子调用全入口接线、真实非 Token 原生单位样本、test-cn 真实账号/学校/供应商端到端验收及成本合同/分摊规则；因此 7.5、7.6、7.7 继续保持未完成。

## 2026-09-30 Metered provider attempt runner 切片（7.4.1 完成；7.4 父任务未完成）

新增企业扩展内的可复用 `run_metered_provider_attempt()` 与 `ProviderAttemptReceipt`。该 runner 不让 core 依赖 OMS 余额逻辑：调用方传入不含正文的 `UsageCallContext`、`TenantScope` 与 provider callable；runner 在真实 callable 前生成 attempt、执行 `reserve()` 并记录 dispatch intent，成功返回可信 receipt 时回填 provider request ID 并结算，provider callable 在发出后抛错或返回无 usage 时把 attempt 标为 `remote_unknown`，保留预留等待后续 receipt/人工对账。`call` 只拿到 `attempt_id`，不会接收 prompt、回答或附件正文。

TDD 红灯：`test_metered_provider_attempt_runner_settles_or_marks_unknown` 先失败于缺少 `ProviderAttemptReceipt`/runner，后验证合成 provider 成功样本按 6/10 单位结算并回填 request ID，发出后 timeout 样本进入 `remote_unknown` 且 5 单位预留不释放；账本不变量为 `settled_lifetime=6, committed_unspent=69, reserved_inflight=5`。

验证：`.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_oms_attempt_ledger.py extensions/enterprise/tests/test_oms_call_context.py --tb=short` → **20 passed**；`ruff check` 覆盖 `oms/call_context.py` 与相关测试 → **通过**。

限制：runner 仍只是企业扩展内可用适配层，尚未接入真实 CLI/HTTP/WS/SDK/后台/Agent 子调用和逐服务 provider adapter；因此 7.4 继续保持未完成。
