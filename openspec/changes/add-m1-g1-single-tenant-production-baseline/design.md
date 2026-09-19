# 设计说明

## Context

M1/G1 单租户生产基线位于已有企业化切片和未来多租户/TMS/OMS 之间。它的目标是把已实现/已规划的 PG-only、外置资源、EduPlus2 API-only 接入、企业组合根和 K8s 无状态运行要求，整理成一个可执行的生产发布闭环。

本设计遵守仓库级约束：保持 upstream mergeability，企业特有逻辑放在 `extensions/enterprise/` 或部署制品中；core 修改只允许作为通用 seam。DeepTutor 应用进程只直接访问应用 PG、DeepTutor 业务 ObjectStore、Secret/Settings provider 和 LightRAG Server API；不得把 LightRAG 内部 PG/HugeGraph 凭证或迁移职责放入 DeepTutor 业务进程。

## 目标拓扑

```text
Browser / Fronting App / SDK
        │
        ▼
Ingress + TLS + allowed origins
        │
        ├── DeepTutor frontend Deployment
        │
        └── DeepTutor enterprise backend Deployment（单执行模式）
              ├── 应用 PostgreSQL（tenant/identity/session/message/turn/audit/resource binding）
              ├── S3-compatible ObjectStore（业务文件、附件、KB 原文、workspace outputs）
              ├── Secret/Settings provider（模型、EduPlus2、ObjectStore、LightRAG API secret ref）
              ├── EduPlus2 exchange / audit API
              └── LightRAG Server API（服务 binding）
                         ├── 检索 PostgreSQL（LightRAG 内部）
                         └── HugeGraph（LightRAG 内部图后端）
```

M1 只开放固定租户生产基线。多租户逻辑从 schema/权限/测试角度保留，但不开放租户自助/TMS/OMS 管理能力。

## 设计前提：租户模式不决定 K8s/Woodpecker 拓扑

“单租户”在本 proposal 中只表示 M1/G1 的 runtime 边界：固定 tenant binding、固定授权边界、固定 smoke scope 和禁止开放多租户治理入口。它不决定 Woodpecker server/agent 类型、CI 后端、审批门禁、Secret 发放方式、registry、K8s namespace、Ingress/TLS、SecretStore、NetworkPolicy、发布锁、回退策略或 evidence 存放位置。

因此 A3 的 K8s/Woodpecker 实施必须先有目标部署契约，再产出可执行制品。没有目标契约时，只能实现配置校验、smoke/evidence 工具和待接入说明；不能用通用 YAML 或凭“单租户”推断出的 pipeline 当作 A3 完成证据。

## 决策 1：G1 以发布闭环为交付，不以单个功能 demo 为交付

EduPlus2 前置 demo 用于 local/test 联调，它证明一条认证与 WS 对话路径可以工作，但无法替代 G1。G1 必须由可重复 pipeline 与目标环境 smoke 证明：构建、迁移、部署、运行、回退和证据归档都可执行。

因此本 proposal 的主交付是：部署源、流水线、smoke、runbook、evidence 和 fail-closed gate。功能实现只补足这些闭环所暴露的真实缺口，不扩大到 B/C 里程碑。

## 决策 2：生产配置只保存引用和脱敏状态

生产 runtime 配置分三层：

| 层级 | 内容 | 约束 |
| --- | --- | --- |
| 非敏感部署清单 | runtime mode、固定 tenant、endpoint、feature gate、image digest、service binding ref | 可进入 ConfigMap/manifest；纳入 release evidence |
| Secret ref | DB credential、ObjectStore access key、模型 key、EduPlus2 client secret、LightRAG API secret | 只记录 ref，不把明文写入 spec/evidence/log |
| 运行状态 | schema version、readiness、release id、smoke run id、审计 request id | 脱敏持久化，可用于排障 |

任何生产入口发现需要本地 `data/` 权威、SQLite、明文 Secret、未登记 provider、未就绪 ObjectStore/LightRAG 或漂移 migration，均 fail closed。


