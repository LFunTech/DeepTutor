# 设计说明

## Context

本 change 从原 M1/G1 单租户生产基线中拆出 M1 固定租户 runtime 边界。它回答“DeepTutor 企业 runtime 在固定租户下应该如何认证、授权、读取状态、处理资源、调用检索和生成可供发布流水线验收的 smoke/evidence”。它不回答“Woodpecker/K8s 如何构建、部署、回退和归档 release evidence”。

本设计遵守仓库级约束：保持 upstream mergeability，企业特有逻辑放在 `extensions/enterprise/`；core 修改只允许作为通用 seam。DeepTutor 应用进程只直接访问应用 PG、DeepTutor 业务 ObjectStore、Secret/Settings provider 和 LightRAG Server API；不得把 LightRAG 内部 PG/HugeGraph 凭证或迁移职责放入 DeepTutor 业务进程。

## 运行边界

```text
Browser / Fronting App / SDK
        │
        ▼
DeepTutor enterprise runtime（固定 tenant binding）
        ├── 应用 PostgreSQL（tenant/identity/session/message/turn/audit/resource binding）
        ├── S3-compatible ObjectStore（业务文件、附件、KB 原文、workspace outputs）
        ├── Secret/Settings provider（模型、EduPlus2、ObjectStore、LightRAG API secret ref）
        ├── EduPlus2 exchange / audit API
        └── LightRAG Server API（服务 binding）
                   ├── 检索 PostgreSQL（LightRAG 内部）
                   └── HugeGraph（LightRAG 内部图后端）
```

固定租户只表示 runtime 绑定一个明确 tenant、授权边界和 smoke scope。它不决定 Woodpecker server/agent 类型、CI 后端、审批门禁、Secret 发放方式、registry、K8s namespace、Ingress/TLS、SecretStore、NetworkPolicy、发布锁、回退策略或 evidence 存放位置。

## 决策 1：运行基线只暴露可被发布流水线调用的契约

本 proposal 输出 runtime readiness、smoke harness 和脱敏 evidence 摘要，供本地/集成验证和独立 G1 发布流水线复用。发布流水线可以调用这些能力，但不能反向把 Woodpecker/K8s 目标环境假设写入固定租户 runtime。

## 决策 2：生产配置只保存引用和脱敏状态

| 层级 | 内容 | 约束 |
| --- | --- | --- |
| 非敏感 runtime 清单 | runtime mode、固定 tenant、feature gate、service binding ref | 可进入 ConfigMap/manifest；可被 release evidence 引用 |
| Secret ref | DB credential、ObjectStore access key、模型 key、EduPlus2 client secret、LightRAG API secret | 只记录 ref，不把明文写入 spec/evidence/log |
| 运行状态 | schema version、readiness、request id、审计 request id | 脱敏持久化，可用于排障 |

任何 production runtime 发现需要本地 `data/` 权威、SQLite、明文 Secret、未登记 provider、未就绪 ObjectStore/LightRAG 或漂移 migration，均 fail closed。

## 决策 3：第三方资源提交采用 pre-signed upload + resource binding

资源输入基线采用“DeepTutor 发放上传授权、第三方直传 ObjectStore、提交 turn 时引用资源、DeepTutor 内部读取并转交模型/RAG adapter”的模式：

1. 第三方应用申请 upload intent，声明 `modality`、`mime_type`、`size_bytes`、`sha256`、`purpose`、`session_id` 或业务关联；
2. DeepTutor 按固定 tenant/owner/session 生成不透明 `resource_id` 和内部 ObjectStore key，返回短 TTL pre-signed upload URL、policy headers、过期时间和限制；
3. 调用方直传 ObjectStore，bucket 不允许 public-read，调用方不得自选 key 前缀；
4. 上传完成后，调用方 complete 或在 turn 中携带 `prompt + resource_ids`；DeepTutor 以 binding 和 ObjectStore `HEAD` 为权威校验 owner、tenant、size、MIME、checksum、状态和 TTL；
5. 模型/RAG/多模态 adapter 只能通过 DeepTutor ObjectStore abstraction 获取资源。若 provider 支持 URL 输入，adapter 只生成短 TTL pre-signed read URL；否则后端读取 bytes 并转换为 provider-specific content block。

WebSocket 不承载二进制上传，不新增 `upload` 类长连接命令；上传授权和完成确认走 HTTP/维护 API，WebSocket `start_turn` 只携带文本 prompt 与资源引用。

## 决策 4：固定租户迁移与启动职责分离

固定 tenant bootstrap、默认 policy/profile 初始化和 schema version 校验必须是幂等、可由外部发布步骤或维护命令控制的操作。应用普通 startup/lifespan 只读取/校验版本，不在 Pod 启动时抢跑非幂等迁移。

该设计为 G1 发布流水线保留 migration Job 接入点，但本 proposal 不定义 Woodpecker 或 K8s Job 的具体实现。

## 决策 5：Smoke 走真实 runtime 入口，负例和脱敏同等重要

固定租户 runtime smoke 至少覆盖：

- auth/status 与固定租户身份；
- EduPlus2 user JWT exchange → `dt_token`；
- WebSocket `/api/v1/ws` 认证、`start_turn`、stream done、`auth_refresh`；
- session list/detail/history、owner guard 负例；
- pre-signed upload、ObjectStore 写读删或授权下载；
- `start_turn.resource_ids` 资源引用；
- audit query/export 的权限与脱敏；
- LightRAG/KB 检索链路（目标环境具备服务和样本语料时执行；否则输出未验证阻断）；
- 过期/撤销/身份不匹配 token、Secret 缺失、ObjectStore/LightRAG unavailable、SQLite/local fallback、跨 owner/伪造 tenant 等负例。

Smoke 输出只包含 run ID、request id、短 hash、状态码、错误 code 和证据路径，不输出 JWT、`dt_token`、client secret、模型 key、完整用户资料或私密内容。

## 决策 6：B/C/H 只做边界和回归，不在 M1 偷交付

M1 固定租户 runtime 需要为未来 B1/B2/C1/C2/H 留出兼容接口与证据，但不实现：

- 不上线 TMS/OMS 入口；
- 不开放多租户自助治理；
- 不做在线 client registry UI；
- 不承诺实时撤权 SLA；
- 不启用多执行者/HA。

相应任务只做“入口未暴露、契约未破坏、scope/权限不被绕过、后续迁移不被堵死”的验证。

## 与 G1 发布流水线的接口

`add-g1-woodpecker-k8s-release-baseline` 可以依赖本 change 提供：

- runtime readiness 命令/API；
- smoke harness 与 dry-run smoke；
- release evidence 可引用的脱敏 runtime 摘要；
- 固定 tenant、owner、resource、KB、audit 的负例集合；
- upstream-neutral core seam 清单。

发布流水线不得将目标 Woodpecker/K8s 拓扑写回本 runtime baseline，也不得因固定租户而推导 CI/K8s 安全边界。