## 决策 2A：第三方资源提交采用 pre-signed upload + resource binding

M1/G1 的生产资源输入基线采用“DeepTutor 发放上传授权、第三方直传 ObjectStore、提交 turn 时引用资源、DeepTutor 内部读取并转交模型/RAG adapter”的模式。该模式用于普通附件、KB 原文样本，也为后续图片/音频/视频多模态输入预留同一安全边界。

推荐顺序：

1. 第三方应用调用 DeepTutor 资源上传意图接口，声明 `modality`、`mime_type`、`size_bytes`、`sha256`、`purpose`、`session_id` 或业务关联；M1/G1 生产路径要求 `sha256` 必填，以便上传完成确认和 turn 引用校验均可 fail-closed；
2. DeepTutor 按固定 tenant/owner/session 生成不透明 `resource_id` 和内部 ObjectStore key，返回短 TTL 的 pre-signed upload URL、必须携带的 headers/policy、过期时间和大小/MIME 限制；
3. 第三方应用使用该 URL 直接上传到 S3-compatible ObjectStore；bucket 不允许 public-read，调用方不得自选任意 key 前缀；
4. 上传完成后，调用方执行资源完成确认，或在提交 turn 时携带 `prompt + resource_ids`；DeepTutor 对 ObjectStore 执行 `HEAD`/metadata 校验，确认 owner、tenant、size、MIME、checksum、状态和 TTL 后才把资源标记为可用；
5. 模型、RAG 或后续多模态 adapter 只能通过 DeepTutor ObjectStore abstraction 获取资源。若目标 provider 支持 URL 输入，adapter 只生成短 TTL pre-signed read URL；否则由后端读取 bytes 并转换为 provider-specific content block；两者都不得把内部 key、长期 URL 或 Secret 暴露给调用方。

外部 API SHOULD 使用 `resource_id` 作为提交引用；ObjectStore key 是内部 locator，只能进入脱敏 evidence/audit 摘要。若为了兼容旧调用方必须接受 resource key，系统 MUST 校验该 key 由 DeepTutor 发行、绑定当前 owner/tenant/session/purpose，且仍在允许状态内。

HTTP 与 WebSocket turn submission 使用同一语义。WebSocket 不承载二进制上传，不新增 `upload` 类长连接命令；上传授权和完成确认走 HTTP/维护 API，WebSocket `start_turn` 只携带文本 prompt 与资源引用，例如：

```json
{
  "type": "start_turn",
  "protocol_version": "2.0",
  "session_id": "...",
  "content": "请分析这些材料",
  "resource_ids": ["res_..."]
}
```

实现层 MAY 将 `resource_ids` 规范化为 `resource_references`，但调用方提供的 `mime_type`、`sha256`、`modality` 只能作为校验提示，不能作为权威。权威 metadata 来自 DeepTutor resource binding 与 ObjectStore `HEAD` 结果。现有 `attachments.url`/`attachments.base64` 只能作为 legacy/local 兼容路径；production enterprise runtime 不得把未登记 URL 或大 base64 当作模型输入主路径。

该决策替代“调用方把任意外部 URL、大 base64 或未登记路径直接交给模型”的方案。生产入口接收未登记 URL、未完成上传、checksum/hash mismatch、MIME/大小超限、过期上传、跨 owner/tenant 资源、被删除/隔离资源或 provider 不支持的 modality 时，必须 fail closed 并留下脱敏审计。

多模态处理本身不在 M1/G1 完整交付范围内；M1/G1 只要求该资源输入契约不会阻断后续多模态扩展，并能在 smoke/evidence 中证明资源上传、绑定、读取、拒绝和脱敏链路成立。

## 决策 3：迁移由独立 Job 执行，应用启动只做版本校验

应用 PG migration、固定租户 bootstrap、默认 policy/profile 初始化由 pipeline 中的独立 Job 执行：

1. 获取发布锁和数据库迁移锁；
2. 校验目标环境、当前版本、历史 drift 和 pending release；
3. plan/apply/verify，并将 schema version 和 release id 写入 evidence；
4. 应用 Deployment 启动时只读取/校验版本，不自动迁移；
5. 失败阻断 rollout，不允许 `|| true` 或逐 Pod 抢跑。

LightRAG 内部 PG/HugeGraph 迁移不属于 DeepTutor 应用 Job。DeepTutor release 只能引用 LightRAG 部署记录、API 契约版本、workspace/index-version binding 和 readiness；图/检索 schema 由 LightRAG 侧 Job/运维流程负责。

## 决策 4：首发保持单执行，禁止 rollout 期间执行者重叠

M1 首发为单执行模式。Deployment/rollout 需要显式策略：

- 业务执行者限制为一个实际 writer/executor；
- 发布前停止接新 turn 或进入维护/排空；
- 确认旧执行者终止后启动新执行者；
- `replicas: 1` 不能单独证明无重叠，pipeline 必须有排空/锁/状态确认；
- 多执行者、跨 Pod fanout 或 HA 需求触发时，先通过 G-H，不在本 proposal 中顺手开启。

Frontend 或无执行权组件可独立滚动，但不能因此把 backend execution 也改为无门禁滚动。

## 决策 5：Smoke 走真实入口，负例和脱敏同等重要

M1 smoke 不只检查 `/health`。最低集合：

- Ingress/TLS/front-end 可达；
- auth/status 与固定租户身份；
- EduPlus2 user JWT exchange → `dt_token`；
- WebSocket `/api/v1/ws` 认证、`start_turn`、stream done、`auth_refresh`；
- session list/detail/history、owner guard 负例；
- ObjectStore readiness 与一次业务对象写读删或授权下载；
- audit query/export 的权限与脱敏；
- LightRAG/KB 检索链路（目标 test 环境已配置服务和样本语料时必须执行；否则 G1 记录为阻断依赖，不可声明完整生产上线）；
- 过期/撤销/身份不匹配 token、Secret 缺失、ObjectStore/LightRAG unavailable、SQLite/local fallback、跨 owner 等负例。

Smoke 输出只包含 run ID、request id、短 hash、状态码、错误 code 和证据路径，不输出 JWT、`dt_token`、client secret、模型 key、完整用户资料或私密内容。

## 决策 6：回退是应用/配置/依赖组合回退，不是数据库回滚

回退流程按发布清单组合执行：镜像 digest、非敏感配置、schema 兼容性、ObjectStore binding、LightRAG binding、feature gate 必须一致。应用回退不自动降库；若 migration 不兼容旧应用，则不能回退旧应用继续写入，应进入维护模式、前向修复或按已演练的成套恢复方案执行。

回退成功必须重跑 smoke 并保存 evidence；失败发布本身仍保留失败记录，不能被通知成功覆盖。

## 决策 7：B/C/H 只做边界和回归，不在 M1 偷交付

M1/G1 需要为未来 B1/B2/C1/C2/H 留出兼容接口与证据，但不实现：

- 不上线 TMS/OMS 入口；
- 不开放多租户自助治理；
- 不做在线 client registry UI；
- 不承诺实时撤权 SLA；
- 不启用多执行者/HA。

相应任务只做“入口未暴露、契约未破坏、scope/权限不被绕过、后续迁移不被堵死”的验证。

## Evidence 结构

建议每次 G1 候选生成一个 evidence 目录或对象：

```text
release-evidence/
  <release-id>/
    manifest.yaml              # 脱敏发布清单
    build.json                 # 源码 SHA、镜像 digest、SBOM/scan 摘要
    migration.json             # plan/apply/verify、schema version、drift 结果
    deploy.json                # rollout、probe、release lock、单执行状态
    smoke.json                 # run id、cases、request id、脱敏摘要
    rollback.json              # 未执行则写明原因；执行则记录步骤与结果
    upstream-compat.md         # core patch 清单、upstream merge 风险、回归命令
    unresolved.md              # 未验证项、阻断项、环境前提
```

证据可进入受控对象存储、CI artifact 或审计系统，但不得包含明文 Secret/token。
